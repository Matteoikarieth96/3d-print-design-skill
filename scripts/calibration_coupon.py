#!/usr/bin/env python3
"""Tolerance and overhang calibration coupon for FDM printers.

build   writes <out>/calibration-coupon.stl + .json + legend: a plate with
        9 round holes and 9 square holes at per-side clearances 0.00 to 0.40 mm
        (0.05 mm steps), 2 round pegs, 1 square bar, and 5 overhang fins
        (30, 40, 45, 50, 60 degrees).
record  writes fits.json in the current folder from what you measured, so
        build.py scripts in this folder use your printer's real clearances.

Reading the notches (no text needed): each hole has V notches on the plate
edge next to it. A deep notch counts 5 steps, a shallow notch 1 step, one
step is 0.05 mm per side. No notch = 0.00. Round holes are on the front edge
(the long edge nearest the pegs), square holes on the back edge. The fins
stand at the right end; the front one is 30 degrees and they get steeper
toward the back: 30, 40, 45, 50, 60. See references/calibration.md.

Examples:
    python calibration_coupon.py build --out out --peg 6 --bed 220x220x250
    python calibration_coupon.py record --press 0.10 --snug 0.15 --sliding 0.20 \
        --free 0.30 --overhang 45 --printer "my printer" --material PETG --nozzle 0.4

Never talks to a printer: slice and print the STL yourself.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

STEP = 0.05          # clearance step per side, mm
STEPS = 9            # 0.00 .. 0.40
FIN_ANGLES = (30, 40, 45, 50, 60)
MATERIALS = ("PLA", "PETG", "TPU", "ABS", "ASA", "OTHER")
PRINTABLE_TEXT = re.compile(r"^[\w .,:()/+#-]{0,60}$")


def clearances():
    return [round(i * STEP, 2) for i in range(STEPS)]


def tally(index: int):
    """Notch pattern for a clearance index: ('deep' = 5 steps, 'shallow' = 1 step)."""
    return ["deep"] * (index // 5) + ["shallow"] * (index % 5)


def build_coupon(peg_d: float = 6.0, plate_t: float = 4.0, foot: float = 0.4):
    """Return (solid, legend dict). Imports the geometry stack lazily."""
    import cad
    from shapely.geometry import Polygon

    if not 3.0 <= peg_d <= 12.0:
        raise ValueError("peg diameter must be between 3 and 12 mm")
    clear = clearances()
    max_r = peg_d / 2 + clear[-1] + foot           # widest hole radius incl. bottom flare
    notch_deep, notch_shallow = 2.0, 1.2            # notch depths into the plate edge
    wall = 1.6                                      # material between notch tip and hole flare
    pitch = max(2 * max_r + 4.0, 9.0)               # hole spacing, also fits a 4-notch group (7 mm)
    y_round = notch_deep + wall + max_r
    y_square = y_round + 2 * max_r + 4.0
    depth = y_square + max_r + wall + notch_deep
    x0 = 4.0 + max_r
    xs = [x0 + i * pitch for i in range(STEPS)]

    fin_h, fin_t = 6.0, 2.0                          # fin height above the plate, horizontal thickness
    fin_x = xs[-1] + max_r + 4.0
    fin_reach = fin_t + fin_h * math.tan(math.radians(max(FIN_ANGLES)))
    width = fin_x + fin_reach + 3.0

    # plate outline with V notches (tally marks) on front and back edges
    outline = cad.rect(width, depth, center=False)
    notch_pitch = 2.0

    def notch(x, y_edge, kind, inward):
        w, d = (1.4, notch_deep) if kind == "deep" else (1.0, notch_shallow)
        return Polygon([(x - w / 2, y_edge - inward * 0.01), (x, y_edge + inward * d),
                        (x + w / 2, y_edge - inward * 0.01)])

    for i, x in enumerate(xs):
        marks = tally(i)
        offsets = [(k - (len(marks) - 1) / 2) * notch_pitch for k in range(len(marks))]
        for kind, off in zip(marks, offsets):
            outline = outline.difference(notch(x + off, 0.0, kind, +1))
            outline = outline.difference(notch(x + off, depth, kind, -1))
    plate = cad.chamfered_extrude(outline, plate_t, bottom=foot)

    cutters = []
    for x, c in zip(xs, clear):
        d = peg_d + 2 * c
        cutters.append(cad.translate(cad.hole(d, plate_t, plate_t, n=96, foot=foot), x=x, y=y_round))
        sq = cad.rect(d, d)
        sq_cut = cad.extrude(sq, plate_t + 2 * cad.EPS, z0=-cad.EPS)
        flare = cad.chamfered_extrude(cad.rect(d + 2 * foot + 2 * cad.EPS, d + 2 * foot + 2 * cad.EPS),
                                      foot + 0.2, top=foot + 0.1)
        cutters.append(cad.translate(cad.union(sq_cut, cad.translate(flare, z=-0.1)), x=x, y=y_square))
    plate = cad.difference(plate, *cutters)

    # overhang fins, leaning toward +X; the right face is the overhang at the fin's angle
    fins = []
    spacing = depth / len(FIN_ANGLES)
    fin_w = min(4.0, spacing - 1.5)
    for k, ang in enumerate(FIN_ANGLES):
        lean = fin_h * math.tan(math.radians(ang))
        sink = cad.EPS * math.tan(math.radians(ang))  # start EPS below the plate top so they fuse
        prof = Polygon([(-sink, -cad.EPS), (fin_t - sink, -cad.EPS), (fin_t + lean, fin_h), (lean, fin_h)])
        fin = cad.extrude(prof, fin_w)                       # profile in XY, width along Z
        fin = fin.rotate((90.0, 0.0, 0.0))                   # (x, y, z) -> (x, -z, y): profile Y -> Z
        y_c = spacing * (k + 0.5)
        fins.append(cad.translate(fin, x=fin_x, y=y_c + fin_w / 2, z=plate_t))
    plate = cad.union(plate, *fins)

    # loose pegs in front of the plate: 2 round, 1 square bar, chamfered both ends
    peg_h, bar_h = 12.0, 16.0
    y_peg = -4.0 - peg_d / 2
    round_peg = cad.chamfered_extrude(cad.circle2d(peg_d, 96), peg_h, bottom=foot, top=0.6)
    bar = cad.chamfered_extrude(cad.rect(peg_d, peg_d), bar_h, bottom=foot, top=0.6)
    pegs = [cad.translate(round_peg, x=xs[0], y=y_peg), cad.translate(round_peg, x=xs[1], y=y_peg),
            cad.translate(bar, x=xs[2], y=y_peg)]
    solid = cad.union(plate, *pegs)

    legend = {
        "peg_diameter_mm": peg_d,
        "step_mm_per_side": STEP,
        "notches": "deep notch = 5 steps, shallow notch = 1 step, no notch = 0.00",
        "round_holes_front_edge": [{"index": i, "notches": tally(i), "clearance_per_side_mm": c,
                                    "hole_mm": round(peg_d + 2 * c, 2)} for i, c in enumerate(clear)],
        "square_holes_back_edge": [{"index": i, "notches": tally(i), "clearance_per_side_mm": c,
                                    "hole_mm": round(peg_d + 2 * c, 2)} for i, c in enumerate(clear)],
        "fins_front_to_back_deg": list(FIN_ANGLES),
        "bodies": 4,
        "expected_warnings": "overhang (the 50 and 60 degree fins are meant to show where your printer "
                             "fails) and thin walls at the knife-edge tips of the steep fins",
    }
    return solid, legend


def cmd_build(args) -> int:
    import cad
    import printcheck

    project = Path.cwd()
    try:
        out_dir = cad.safe_out_dir(project, args.out)
        bed = printcheck.parse_bed(args.bed)
        solid, legend = build_coupon(peg_d=args.peg)
    except ValueError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    mesh = cad.to_trimesh(solid)
    res = printcheck.check_printable(mesh, bed=bed, layer=args.layer, nozzle=args.nozzle,
                                     overhang_deg=45, expected_bodies=4, supports=True,
                                     min_hole_d=3.0, thin_wall_samples=300)
    print(res.summary("calibration-coupon"))
    if not res.ok:
        print("printcheck failed: nothing written", file=sys.stderr)
        return 1
    params = {"PEG_D": args.peg, "STEP": STEP, "STEPS": STEPS, "FIN_ANGLES": list(FIN_ANGLES),
              "NOZZLE": args.nozzle, "LAYER": args.layer}
    stl, meta = cad.write_part(out_dir, "calibration-coupon", mesh, res, material=args.material,
                               params=params, color="#e0a030", bed=bed, extra={"legend": legend})
    print(f"wrote {stl} and {meta}")
    print("print it WITHOUT supports, 0.2 mm layers, the material you will use for real parts")
    return 0


def _clean_text(value: str, label: str) -> str:
    value = (value or "").strip()
    if not PRINTABLE_TEXT.fullmatch(value):
        raise ValueError(f"{label}: use up to 60 plain characters (letters, digits, spaces, .,:()/+#-)")
    return value


def cmd_record(args) -> int:
    import cad

    try:
        target = cad.safe_out_dir(Path.cwd(), ".") / "fits.json"
        fits = {}
        for key in ("press", "snug", "sliding", "free"):
            v = getattr(args, key)
            if v is None:
                continue
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"--{key} must be between 0 and 1 mm per side")
            fits[key] = round(v, 3)
        if not fits:
            raise ValueError("give at least one of --press --snug --sliding --free")
        order = [fits.get(k) for k in ("press", "snug", "sliding", "free") if k in fits]
        if order != sorted(order):
            print("note: clearances are usually press <= snug <= sliding <= free; double check", file=sys.stderr)
        data = {
            "printer": _clean_text(args.printer, "--printer"),
            "material": args.material.upper(),
            "nozzle_mm": args.nozzle,
            "layer_mm": args.layer,
            "measured": _dt.date.today().isoformat(),
            "clearance_per_side": fits,
            "note": "per-side clearances measured with the calibration coupon; "
                    "they already include this printer's hole shrink",
        }
        if args.overhang is not None:
            if not 20 <= args.overhang <= 75:
                raise ValueError("--overhang must be between 20 and 75 degrees")
            data["overhang_ok_deg"] = args.overhang
        if data["material"] not in MATERIALS:
            raise ValueError(f"--material must be one of {', '.join(MATERIALS)}")
    except ValueError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="FDM tolerance + overhang calibration coupon.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the coupon STL")
    b.add_argument("--out", default="out", help="output folder inside the current folder (default out)")
    b.add_argument("--peg", type=float, default=6.0, help="nominal peg size in mm (default 6)")
    b.add_argument("--bed", default="220x220x250", help="build volume, mm (default 220x220x250)")
    b.add_argument("--nozzle", type=float, default=0.4)
    b.add_argument("--layer", type=float, default=0.2)
    b.add_argument("--material", default="PLA", help="for the mass estimate only")
    r = sub.add_parser("record", help="write fits.json from your measurements")
    for key, helptext in (("press", "tightest round hole the peg enters fully with firm hand pressure"),
                          ("snug", "first round hole where the peg turns by hand with no visible play"),
                          ("sliding", "first square hole the bar slides through with a light push"),
                          ("free", "first hole where the peg drops through under its own weight")):
        r.add_argument(f"--{key}", type=float, default=None, help=f"per-side mm: {helptext}")
    r.add_argument("--overhang", type=float, default=None, help="steepest fin with a clean underside, degrees")
    r.add_argument("--printer", default="", help="printer name, for your records")
    r.add_argument("--material", default="PLA")
    r.add_argument("--nozzle", type=float, default=0.4)
    r.add_argument("--layer", type=float, default=0.2)
    args = ap.parse_args(argv)
    return cmd_build(args) if args.cmd == "build" else cmd_record(args)


if __name__ == "__main__":
    sys.exit(main())
