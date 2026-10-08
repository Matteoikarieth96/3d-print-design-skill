#!/usr/bin/env python3
"""Local preview server for STL files (stdlib only).

    python serve.py out/            -> prints http://127.0.0.1:<port>/
    python serve.py out/ --open     -> also opens your browser
    python serve.py out/ --bed 180x180x180 --color cable-clip=#2bb673

What it does:
- binds 127.0.0.1 only, on a free port (or --port), never a public address;
- serves the viewer page plus the files of ONE folder (no subfolders, no
  directory listing, no "..", only .stl .json .svg .png). Each file is opened
  with O_NOFOLLOW relative to a directory handle taken at start-up, then
  fstat-checked: symlinks, hard links, FIFOs and other non-regular files are
  refused, and there is no gap between the check and the read;
- writes <folder>/manifest.json once at start-up (atomically, never through a
  symlink); the page's /manifest.json is built in memory on each load, so new
  builds show up on reload without writing to disk;
- rejects requests whose Host header is not 127.0.0.1/localhost (blocks DNS
  rebinding from web pages); drops idle connections after 15 seconds.

It never contacts a printer and never sends anything anywhere: three.js is the
only external file and the browser fetches it from cdnjs with an integrity hash.
Stop it with Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svg_preview  # noqa: E402  stdlib-only fallback renderer, used when WebGL is missing
from safeio import atomic_write, safe_text  # noqa: E402

HOST = "127.0.0.1"  # fixed on purpose: there is no option to listen on other interfaces
VIEWER_DIR = Path(__file__).resolve().parent / "viewer"
VIEWER_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
    "/viewer.css": ("viewer.css", "text/css; charset=utf-8"),
}
FILE_TYPES = {
    ".stl": "model/stl",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
BED_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*$")
PALETTE = ["#4f8cff", "#2bb673", "#e0a030", "#d9534f", "#8e6cf0", "#20a4b8", "#c2569b", "#7a8b99"]
DEFAULT_BED = (220.0, 220.0, 250.0)
MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_META_BYTES = 1024 * 1024
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"

PAGE_CSP = (f"default-src 'none'; script-src 'self' {THREE_URL}; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"

O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
USE_DIR_FD = O_NOFOLLOW is not None and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")


def parse_bed(text: str) -> Tuple[float, float, float]:
    m = BED_RE.fullmatch(text or "")
    if not m:
        raise ValueError(f"bed must look like 220x220x250, got {safe_text(text, 40)!r}")
    dims = tuple(float(g) for g in m.groups())
    if not all(10 <= d <= 3000 for d in dims):
        raise ValueError("bed dimensions must be between 10 and 3000 mm")
    return dims  # type: ignore[return-value]


def allowed_name(name: str) -> bool:
    return bool(SAFE_FILE.fullmatch(name)) and ".." not in name and Path(name).suffix.lower() in FILE_TYPES


def open_child(folder: Path, name: str, dir_fd: Optional[int] = None, max_bytes: int = MAX_FILE_BYTES):
    """Open a plain file directly inside `folder` for reading, or return None.

    O_NOFOLLOW refuses a symlink as the last component; opening relative to
    `dir_fd` pins the directory itself; O_NONBLOCK keeps a FIFO from hanging
    the server. fstat on the open descriptor then requires a regular file
    with a single link (no hard link to a file elsewhere) within the size cap.
    Returns (binary file object, size); the caller closes it.
    """
    if not allowed_name(name):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        if O_NOFOLLOW is not None:
            flags |= O_NOFOLLOW
            if dir_fd is not None and USE_DIR_FD:
                fd = os.open(name, flags, dir_fd=dir_fd)
            else:
                fd = os.open(os.path.join(folder, name), flags)
        else:  # no O_NOFOLLOW (Windows): fall back to a resolve check
            candidate = Path(folder) / name
            if candidate.is_symlink() or candidate.resolve().parent != Path(folder).resolve():
                return None
            fd = os.open(candidate, flags)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > max_bytes:
            os.close(fd)
            return None
        return os.fdopen(fd, "rb"), st.st_size
    except BaseException:
        os.close(fd)
        raise


def _list_names(folder: Path, dir_fd: Optional[int]):
    try:
        if dir_fd is not None and os.listdir in os.supports_fd:
            return sorted(os.listdir(dir_fd))
        return sorted(os.listdir(folder))
    except OSError:
        return []


def build_manifest(folder: Path, bed: Optional[Sequence[float]] = None,
                   colors: Optional[Dict[str, str]] = None, dir_fd: Optional[int] = None) -> dict:
    colors = colors or {}
    parts = []
    found_bed = None
    stls = []
    for name in _list_names(folder, dir_fd):
        if not name.lower().endswith(".stl"):
            continue
        opened = open_child(folder, name, dir_fd)
        if opened:
            opened[0].close()
            stls.append(name)
    for i, fname in enumerate(stls):
        stem = fname[:-4]
        color = colors.get(stem)
        meta = {}
        opened = open_child(folder, f"{stem}.json", dir_fd, max_bytes=MAX_META_BYTES)
        if opened:
            fh, _ = opened
            try:
                with fh:
                    meta = json.loads(fh.read().decode("utf-8"))
                if not isinstance(meta, dict):
                    meta = {}
            except (ValueError, OSError):
                meta = {}
        if not color:
            c = meta.get("preview_color")
            color = c if isinstance(c, str) and HEX_COLOR.fullmatch(c) else PALETTE[i % len(PALETTE)]
        if found_bed is None and isinstance(meta.get("printer_bed"), list) and len(meta["printer_bed"]) == 3:
            try:
                cand = tuple(float(v) for v in meta["printer_bed"])
                if all(10 <= v <= 3000 for v in cand):
                    found_bed = cand
            except (TypeError, ValueError):
                pass
        parts.append({"file": fname, "name": stem, "color": color})
    bed_dims = tuple(bed) if bed else (found_bed or DEFAULT_BED)
    return {"bed": list(bed_dims), "parts": parts}


class PreviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, folder: Path, bed, colors, quiet: bool):
        self.folder = folder
        self.bed = bed
        self.colors = dict(colors or {})
        self.quiet = quiet
        self.dir_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY) if USE_DIR_FD else None
        try:
            super().__init__(address, handler)
        except BaseException:
            self._close_dir()
            raise

    def _close_dir(self):
        if self.dir_fd is not None:
            try:
                os.close(self.dir_fd)
            except OSError:
                pass
            self.dir_fd = None

    def server_close(self):
        super().server_close()
        self._close_dir()

    def manifest(self) -> dict:
        return build_manifest(self.folder, self.bed, self.colors, self.dir_fd)


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "print-preview"
    sys_version = ""
    timeout = 15  # seconds; a stalled client cannot pin a thread forever

    def log_message(self, fmt, *args):  # tidy, sanitised, never logs query strings
        if getattr(self.server, "quiet", False):
            return
        command = safe_text(getattr(self, "command", None) or "-", 10)
        path = safe_text(urlsplit(getattr(self, "path", "") or "").path, 120)
        sys.stderr.write(f"serve: {command} {path} -> {safe_text(args[1] if len(args) > 1 else '', 10)}\n")

    def send_error(self, code, message=None, explain=None):  # used by the base class on bad requests
        self.close_connection = True
        try:
            self._error(code)
        except Exception:
            pass

    def _headers(self, status: int, ctype: str, length: int, csp: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", csp)
        self.end_headers()

    def _send(self, status: int, body: bytes, ctype: str, csp: str = FILE_CSP) -> None:
        self._headers(status, ctype, len(body), csp)
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status: int) -> None:
        msg = f"{status} {HTTPStatus(status).phrase}\n".encode()
        self._send(status, msg, "text/plain; charset=utf-8")

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        host = (self.headers.get("Host") or "").strip().lower()
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return self._error(403)
        path = unquote(urlsplit(self.path).path)
        if "\x00" in path or "\\" in path or ".." in path or "//" in path:
            return self._error(400)
        if path in VIEWER_FILES:
            fname, ctype = VIEWER_FILES[path]
            body = (VIEWER_DIR / fname).read_bytes()
            return self._send(200, body, ctype, PAGE_CSP)
        if path == "/manifest.json":  # built in memory, never written here
            body = json.dumps(self.server.manifest(), indent=2).encode()
            return self._send(200, body, "application/json")
        if path.startswith("/files/"):
            name = path[len("/files/"):]
            opened = open_child(self.server.folder, name, self.server.dir_fd) if "/" not in name else None
            if opened is None:
                return self._error(404)
            fh, size = opened
            with fh:
                self._headers(200, FILE_TYPES[Path(name).suffix.lower()], size, FILE_CSP)
                if self.command != "HEAD":
                    shutil.copyfileobj(fh, self.wfile, 256 * 1024)
            return None
        if path.startswith("/preview/") and path.endswith(".svg"):
            stem = path[len("/preview/"):-len(".svg")]
            opened = None
            if "/" not in stem:
                opened = open_child(self.server.folder, f"{stem}.stl", self.server.dir_fd,
                                    max_bytes=svg_preview.MAX_STL_BYTES)
            if opened is None:
                return self._error(404)
            fh, _ = opened
            try:
                with fh:
                    part = next((p for p in self.server.manifest()["parts"] if p["name"] == stem), None)
                    svg = svg_preview.render_svg(fh, color=(part or {}).get("color", PALETTE[0]), title=stem)
            except ValueError:
                return self._error(413)
            except Exception:
                return self._error(500)
            return self._send(200, svg.encode(), "image/svg+xml")
        return self._error(404)

    def do_POST(self) -> None:  # noqa: N802
        self._error(405)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


def make_server(folder, port: int = 0, bed: Optional[Sequence[float]] = None,
                colors: Optional[Dict[str, str]] = None, quiet: bool = False):
    """Create (not start) the server and write manifest.json. Returns (server, url)."""
    root = Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"not a folder: {safe_text(root)}")
    for name, color in (colors or {}).items():
        if not HEX_COLOR.fullmatch(color) or not SAFE_FILE.fullmatch(name):
            raise ValueError(f"bad colour mapping {safe_text(name, 40)}={safe_text(color, 20)}: "
                             "use part-name=#rrggbb")
    server = PreviewServer((HOST, int(port)), PreviewHandler, root, bed, colors, quiet)
    try:
        atomic_write(root / "manifest.json", json.dumps(server.manifest(), indent=2) + "\n")
    except BaseException:
        server.server_close()
        raise
    url = f"http://{HOST}:{server.server_address[1]}/"
    return server, url


def serve_in_thread(folder, **kwargs):
    server, url = make_server(folder, **kwargs)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, url


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Serve one folder of STL files to the local 3D viewer.")
    ap.add_argument("folder", help="folder with .stl files (usually out/)")
    ap.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    ap.add_argument("--bed", default=None, help="bed size X x Y x Z in mm (default: from part metadata or 220x220x250)")
    ap.add_argument("--color", action="append", default=[], metavar="PART=#RRGGBB", help="colour for a part")
    ap.add_argument("--open", action="store_true", help="open the page in your default browser")
    args = ap.parse_args(argv)
    try:
        bed = parse_bed(args.bed) if args.bed else None
        colors = {}
        for item in args.color:
            name, _, color = item.partition("=")
            colors[name.strip()] = color.strip()
        if not 0 <= args.port <= 65535:
            raise ValueError("port must be 0..65535")
        server, url = make_server(args.folder, port=args.port, bed=bed, colors=colors)
    except (ValueError, OSError) as exc:
        print(f"serve: {safe_text(exc)}", file=sys.stderr)
        return 2
    n = len(server.manifest()["parts"])
    print(f"serving {n} STL file(s) from {safe_text(server.folder)}")
    print(f"open {url}  (Ctrl+C to stop)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
