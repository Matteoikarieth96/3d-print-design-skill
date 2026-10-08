#!/usr/bin/env python3
"""Desk-edge cable clip (fictional example for the 3d-print-design skill).

A plate screwed under a desk edge with two countersunk screws, carrying a
snap-in channel for a cable bundle. Built from templates/build.py: only the
PARAMETERS and GEOMETRY blocks differ from the template.


Copy this file into your project folder, then:
    python build.py            -> runs printcheck, writes out/<NAME>.stl + out/<NAME>.json
    python build.py --check    -> runs printcheck only, writes nothing

Three zones:
  PARAMETERS  every number lives here, in millimetres, each with a comment
              saying why it has that value. Iterate by editing only this block.
  GEOMETRY    build_part() turns the parameters into a solid. It uses
              parameter names, never bare numbers (0, 1, 2 and halves are fine).
  HARNESS     below the DO NOT EDIT line: name check, printcheck, export.

Units: mm. Z is up. The part must sit on z = 0 in its print orientation.
This script never contacts a printer; slicing and printing are your steps.
"""
import argparse
import os
import sys
from pathlib import Path


def _skill_scripts() -> Path:
    """Find the skill's scripts/ folder (cad.py + printcheck.py)."""
    here = Path(__file__).resolve().parent
    candidates = []
    env = os.environ.get("PRINT3D_SKILL_DIR")
    if env:
        candidates.append(Path(env).expanduser() / "scripts")
    candidates += [here.parent / "scripts", here.parent.parent / "scripts",
                   Path.home() / ".claude" / "skills" / "3d-print-design" / "scripts"]
    for c in candidates:
        if (c / "cad.py").is_file() and (c / "printcheck.py").is_file():
            return c.resolve()
    sys.exit("cannot find the 3d-print-design scripts: set PRINT3D_SKILL_DIR to the skill folder")


sys.path.insert(0, str(_skill_scripts()))
import cad  # noqa: E402
import printcheck  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
FITS = cad.load_fits(PROJECT_DIR)  # per-side clearances: fits.json if present, else defaults

# ===================== PARAMETERS START (edit only this block) =====================
NAME = "cable-clip"              # output file stem: a-z, 0-9 and dashes only
MATERIAL = "PETG"                # flexes for the snap without cracking, fine under a desk
COLOR = "#2bb673"                # preview colour in the viewer only

PRINTER_BED = (220, 220, 250)    # X, Y, Z build volume of the target printer (intake)
NOZZLE = 0.4                     # nozzle diameter; minimum wall = 2 x NOZZLE
LAYER = 0.2                      # layer height; flat feature heights are multiples of it
OVERHANG_LIMIT = 45              # degrees from vertical this printer manages without support
SUPPORTS_ALLOWED = False         # the clip must print with no supports at all
EXPECTED_BODIES = 1              # one solid part

CABLE_D = 7.0                    # cable bundle diameter measured with calipers (2 cables)
CABLE_CLEAR = 0.5                # radial room so the bundle is held, not pinched
GAP = 5.0                        # snap opening: about 70 % of CABLE_D so the bundle clicks in
LIP_T = 2.0                      # vertical lip thickness above the opening: 10 layers, flexes in PETG
WALL = 2.4                       # channel side wall: 6 extrusion widths, stiff but not brittle
LEAD = 1.0                       # 45 degree lead-in at the opening so the cable finds the gap
TOP_CH = 1.0                     # cosmetic 45 degree chamfer on the channel top corners
SINK = 1.0                       # channel floor sits this far into the plate: no knife-edge contact

CLIP_W = 12.0                    # clip width along the cable (Y): 3 x the screw head radius region
PLATE_T = 4.0                    # plate thickness: 20 layers, room for the countersink
CORNER_R = 3.0                   # plate corner radius in plan view
FOOT_CHAMFER = 0.4               # bottom edge chamfer that hides elephant foot (0.3 to 0.5)

SCREW_D = 3.5                    # 3.5 mm wood screw shank (measured)
HEAD_D = 7.0                     # flat head diameter (measured)
HEAD_ANGLE = 90                  # included countersink angle of the head (90 for ISO)
SCREW_GAP = 1.5                  # space between the channel wall and the screw head
EDGE = 3.0                       # plate material beyond the screw head
CLEAR = FITS["free"]             # per-side clearance: shank slides in, no force

R_CAV = CABLE_D / 2 + CABLE_CLEAR                          # cavity radius
HALF_OUT = R_CAV + WALL                                    # half width of the channel body
SCREW_X = HALF_OUT + SCREW_GAP + HEAD_D / 2 + CLEAR        # screw axis distance from centre
PLATE_L = 2 * (SCREW_X + HEAD_D / 2 + CLEAR + EDGE)        # plate length along X
Z_C = PLATE_T + R_CAV - SINK                               # cavity centre height
Z_TOP = LAYER * round((Z_C + R_CAV * 2 ** 0.5 - GAP / 2 + LIP_T) / LAYER)  # top, on a layer

PROBES_INSIDE = [(HALF_OUT - WALL / 2, 0.0, Z_C)]          # channel wall must be solid
PROBES_OUTSIDE = [(0.0, 0.0, Z_C), (SCREW_X, 0.0, PLATE_T / 2), (-SCREW_X, 0.0, PLATE_T / 2)]
# ====================== PARAMETERS END ======================


# ===================== GEOMETRY START =====================
def build_part():
    """Plate on the bed, channel standing up, cable running along Y."""
    from shapely.geometry import Polygon

    plate = cad.chamfered_extrude(cad.rounded_rect(PLATE_L, CLIP_W, CORNER_R), PLATE_T, bottom=FOOT_CHAMFER)

    # channel profile drawn in the XZ plane (as 2D x, y), then stood up and extruded along Y
    body = Polygon([(-HALF_OUT, PLATE_T / 2), (HALF_OUT, PLATE_T / 2), (HALF_OUT, Z_TOP - TOP_CH),
                    (HALF_OUT - TOP_CH, Z_TOP), (-HALF_OUT + TOP_CH, Z_TOP), (-HALF_OUT, Z_TOP - TOP_CH)])
    cavity = cad.translate2d(cad.teardrop2d(2 * R_CAV, flat_top=False), y=Z_C)  # 45 degree roof
    slot = cad.box2d(-GAP / 2, Z_C, GAP / 2, Z_TOP + cad.EPS)                   # snap opening
    lead = Polygon([(-GAP / 2 - LEAD, Z_TOP + cad.EPS), (-GAP / 2, Z_TOP - LEAD),
                    (GAP / 2, Z_TOP - LEAD), (GAP / 2 + LEAD, Z_TOP + cad.EPS)])
    opening = cavity.union(slot).union(lead)
    channel = cad.stand_up(cad.extrude(body, CLIP_W))
    cut = cad.stand_up(cad.extrude(opening, CLIP_W + 2 * cad.EPS, z0=-cad.EPS))

    cutter = cad.countersunk_cutter(SCREW_D + 2 * CLEAR, HEAD_D + 2 * CLEAR, PLATE_T, angle=HEAD_ANGLE)
    screws = [cad.translate(cutter, x=sx * SCREW_X) for sx in (-1, 1)]
    return cad.difference(cad.union(plate, channel), cut, *screws)
# ====================== GEOMETRY END ======================


# ============ HARNESS: DO NOT EDIT BELOW THIS LINE ============
def _per_part(value, suffix):
    return value.get(suffix, value.get("", None)) if isinstance(value, dict) else value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=f"Build {NAME} and check it before export.")
    ap.add_argument("--out", default="out", help="output folder inside the project folder (default out)")
    ap.add_argument("--check", action="store_true", help="run printcheck only, write nothing")
    ap.add_argument("--thin-walls", type=int, default=400, metavar="N",
                    help="surface samples for the thin wall check (0 to skip)")
    args = ap.parse_args(argv)
    g = globals()
    try:
        name = cad.validate_name(g["NAME"])
        out_dir = cad.safe_out_dir(PROJECT_DIR, args.out)
    except ValueError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return 2

    parts = build_part()
    if not isinstance(parts, dict):
        parts = {"": parts}
    results = []
    for suffix, solid in parts.items():
        try:
            part_name = name if not suffix else cad.validate_name(f"{name}-{suffix}")
        except ValueError as exc:
            print(f"refusing: {exc}", file=sys.stderr)
            return 2
        mesh = cad.to_trimesh(solid)
        res = printcheck.check_printable(
            mesh, bed=g["PRINTER_BED"], layer=g["LAYER"], nozzle=g["NOZZLE"],
            overhang_deg=g["OVERHANG_LIMIT"], supports=g["SUPPORTS_ALLOWED"],
            expected_bodies=_per_part(g["EXPECTED_BODIES"], suffix),
            thin_wall_samples=args.thin_walls,
            probes_inside=_per_part(g.get("PROBES_INSIDE", ()), suffix) or (),
            probes_outside=_per_part(g.get("PROBES_OUTSIDE", ()), suffix) or (),
        )
        print(res.summary(part_name))
        results.append((part_name, suffix, mesh, res))

    failed = [r for r in results if not r[3].ok]
    if failed:
        print(f"\nprintcheck failed for {', '.join(r[0] for r in failed)}: nothing written. "
              "Fix the parameters or the geometry and run again.", file=sys.stderr)
        return 1
    if args.check:
        print("\ncheck only: nothing written")
        return 0
    params = cad.param_snapshot(g)
    params["FITS"] = FITS
    for part_name, suffix, mesh, res in results:
        stl, meta = cad.write_part(out_dir, part_name, mesh, res, material=g["MATERIAL"], params=params,
                                   color=_per_part(g.get("COLOR"), suffix), bed=g["PRINTER_BED"])
        print(f"wrote {stl.relative_to(PROJECT_DIR)} and {meta.relative_to(PROJECT_DIR)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
