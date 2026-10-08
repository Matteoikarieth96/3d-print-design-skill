#!/usr/bin/env python3
"""Orthographic, flat-shaded SVG picture of one or more STL files (stdlib only).

The fallback when WebGL is not available (offline, headless without GPU):
    python svg_preview.py out/cable-clip.stl --out docs/cable-clip.svg
    python svg_preview.py out/a.stl out/b.stl --colors "#4f8cff,#e0a030" --view top

Painter's algorithm with back-face culling: good enough for a README picture
or a quick look, not a substitute for the interactive viewer. STL files are
read as numbers only; the only text placed in the SVG is the escaped title.
"""
from __future__ import annotations

import argparse
import html
import math
import os
import re
import struct
import sys
from array import array
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safeio import atomic_write, safe_text  # noqa: E402

# Pure-Python fallback renderer: keep it bounded. Both caps are enforced before
# or while reading, never after loading a whole file.
MAX_TRIANGLES = 500_000
MAX_STL_BYTES = 128 * 1024 * 1024
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
VIEWS = {"iso": (-55.0, 28.0), "front": (-90.0, 0.0), "top": (-90.0, 89.9), "right": (0.0, 0.0)}
FLOAT = rb"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
VERTEX_RE = re.compile(rb"vertex\s+(" + FLOAT + rb")\s+(" + FLOAT + rb")\s+(" + FLOAT + rb")")


def _size_of(fh) -> int:
    try:
        return os.fstat(fh.fileno()).st_size
    except (AttributeError, OSError, ValueError):
        pos = fh.tell()
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(pos)
        return size


def read_stl(source, max_triangles: int = None, max_bytes: int = None) -> array:
    """Read an STL (path or binary file object) into a flat array of 9 floats per triangle.

    The byte cap is checked from the file size before anything is read; the
    triangle cap is checked from the binary header, or counted while an ASCII
    file is parsed line by line, and reading stops as soon as it is exceeded.
    """
    max_triangles = MAX_TRIANGLES if max_triangles is None else max_triangles
    max_bytes = MAX_STL_BYTES if max_bytes is None else max_bytes
    if isinstance(source, (str, os.PathLike)):
        if os.path.getsize(source) > max_bytes:
            raise ValueError(f"file larger than {max_bytes // (1024 * 1024)} MB, too big for the SVG preview")
        with open(source, "rb") as fh:
            return read_stl(fh, max_triangles, max_bytes)
    fh = source
    size = _size_of(fh)
    if size > max_bytes:
        raise ValueError(f"file larger than {max_bytes // (1024 * 1024)} MB, too big for the SVG preview")
    out = array("d")
    head = fh.read(84)
    if len(head) == 84:
        (n,) = struct.unpack_from("<I", head, 80)
        if 84 + 50 * n == size:
            if n > max_triangles:
                raise ValueError("too many triangles for the SVG preview")
            rec = struct.Struct("<12fH")
            for _ in range(0, n, 4096):
                chunk = fh.read(50 * min(4096, n - len(out) // 9))
                for v in rec.iter_unpack(chunk):
                    out.extend(v[3:12])
            return out
    # ASCII: stream short lines, count vertices as we go
    fh.seek(0)
    limit = 3 * max_triangles
    count = 0
    while True:
        line = fh.readline(1024)
        if not line:
            break
        m = VERTEX_RE.search(line)
        if m:
            count += 1
            if count > limit:
                raise ValueError("too many triangles for the SVG preview")
            out.extend(float(g) for g in m.groups())
    del out[len(out) - len(out) % 9:]
    return out


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    length = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / length, a[1] / length, a[2] / length)


def _rgb(hexcolor: str):
    return tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))


def render_svg(paths, colors: Sequence[str] = ("#4f8cff",), title: str = "", view: str = "iso",
               width: int = 1200, height: int = 800, background: str = "#f6f7f9", color: str = None) -> str:
    """Return SVG text for the given STL path(s) or open binary file object(s)."""
    if isinstance(paths, (str, os.PathLike)) or hasattr(paths, "read"):
        paths = [paths]
    if color:
        colors = [color]
    colors = [c if HEX.fullmatch(c or "") else "#4f8cff" for c in colors] or ["#4f8cff"]
    if not HEX.fullmatch(background):
        background = "#f6f7f9"
    az, el = VIEWS.get(view, VIEWS["iso"])
    az, el = math.radians(az), math.radians(el)
    cam = (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))  # toward the viewer
    right = (-math.sin(az), math.cos(az), 0.0)
    up = _cross(cam, right)
    light = _norm((cam[0] + 0.35, cam[1] - 0.25, cam[2] + 0.6))

    polys = []
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    x0 = y0 = math.inf
    x1 = y1 = -math.inf
    total = 0
    for idx, src in enumerate(paths):
        base = _rgb(colors[idx % len(colors)])
        flat = read_stl(src, max_triangles=MAX_TRIANGLES - total)  # the cap covers all files together
        total += len(flat) // 9
        for t in range(0, len(flat), 9):
            tri = ((flat[t], flat[t + 1], flat[t + 2]), (flat[t + 3], flat[t + 4], flat[t + 5]),
                   (flat[t + 6], flat[t + 7], flat[t + 8]))
            for v in tri:
                for k in range(3):
                    lo[k] = min(lo[k], v[k])
                    hi[k] = max(hi[k], v[k])
            n = _cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0]))
            if _dot(n, n) < 1e-18:
                continue
            n = _norm(n)
            if _dot(n, cam) <= 0:
                continue  # facing away
            shade = 0.38 + 0.62 * max(0.0, _dot(n, light))
            rgb = "#%02x%02x%02x" % tuple(min(255, int(c * shade)) for c in base)
            pts = [(_dot(v, right), -_dot(v, up)) for v in tri]
            for x, y in pts:
                x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            depth = sum(_dot(v, cam) for v in tri) / 3.0
            polys.append((depth, " ".join(f"{x:.2f},{y:.2f}" for x, y in pts), rgb))
    if not polys:
        raise ValueError("nothing to draw")
    polys.sort(key=lambda t: t[0])
    span = max(x1 - x0, y1 - y0, 1e-6)
    pad = 0.08 * span
    caption_h = 0.07 * span
    vb = (x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad + caption_h)
    stroke = 0.0015 * span
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="{vb[0]:.3f} {vb[1]:.3f} {vb[2]:.3f} {vb[3]:.3f}" preserveAspectRatio="xMidYMid meet">',
        f'<rect x="{vb[0]:.3f}" y="{vb[1]:.3f}" width="{vb[2]:.3f}" height="{vb[3]:.3f}" fill="{background}"/>',
        f'<g stroke-linejoin="round" stroke-width="{stroke:.4f}">',
    ]
    for _, coords, c in polys:
        out.append(f'<polygon points="{coords}" fill="{c}" stroke="{c}"/>')
    out.append("</g>")
    size = f"{hi[0] - lo[0]:.1f} x {hi[1] - lo[1]:.1f} x {hi[2] - lo[2]:.1f} mm"
    label = f"{title}  ({size}, {view} view)" if title else f"{size}, {view} view"
    out.append(f'<text x="{vb[0] + pad:.3f}" y="{vb[1] + vb[3] - pad * 0.4:.3f}" '
               f'font-family="Helvetica, Arial, sans-serif" font-size="{caption_h * 0.55:.3f}" '
               f'fill="#3a4250">{html.escape(label, quote=True)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Flat-shaded SVG picture of STL files (no WebGL needed).")
    ap.add_argument("stl", nargs="+", help=".stl file(s)")
    ap.add_argument("--out", required=True, help="output .svg path")
    ap.add_argument("--colors", default="#4f8cff", help="comma separated #rrggbb, one per file")
    ap.add_argument("--view", default="iso", choices=sorted(VIEWS))
    ap.add_argument("--title", default="")
    args = ap.parse_args(argv)
    try:
        for p in args.stl:
            if not p.lower().endswith(".stl") or not Path(p).is_file():
                raise ValueError(f"not an .stl file: {safe_text(p)}")
        if not args.out.lower().endswith(".svg"):
            raise ValueError("--out must end with .svg")
        svg = render_svg(args.stl, colors=args.colors.split(","), title=args.title, view=args.view)
        atomic_write(args.out, svg)  # never through a symlink
    except (ValueError, OSError) as exc:
        print(f"svg_preview: {safe_text(exc)}", file=sys.stderr)
        return 2
    print(f"wrote {safe_text(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
