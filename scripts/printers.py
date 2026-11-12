"""printers: printer profiles and the hand-off to a printer skill.

A profile gives the build volume and the facts the design checks need. A
profile with a `handoff` also gets a draft job file next to the STLs, so the
printer skill that comes next (today only x2d-print, for the Bambu Lab X2D)
starts from what the design already knows: which STL is which colour, how
many layers each colour spans, the material, the layer height.

The two skills stay separate. This module only writes a JSON file in out/;
it never runs the other skill, never opens a slicer and never contacts a
printer. Numbers for the X2D were read from Bambu Studio 2.9's system
profile "Bambu Lab X2D 0.4 nozzle" (printable_area, printable_height,
extruder_printable_area, extruder_printable_height, extruder_type). The
printer skill checks them again against the person's own Bambu Studio.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from safeio import atomic_write

PROFILES: Dict[str, dict] = {
    "generic": {
        "label": "generic FDM printer",
        "bed": (220.0, 220.0, 250.0),
        "nozzle": 0.4,
        "layer": 0.2,
        "nozzles": 1,
        "handoff": None,
    },
    "bambu-x2d": {
        "label": "Bambu Lab X2D",
        # whole plate, left nozzle (direct drive, fed by the AMS)
        "bed": (256.0, 256.0, 261.0),
        # what both nozzles reach: the right nozzle starts at x = 20.5 and stops at 256 mm high
        "bed_two_nozzles": (235.5, 256.0, 256.0),
        "nozzle": 0.4,
        "layer": 0.2,
        "nozzles": 2,
        "plate": "Textured PEI Plate",
        "process": "0.20mm Standard @BBL X2D",
        "handoff": "x2d-print",
        "handoff_file": "x2d-job.json",
        "right_nozzle_refuses": ("TPU",),
    },
}

# A colour part thinner than this many layers may let the colour under it show through.
MIN_COLOUR_LAYERS = 3


def get(name: Optional[str]) -> dict:
    """Return a copy of the profile called `name` ("generic" when empty)."""
    key = (name or "generic").strip().lower()
    if key not in PROFILES:
        raise ValueError(f"unknown printer profile {key!r}: use one of {', '.join(sorted(PROFILES))}")
    prof = dict(PROFILES[key])
    prof["name"] = key
    return prof


def bed_for(profile: dict, n_colours: int, override: Optional[Sequence[float]] = None) -> tuple:
    """Build volume to check against.

    An explicit override (the old PRINTER_BED tuple) always wins. With two or
    more colours on a two-nozzle printer, the volume both nozzles reach is
    used, because the printer skill may put a colour on either nozzle.
    """
    if override:
        bed = tuple(float(v) for v in override)
        if len(bed) != 3:
            raise ValueError("PRINTER_BED must have 3 values (x, y, z) or be None")
        return bed
    if n_colours >= 2 and profile.get("bed_two_nozzles"):
        return tuple(profile["bed_two_nozzles"])
    return tuple(profile["bed"])


def notes(profile: dict, material: str, n_colours: int, used_two_nozzle_bed: bool) -> List[str]:
    """Printer-specific remarks for the build log, the print sheet and the hand-off."""
    out = []
    if profile["name"] != "bambu-x2d":
        return out
    mat = (material or "").upper()
    if mat in profile.get("right_nozzle_refuses", ()):
        out.append(f"{mat}: the X2D right nozzle (Bowden) cannot print it; every part goes on the left nozzle")
    if used_two_nozzle_bed:
        b = profile["bed_two_nozzles"]
        out.append(f"{n_colours} colours: checked against the {b[0]:g} x {b[1]:g} x {b[2]:g} mm "
                   "that both nozzles reach; leave room for the prime tower too")
    out.append(f"plate: {profile['plate']} by default (the bottom face takes its texture)")
    return out


def _layers(z0: float, z1: float, layer: float) -> int:
    return max(0, int(round((z1 - z0) / layer)))


def colour_layers(parts: Sequence[dict], layer: float) -> dict:
    """How many layers hold 2 or more colours, by each part's height range.

    parts: [{"stl": str, "z": (zmin, zmax)}]. A height-range estimate: a part
    counts in a layer when the layer's middle is inside its z range.
    """
    if not parts or layer <= 0:
        return {"layers": 0, "mixed_layers": 0, "max_colours_per_layer": 0}
    top = max(p["z"][1] for p in parts)
    n = _layers(0.0, top, layer)
    mixed, most = 0, 0
    for k in range(n):
        zc = (k + 0.5) * layer
        here = sum(1 for p in parts if p["z"][0] < zc < p["z"][1])
        most = max(most, here)
        if here >= 2:
            mixed += 1
    return {"layers": n, "mixed_layers": mixed, "max_colours_per_layer": most}


def suggest_nozzles(profile: dict, parts: Sequence[dict], material: str) -> Dict[str, str]:
    """Dominant colour (most layers, then most volume) on its own nozzle.

    On the X2D the AMS feeds the left nozzle and the external spool the
    right one, so the dominant colour goes right (external spool) and the
    accents left (AMS). One colour, or TPU: everything left.
    """
    if profile["name"] != "bambu-x2d" or not parts:
        return {}
    if len(parts) == 1 or (material or "").upper() in profile.get("right_nozzle_refuses", ()):
        return {p["stl"]: "left" for p in parts}
    dominant = max(parts, key=lambda p: (p["layers"], p.get("volume_mm3", 0.0)))
    return {p["stl"]: ("right" if p is dominant else "left") for p in parts}


def x2d_job(name: str, parts: Sequence[dict], *, assembly: bool, material: str, layer: float,
            nozzle: float, supports: bool, profile: dict, printer_notes: Sequence[str]) -> dict:
    """Draft job for the x2d-print skill (its templates/job.example.json format).

    `template` and each part's `filament` stay empty on purpose: they come
    from the Bambu Studio template the person saves in x2d-print step 3,
    because only that file knows which colour sits in which AMS slot.
    x2d-print refuses the job until they are filled.
    """
    stl_parts = [{"stl": p["stl"], "filament": None, "colour": p["colour"], "colour_hex": p["colour_hex"]}
                 for p in parts]
    if assembly:
        objects = [{"name": name, "parts": stl_parts}]
    else:
        objects = [{"name": Path(p["stl"]).stem, "parts": [p]} for p in stl_parts]
    mix = colour_layers([{"stl": p["stl"], "z": p["z"]} for p in parts], layer) if assembly else {}
    nozzles = suggest_nozzles(profile, parts, material)
    settings = {"enable_support": "1"} if supports else {}
    todo = [
        "template: the .3mf saved from Bambu Studio (x2d-print step 3)",
        "filament: for each part, the number of the template filament with that colour",
        "nozzles: from the template's filament numbers, following design.suggested_nozzles",
        f"check that the template's filaments are {material}",
    ]
    return {
        "name": name,
        "template": "",
        "objects": objects,
        "nozzles": {},
        "settings": settings,
        "output": f"{name}.3mf",
        "design": {
            "from": "3d-print-design",
            "format": 1,
            "printer": profile["label"],
            "material": material,
            "layer_mm": layer,
            "nozzle_mm": nozzle,
            "supports": bool(supports),
            "assembly": bool(assembly),
            "parts": [{"stl": p["stl"], "colour": p["colour"], "colour_hex": p["colour_hex"],
                       "z_mm": [round(p["z"][0], 3), round(p["z"][1], 3)], "layers": p["layers"],
                       "volume_mm3": round(p.get("volume_mm3", 0.0), 1)} for p in parts],
            "colour_layers": mix,
            "suggested_nozzles": nozzles,
            "notes": list(printer_notes),
            "todo": todo,
        },
    }


def write_handoff(out_dir: Path, job: dict, filename: str) -> Path:
    """Write the draft job as out/<filename>, refusing symlinks like every other output."""
    if Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError(f"bad hand-off file name {filename!r}")
    path = Path(out_dir) / filename
    atomic_write(path, json.dumps(job, indent=2, ensure_ascii=False) + "\n")
    return path
