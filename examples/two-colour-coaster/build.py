#!/usr/bin/env python3
"""Parametric build script for one FDM part (3d-print-design skill template).

Copy this file into a fresh, empty project folder (never inside a cloned
repository or a folder of downloaded files), then:
    python -P build.py            -> runs printcheck, writes out/<NAME>.stl + out/<NAME>.json
    python -P build.py --check    -> runs printcheck only, writes nothing
Set PRINT3D_SKILL_DIR to the skill folder unless it is installed in
~/.claude/skills/3d-print-design.

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
NAME = "coaster"                 # output file stem: a-z, 0-9 and dashes only
MATERIAL = "PLA"                 # one material for both colours; a cold drink, indoors
COLOR = {"base": "#161616", "star": "#fff144"}        # preview colours, close to the filaments
COLOUR_NAME = {"base": "black", "star": "yellow"}     # filament colours for the x2d-print hand-off

PRINTER = "bambu-x2d"            # Bambu Lab X2D: two nozzles, AMS on the left one
PRINTER_BED = None               # None = what both X2D nozzles reach (two colours)
NOZZLE = 0.4                     # the X2D's standard nozzle
LAYER = 0.2                      # 0.20mm Standard process; every height below is a multiple
OVERHANG_LIMIT = FITS.get("overhang_ok_deg", 45)  # degrees from vertical without support (coupon, else 45)
SUPPORTS_ALLOWED = False         # flat part, nothing to support
EXPECTED_BODIES = 1              # each colour part is one solid
ASSEMBLY = True                  # base and star are the two colours of ONE coaster, printed in place
ASSEMBLY_BODIES = 1              # joined, they make one solid coaster
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

DIAM = 90.0                      # coaster diameter: a mug base is 70 to 80 mm (fictional)
THICK = 4.0                      # 20 layers: stiff, and the star pocket leaves 3.4 mm of base under it
FOOT_CHAMFER = 0.4               # bottom edge chamfer that hides elephant foot (0.3 to 0.5)
TOP_CHAMFER = 0.6                # cosmetic top edge chamfer, 3 layers
STAR_POINTS = 5                  # a classic five-point star
STAR_R_OUT = 30.0                # tip radius: well inside the 45 mm disc, 15 mm of black rim
STAR_R_IN = 12.5                 # notch radius: notches wider than 2 x nozzle so thin walls pass
INLAY_T = 0.6                    # star depth: 3 layers, enough for yellow to cover black

PROBES_INSIDE = {"base": [(0.0, 0.0, THICK / 2)],              # base is solid under the star
                 "star": [(0.0, 0.0, THICK - INLAY_T / 2)]}    # star fills its pocket
PROBES_OUTSIDE = {"base": [(0.0, 0.0, THICK - INLAY_T / 2)]}   # the pocket is empty in the base
# ====================== PARAMETERS END ======================


# ===================== GEOMETRY START =====================
def _star():
    import math
    pts = []
    for k in range(2 * STAR_POINTS):
        r = STAR_R_OUT if k % 2 == 0 else STAR_R_IN
        a = math.pi / 2 + k * math.pi / STAR_POINTS
        pts.append((r * math.cos(a), r * math.sin(a)))
    return cad.Polygon(pts)


def build_part():
    """Base with a star-shaped pocket on top, and the star that fills it.

    The star is cut out of the base with the very same outline, so the two
    parts touch without sharing volume (the assembly overlap check).
    """
    disc = cad.chamfered_extrude(cad.circle2d(DIAM), THICK, bottom=FOOT_CHAMFER, top=TOP_CHAMFER)
    star = cad.extrude(_star(), INLAY_T, z0=THICK - INLAY_T)
    return {"base": cad.difference(disc, star), "star": star}
# ====================== GEOMETRY END ======================


# ============ HARNESS: DO NOT EDIT BELOW THIS LINE ============
def main(argv=None) -> int:
    """Name check, printcheck, estimate, export and hand-off: the skill's scripts/harness.py."""
    return harness.run(globals(), argv, Path(__file__))


if __name__ == "__main__":
    sys.exit(main())
