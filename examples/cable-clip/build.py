#!/usr/bin/env python3
"""Desk-edge cable clip (fictional example for the 3d-print-design skill).

A plate screwed under a desk edge with two countersunk screws, carrying a
snap-in channel for a cable bundle. Built from templates/build.py: only the
PARAMETERS and GEOMETRY blocks differ from the template.

Run it from this folder with the skill named explicitly (build scripts
never search folders around the project for code):
    PRINT3D_SKILL_DIR="$(cd ../.. && pwd)" ../../.venv/bin/python -P build.py
    (add --check to run printcheck only and write nothing)

Three zones:
  PARAMETERS  every number lives here, in millimetres, each with a comment
              saying why it has that value. Iterate by editing only this block.
  GEOMETRY    build_part() turns the parameters into a solid. It uses
              parameter names, never bare numbers (0, 1, 2 and halves are fine).
  HARNESS     below the DO NOT EDIT line: name check, printcheck, export.

Units: mm. Z is up. The part must sit on z = 0 in its print orientation.
This script never contacts a printer; slicing and printing are your steps.
"""
import os
import sys

# Never import code from the project folder. Python puts this script's folder
# first on sys.path, so a planted argparse.py, pathlib.py or cad.py next to
# build.py would run. os and sys are already loaded by the interpreter, so this
# runs before anything that could be shadowed. (`python -P build.py` does the
# same; this keeps plain `python build.py` safe too.)
if not getattr(sys.flags, "safe_path", False):
    _HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:] = [p for p in sys.path if os.path.realpath(p or os.getcwd()) != _HERE]

import argparse  # noqa: E402
from pathlib import Path  # noqa: E402


def _skill_scripts() -> Path:
    """Find the skill's scripts/ folder (cad.py + printcheck.py).

    Only two places are trusted: $PRINT3D_SKILL_DIR/scripts and the installed
    skill in ~/.claude/skills/3d-print-design/scripts. Folders around the
    project are never searched, so a repository or download folder that
    happens to contain a scripts/cad.py cannot inject code.
    """
    candidates = []
    env = os.environ.get("PRINT3D_SKILL_DIR")
    if env:
        candidates.append(Path(env).expanduser().resolve() / "scripts")
    candidates.append(Path.home() / ".claude" / "skills" / "3d-print-design" / "scripts")
    for c in candidates:
        if (c / "cad.py").is_file() and (c / "printcheck.py").is_file():
            return c.resolve()
    sys.exit("cannot find the 3d-print-design scripts: set PRINT3D_SKILL_DIR to the skill folder")


sys.path.insert(0, str(_skill_scripts()))
import assembly  # noqa: E402
import cad  # noqa: E402
import harness  # noqa: E402
import printcheck  # noqa: E402
import printers  # noqa: E402
from safeio import safe_text  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent
FITS = cad.load_fits(PROJECT_DIR)  # per-side clearances: fits.json if present, else defaults

# ===================== PARAMETERS START (edit only this block) =====================
NAME = "cable-clip"              # output file stem: a-z, 0-9 and dashes only
MATERIAL = "PETG"                # flexes for the snap without cracking, fine under a desk
COLOR = "#2bb673"                # preview colour in the viewer only

PRINTER_BED = (220, 220, 250)    # X, Y, Z build volume of the target printer (intake)
NOZZLE = 0.4                     # nozzle diameter; minimum wall = 2 x NOZZLE
LAYER = 0.2                      # layer height; flat feature heights are multiples of it
OVERHANG_LIMIT = FITS.get("overhang_ok_deg", 45)  # degrees from vertical without support (coupon, else 45)
SUPPORTS_ALLOWED = False         # the clip must print with no supports at all
EXPECTED_BODIES = 1              # one solid part
QUANTITY = 1                     # copies to print (multiplies filament and time in the estimate)
FIRST_PRINT = True               # from intake: True if the person has never printed (x2d-print gives the full guide)

# Versions to compare before printing (filament and time). The base is "standard";
# vary(standard, name=value) sets a parameter per version. Geometry can vary too,
# e.g. PLATE_T = cad.vary(4.0, light=3.0). Compare with: build.py --variants
VARIANTS = {                     # name: what changes, in words the person understands
    "light": "2 walls, 10% infill: fastest, least filament; for looks or light use",
    "strong": "4 walls, 40% infill: slower, more filament; for loads, screws and clips",
}
STANDARD_ABOUT = "3 walls, 15% infill: the everyday choice for a functional part"
WALLS = cad.vary(3, light=2, strong=4)        # wall loops: the outer shell gives most of the strength
INFILL = cad.vary(15, light=10, strong=40)    # infill %: the pattern inside; more = heavier and slower
TOP_LAYERS = 5                   # solid layers on top (Bambu 0.20mm Standard)
BOTTOM_LAYERS = 3                # solid layers at the bottom (Bambu 0.20mm Standard)

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
def main(argv=None) -> int:
    """Name check, printcheck, estimate, export and hand-off: the skill's scripts/harness.py."""
    return harness.run(globals(), argv, Path(__file__))


if __name__ == "__main__":
    sys.exit(main())
