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
import re
import struct
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

MAX_TRIANGLES = 2_000_000
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
VIEWS = {"iso": (-55.0, 28.0), "front": (-90.0, 0.0), "top": (-90.0, 89.9), "right": (0.0, 0.0)}
FLOAT = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
VERTEX_RE = re.compile(rf"vertex\s+({FLOAT})\s+({FLOAT})\s+({FLOAT})")

Tri = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


def read_stl(path) -> List[Tri]:
    data = Path(path).read_bytes()
    if len(data) >= 84:
        (n,) = struct.unpack_from("<I", data, 80)
        if 84 + 50 * n == len(data):
            if n > MAX_TRIANGLES:
                raise ValueError("too many triangles for the SVG preview")
            tris = []
            for i in range(n):
                v = struct.unpack_from("<12f", data, 84 + 50 * i)
                tris.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
            return tris
    text = data.decode("ascii", errors="ignore")
    pts = [tuple(float(g) for g in m.groups()) for m in VERTEX_RE.finditer(text)]
    if len(pts) // 3 > MAX_TRIANGLES:
        raise ValueError("too many triangles for the SVG preview")
    return [(pts[i], pts[i + 1], pts[i + 2]) for i in range(0, len(pts) - 2, 3)]


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
    """Return SVG text for the given STL path(s)."""
    if isinstance(paths, (str, Path)):
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
    for idx, p in enumerate(paths):
        base = _rgb(colors[idx % len(colors)])
        for tri in read_stl(p):
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
            rgb = tuple(min(255, int(c * shade)) for c in base)
            pts = [(_dot(v, right), -_dot(v, up)) for v in tri]
            depth = sum(_dot(v, cam) for v in tri) / 3.0
            polys.append((depth, pts, rgb))
    if not polys:
        raise ValueError("nothing to draw")
    polys.sort(key=lambda t: t[0])
    xs = [x for _, pts, _ in polys for x, _ in pts]
    ys = [y for _, pts, _ in polys for _, y in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
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
    for _, pts, rgb in polys:
        c = "#%02x%02x%02x" % rgb
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
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
                raise ValueError(f"not an .stl file: {p}")
        if not args.out.lower().endswith(".svg"):
            raise ValueError("--out must end with .svg")
        svg = render_svg(args.stl, colors=args.colors.split(","), title=args.title, view=args.view)
    except (ValueError, OSError) as exc:
        print(f"svg_preview: {exc}", file=sys.stderr)
        return 2
    Path(args.out).write_text(svg, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
