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
OVERHANG_LIMIT = 45              # degrees from vertical without support
SUPPORTS_ALLOWED = False         # flat part, nothing to support
EXPECTED_BODIES = 1              # each colour part is one solid
ASSEMBLY = True                  # base and star are the two colours of ONE coaster, printed in place
ASSEMBLY_BODIES = 1              # joined, they make one solid coaster

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
        profile = printers.get(g.get("PRINTER"))
    except ValueError as exc:
        print(f"refusing: {safe_text(exc)}", file=sys.stderr)
        return 2

    parts = build_part()
    if not isinstance(parts, dict):
        parts = {"": parts}
    together = bool(g.get("ASSEMBLY", False)) and len(parts) > 1
    colours = {sfx: str(_per_part(g.get("COLOUR_NAME"), sfx) or "") for sfx in parts}
    n_colours = len(set(colours.values())) if len(parts) > 1 else 1
    try:
        bed = printers.bed_for(profile, n_colours, g.get("PRINTER_BED"))
    except ValueError as exc:
        print(f"refusing: {safe_text(exc)}", file=sys.stderr)
        return 2
    results = []
    for suffix, solid in parts.items():
        try:
            part_name = name if not suffix else cad.validate_name(f"{name}-{suffix}")
        except ValueError as exc:
            print(f"refusing: {safe_text(exc)}", file=sys.stderr)
            return 2
        mesh = cad.to_trimesh(solid)
        res = printcheck.check_printable(
            mesh, bed=bed, layer=g["LAYER"], nozzle=g["NOZZLE"],
            overhang_deg=g["OVERHANG_LIMIT"], supports=g["SUPPORTS_ALLOWED"],
            expected_bodies=_per_part(g["EXPECTED_BODIES"], suffix),
            thin_wall_samples=args.thin_walls,
            probes_inside=_per_part(g.get("PROBES_INSIDE", ()), suffix) or (),
            probes_outside=_per_part(g.get("PROBES_OUTSIDE", ()), suffix) or (),
            standalone=not together,
        )
        print(res.summary(part_name))
        results.append((part_name, suffix, mesh, res))

    joined = None
    if together:
        joined = assembly.check_assembly(
            parts, bed=bed, layer=g["LAYER"], nozzle=g["NOZZLE"], overhang_deg=g["OVERHANG_LIMIT"],
            supports=g["SUPPORTS_ALLOWED"], expected_bodies=g.get("ASSEMBLY_BODIES", 1),
            nozzles=profile["nozzles"])
        print(joined.summary(f"{name} (all {len(parts)} colour parts joined)"))
    two_nozzle_bed = not g.get("PRINTER_BED") and n_colours >= 2 and bool(profile.get("bed_two_nozzles"))
    notes = printers.notes(profile, g["MATERIAL"], n_colours, two_nozzle_bed)
    for note in notes:
        print(f"note ({profile['label']}): {note}")

    failed = [r[0] for r in results if not r[3].ok] + ([name + " (joined)"] if joined and not joined.ok else [])
    if failed:
        print(f"\nprintcheck failed for {', '.join(failed)}: nothing written. "
              "Fix the parameters or the geometry and run again.", file=sys.stderr)
        return 1
    if args.check:
        print("\ncheck only: nothing written")
        return 0
    params = cad.param_snapshot(g)
    params["FITS"] = FITS
    extra = {"printer": profile["name"], "assembly": together, "printer_notes": notes}
    if joined is not None:
        extra["assembly_check"] = joined.to_dict()
    handoff = []
    for part_name, suffix, mesh, res in results:
        hex_colour = _per_part(g.get("COLOR"), suffix)
        try:
            stl, meta = cad.write_part(out_dir, part_name, mesh, res, material=g["MATERIAL"], params=params,
                                       color=hex_colour, bed=bed, extra=dict(extra, colour=colours[suffix]))
        except (ValueError, OSError) as exc:
            print(f"refusing: {safe_text(exc)}", file=sys.stderr)
            return 2
        print(f"wrote {stl.relative_to(PROJECT_DIR)} and {meta.relative_to(PROJECT_DIR)}")
        z0, z1 = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
        handoff.append({"stl": stl.name, "colour": colours[suffix], "colour_hex": hex_colour, "z": (z0, z1),
                        "layers": int(round((z1 - z0) / g["LAYER"])), "volume_mm3": float(mesh.volume)})
    if profile.get("handoff"):
        job = printers.x2d_job(name, handoff, assembly=together, material=g["MATERIAL"], layer=g["LAYER"],
                               nozzle=g["NOZZLE"], supports=g["SUPPORTS_ALLOWED"], profile=profile,
                               printer_notes=notes)
        try:
            path = printers.write_handoff(out_dir, job, profile["handoff_file"])
        except (ValueError, OSError) as exc:
            print(f"refusing: {safe_text(exc)}", file=sys.stderr)
            return 2
        print(f"wrote {path.relative_to(PROJECT_DIR)}: draft job for the {profile['handoff']} skill "
              "(template and filament numbers are filled there)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
