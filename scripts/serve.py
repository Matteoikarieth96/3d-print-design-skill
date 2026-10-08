#!/usr/bin/env python3
"""Local preview server for STL files (stdlib only).

    python serve.py out/            -> prints http://127.0.0.1:<port>/
    python serve.py out/ --open     -> also opens your browser
    python serve.py out/ --bed 180x180x180 --color cable-clip=#2bb673

What it does:
- binds 127.0.0.1 only, on a free port (or --port), never a public address;
- serves the viewer page plus the files of ONE folder (no subfolders, no
  directory listing, no "..", no symlinks, only .stl .json .svg .png);
- writes <folder>/manifest.json listing every STL with a colour and the bed
  size, and refreshes it each time the page loads it;
- rejects requests whose Host header is not 127.0.0.1/localhost (blocks DNS
  rebinding from web pages).

It never contacts a printer and never sends anything anywhere: three.js is the
only external file and the browser fetches it from cdnjs with an integrity hash.
Stop it with Ctrl+C.
"""
from __future__ import annotations

import argparse
import json
import re
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

PAGE_CSP = ("default-src 'none'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def parse_bed(text: str) -> Tuple[float, float, float]:
    m = BED_RE.fullmatch(text or "")
    if not m:
        raise ValueError(f"bed must look like 220x220x250, got {text!r}")
    dims = tuple(float(g) for g in m.groups())
    if not all(10 <= d <= 3000 for d in dims):
        raise ValueError("bed dimensions must be between 10 and 3000 mm")
    return dims  # type: ignore[return-value]


def safe_child(folder: Path, name: str) -> Optional[Path]:
    """Return folder/name if it is a plain, allowed file directly inside folder, else None."""
    if not SAFE_FILE.fullmatch(name) or ".." in name:
        return None
    if Path(name).suffix.lower() not in FILE_TYPES:
        return None
    candidate = folder / name
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError, RuntimeError):
        return None
    if resolved.parent != folder or not resolved.is_file():
        return None
    return resolved


def build_manifest(folder: Path, bed: Optional[Sequence[float]] = None,
                   colors: Optional[Dict[str, str]] = None) -> dict:
    colors = colors or {}
    parts = []
    found_bed = None
    stls = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".stl" and safe_child(folder, p.name))
    for i, stl in enumerate(stls):
        stem = stl.stem
        color = colors.get(stem)
        meta = {}
        meta_path = safe_child(folder, f"{stem}.json")
        if meta_path:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
        parts.append({"file": stl.name, "name": stem, "color": color})
    bed_dims = tuple(bed) if bed else (found_bed or DEFAULT_BED)
    return {"bed": list(bed_dims), "parts": parts}


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "print-preview"
    sys_version = ""

    # set by make_server
    folder: Path
    bed: Optional[Sequence[float]] = None
    colors: Dict[str, str] = {}
    quiet = False

    def log_message(self, fmt, *args):  # keep the terminal tidy, never log query strings
        if not self.quiet:
            sys.stderr.write(f"serve: {self.command} {urlsplit(self.path).path} -> {args[1] if len(args) > 1 else ''}\n")

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
        raw_path = urlsplit(self.path).path
        path = unquote(raw_path)
        if "\x00" in path or "\\" in path or ".." in path or "//" in path:
            return self._error(400)
        if path in VIEWER_FILES:
            fname, ctype = VIEWER_FILES[path]
            body = (VIEWER_DIR / fname).read_bytes()
            return self._send(200, body, ctype, PAGE_CSP)
        if path == "/manifest.json":
            manifest = build_manifest(self.folder, self.bed, self.colors)
            body = json.dumps(manifest, indent=2).encode()
            try:
                (self.folder / "manifest.json").write_bytes(body + b"\n")
            except OSError:
                pass
            return self._send(200, body, "application/json")
        if path.startswith("/files/"):
            name = path[len("/files/"):]
            if "/" in name:
                return self._error(404)
            target = safe_child(self.folder, name)
            if target is None or target.stat().st_size > MAX_FILE_BYTES:
                return self._error(404)
            body = target.read_bytes()
            return self._send(200, body, FILE_TYPES[target.suffix.lower()])
        if path.startswith("/preview/") and path.endswith(".svg"):
            stem = path[len("/preview/"):-len(".svg")]
            stl = safe_child(self.folder, f"{stem}.stl") if "/" not in stem else None
            if stl is None:
                return self._error(404)
            try:
                part = next((p for p in build_manifest(self.folder, self.bed, self.colors)["parts"]
                             if p["name"] == stem), None)
                svg = svg_preview.render_svg(stl, color=(part or {}).get("color", PALETTE[0]), title=stem)
            except Exception:
                return self._error(500)
            return self._send(200, svg.encode(), "image/svg+xml")
        return self._error(404)

    def do_POST(self) -> None:  # noqa: N802
        self._error(405)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST


def make_server(folder, port: int = 0, bed: Optional[Sequence[float]] = None,
                colors: Optional[Dict[str, str]] = None, quiet: bool = False):
    """Create (not start) the server. Returns (server, url)."""
    root = Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"not a folder: {root}")
    for name, color in (colors or {}).items():
        if not HEX_COLOR.fullmatch(color) or not SAFE_FILE.fullmatch(name):
            raise ValueError(f"bad colour mapping {name}={color}: use part-name=#rrggbb")
    handler = type("BoundPreviewHandler", (PreviewHandler,),
                   {"folder": root, "bed": bed, "colors": dict(colors or {}), "quiet": quiet})
    server = ThreadingHTTPServer((HOST, int(port)), handler)
    server.daemon_threads = True
    manifest = build_manifest(root, bed, colors)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
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
        print(f"serve: {exc}", file=sys.stderr)
        return 2
    n = len(build_manifest(Path(args.folder).resolve(), bed, colors)["parts"])
    print(f"serving {n} STL file(s) from {Path(args.folder).resolve()}")
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
