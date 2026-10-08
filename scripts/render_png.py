#!/usr/bin/env python3
"""Render a PNG of the local viewer for a README or a print sheet (stdlib only).

    python render_png.py out/ --out docs/part.png
    python render_png.py out/ --out docs/part.png --view top --theme dark --section y

How: serves the folder on 127.0.0.1 (same server as serve.py), asks headless
Chrome for the page with SwiftShader WebGL, checks the page reported a real
3D render, then takes the screenshot. If WebGL does not render headless (or
three.js cannot be fetched), it falls back to the SVG orthographic picture
from svg_preview.py and rasterises that instead, and says so.

Chrome lookup: $CHROME_PATH, the macOS app path, then google-chrome /
chromium / chromium-browser on PATH. Chrome runs with a throwaway profile.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import serve  # noqa: E402
import svg_preview  # noqa: E402
from safeio import atomic_write, safe_text  # noqa: E402

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def find_chrome():
    env = os.environ.get("CHROME_PATH")
    if env and Path(env).is_file():
        return env
    if Path(MAC_CHROME).is_file():
        return MAC_CHROME
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _chrome_args(chrome, profile, w, h):
    return [chrome, "--headless=new", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--disable-background-networking", "--disable-component-update", "--disable-sync",
            "--use-mock-keychain", "--password-store=basic",
            f"--user-data-dir={profile}", f"--window-size={w},{h}", "--virtual-time-budget=15000"]


def _run_until(cmd, done, timeout):
    """Run Chrome until `done(stdout_text)` is true, then stop it.

    Some Chrome builds write the screenshot or DOM and then never exit, so we
    poll for the result instead of waiting for the process.
    """
    with tempfile.TemporaryFile() as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline and proc.poll() is None:
                out.seek(0)
                if done(out.read().decode("utf-8", errors="replace")):
                    time.sleep(0.5)
                    break
                time.sleep(0.25)
        finally:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except (OSError, AttributeError):
                    proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (OSError, AttributeError):
                        proc.kill()
                    proc.wait()
        out.seek(0)
        return out.read().decode("utf-8", errors="replace")


def _png_ready(path):
    def check(_text):
        try:
            return path.is_file() and path.stat().st_size > 0 and path.read_bytes()[-8:-4] == b"IEND"
        except OSError:
            return False
    return check


def render(folder, out, view="iso", theme="light", size="1400x900", section=None, timeout=90,
           force_svg=False):
    m = SIZE_RE.fullmatch(size)
    if not m:
        raise ValueError("size must look like 1400x900")
    w, h = int(m.group(1)), int(m.group(2))
    if view not in ("iso", "top", "front", "right"):
        raise ValueError("view must be iso, top, front or right")
    if theme not in ("light", "dark"):
        raise ValueError("theme must be light or dark")
    if section not in (None, "x", "y", "z"):
        raise ValueError("section must be x, y or z")
    out = Path(os.path.abspath(out))  # abspath, not resolve: a symlink must not be followed
    if out.suffix.lower() != ".png":
        raise ValueError("--out must end with .png")
    svg_out = out.with_suffix(".svg")
    for target in (out, svg_out):
        if target.is_symlink():
            raise ValueError(f"refusing to write through a symlink: {safe_text(target)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    server, url = serve.serve_in_thread(folder, quiet=True)
    try:
        with tempfile.TemporaryDirectory() as work:
            shot = Path(work) / "shot.png"  # Chrome writes here; we move it into place ourselves
            query = f"?ui=1&view={view}&theme={theme}" + (f"&section={section}" if section else "")
            method = "svg-fallback"
            if chrome and not force_svg:
                with tempfile.TemporaryDirectory() as profile:
                    base = _chrome_args(chrome, profile, w, h)
                    dom = _run_until(base + ["--dump-dom", url + query], lambda t: "</html>" in t, timeout)
                    state = re.search(r'<body[^>]*data-render="([a-z-]+)"', dom)
                    if state and state.group(1) == "ok":
                        _run_until(base + [f"--screenshot={shot}", url + query], _png_ready(shot), timeout)
                        if shot.is_file() and shot.stat().st_size > 5000:
                            method = "webgl"
            if method != "webgl":
                svg = _fallback_svg(server, view, theme, w, h)
                if not chrome:
                    atomic_write(svg_out, svg)
                    return "svg-only", svg_out
                svg_tmp = Path(work) / "preview.svg"
                svg_tmp.write_text(svg, encoding="utf-8")
                with tempfile.TemporaryDirectory() as profile:
                    _run_until(_chrome_args(chrome, profile, w, h) + [f"--screenshot={shot}", svg_tmp.as_uri()],
                               _png_ready(shot), timeout)
                if not shot.is_file():
                    atomic_write(svg_out, svg)
                    return "svg-only", svg_out
            if shot.stat().st_size > 600 * 1024 and shutil.which("sips"):
                subprocess.run(["sips", "-Z", "1600", str(shot)], capture_output=True, check=False)
            atomic_write(out, shot.read_bytes())  # never through a symlink
            return method, out
    finally:
        server.shutdown()
        server.server_close()


def _fallback_svg(server, view, theme, w, h) -> str:
    """SVG of every STL in the served folder, with the same caps as svg_preview."""
    manifest = server.manifest()
    if not manifest["parts"]:
        raise ValueError("no STL files in the folder")
    handles = []
    try:
        for part in manifest["parts"]:
            opened = serve.open_child(server.folder, part["file"], server.dir_fd,
                                      max_bytes=svg_preview.MAX_STL_BYTES)
            if opened is None:
                raise ValueError(f"{safe_text(part['file'])}: unreadable or larger than "
                                 f"{svg_preview.MAX_STL_BYTES // (1024 * 1024)} MB for the SVG fallback")
            handles.append(opened[0])
        return svg_preview.render_svg(handles, colors=[p["color"] for p in manifest["parts"]],
                                      title=", ".join(p["name"] for p in manifest["parts"])[:80],
                                      view=view, width=w, height=h,
                                      background="#14181f" if theme == "dark" else "#f6f7f9")
    finally:
        for fh in handles:
            fh.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PNG of the local STL viewer (headless Chrome, SVG fallback).")
    ap.add_argument("folder", help="folder with .stl files")
    ap.add_argument("--out", required=True, help="output .png path")
    ap.add_argument("--view", default="iso", choices=["iso", "top", "front", "right"])
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--size", default="1400x900", help="window size WxH (default 1400x900)")
    ap.add_argument("--section", default=None, choices=["x", "y", "z"], help="cut the parts at the middle")
    ap.add_argument("--svg", action="store_true", help="skip WebGL and use the SVG orthographic fallback")
    args = ap.parse_args(argv)
    try:
        method, path = render(args.folder, args.out, view=args.view, theme=args.theme, size=args.size,
                              section=args.section, force_svg=args.svg)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"render_png: {safe_text(exc)}", file=sys.stderr)
        return 2
    if method == "webgl":
        print(f"wrote {safe_text(path)} (WebGL viewer)")
    elif method == "svg-fallback" and args.svg:
        print(f"wrote {safe_text(path)} (SVG orthographic picture, as asked)")
    elif method == "svg-fallback":
        print(f"wrote {safe_text(path)} (WebGL did not render headless: SVG orthographic fallback)")
    else:
        print(f"wrote {safe_text(path)} only: no PNG (Chrome missing or failed); open the SVG in a browser")
    return 0


if __name__ == "__main__":
    sys.exit(main())
