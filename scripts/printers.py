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

    parts: [{"stl": str, "z": (zmin, zmax), "colour": name}], every part on the
    plate (an assembly or separate objects: two objects of different colours
    side by side share every layer). Parts of the same colour count once; a
    part without "colour" counts as its own colour. A height-range estimate: a
    part counts in a layer when the layer's middle is inside its z range.
    """
    if not parts or layer <= 0:
        return {"layers": 0, "mixed_layers": 0, "max_colours_per_layer": 0}
    top = max(p["z"][1] for p in parts)
    n = _layers(0.0, top, layer)
    mixed, most = 0, 0
    for k in range(n):
        zc = (k + 0.5) * layer
        here = len({p.get("colour") or p.get("stl") for p in parts if p["z"][0] < zc < p["z"][1]})
        most = max(most, here)
        if here >= 2:
            mixed += 1
    return {"layers": n, "mixed_layers": mixed, "max_colours_per_layer": most}


def _by_colour(parts: Sequence[dict]) -> Dict[str, dict]:
    """Group parts by colour name: layers = most layers of any part, volume summed."""
    out: Dict[str, dict] = {}
    for p in parts:
        c = out.setdefault(p.get("colour") or "", {"layers": 0, "volume_mm3": 0.0})
        c["layers"] = max(c["layers"], int(p.get("layers", 0)))
        c["volume_mm3"] += float(p.get("volume_mm3", 0.0))
    return out


def nozzle_options(profile: dict, parts: Sequence[dict], material: str, mixed_layers: Optional[int] = None,
                   external_spool: bool = True) -> List[dict]:
    """The nozzle plans worth comparing, keyed by colour name (job format 2).

    On the X2D the AMS feeds the left nozzle and the external spool the right
    one. "all_left" (AMS only, nothing on the external holder) is always a
    plan. Two more are added only when they can help: two or more colours that
    share layers (`mixed_layers` > 0, counted over every part on the plate), a
    material the right nozzle takes (not TPU) and a spool that can go on the
    external holder:
    - "accent_right": the main colour (most layers, then most volume) stays in
      the AMS on the left nozzle and the largest other colour goes on the
      external spool. The left nozzle is the fast one, so this is usually the
      quickest two-nozzle plan;
    - "dominant_right": the main colour on the external spool, the others in
      the AMS. Same purge, but the main colour is printed by the slower right
      nozzle; with three or more colours it can still win, because it takes
      the colour every layer needs off the nozzle that swaps.
    A nozzle switch costs no colour purge, only a prime tower layer; the caller
    estimates every plan and picks the fastest.
    """
    if profile["name"] != "bambu-x2d" or not parts:
        return []
    colours = _by_colour(parts)
    plans = [{"option": "all_left", "label": "all colours on the left nozzle (AMS)",
              "nozzles": {c: "left" for c in colours}}]
    if (len(colours) < 2 or (material or "").upper() in profile.get("right_nozzle_refuses", ())
            or not mixed_layers or not external_spool):
        return plans
    ranked = sorted(colours, key=lambda c: (colours[c]["layers"], colours[c]["volume_mm3"]), reverse=True)
    dominant, accent = ranked[0], ranked[1]
    for option, on_right in (("accent_right", accent), ("dominant_right", dominant)):
        plans.append({"option": option, "label": f"{on_right} on the right nozzle (external spool)",
                      "nozzles": {c: ("right" if c == on_right else "left") for c in colours}})
    return plans


def suggest_nozzles(profile: dict, parts: Sequence[dict], material: str, mixed_layers: Optional[int] = None,
                    external_spool: bool = True) -> Dict[str, str]:
    """Rule-of-thumb plan without an estimate: when colours share layers, the main colour stays on
    the left nozzle (AMS) and the largest other colour goes on the right one (external spool).

    The build uses nozzle_options() and the time estimate instead; this stays
    for callers that have no estimate (one colour, colours only by height and
    TPU always give all left).
    """
    plans = nozzle_options(profile, parts, material, mixed_layers, external_spool)
    by_name = {p["option"]: p for p in plans}
    chosen = by_name.get("accent_right") or by_name.get("all_left")
    return chosen["nozzles"] if chosen else {}


def slicer_settings(*, walls: int, infill: float, layer: float, top_layers: int, bottom_layers: int,
                    supports: bool) -> Dict[str, str]:
    """The design's print settings as Bambu Studio strings (job `settings`)."""
    return {
        "layer_height": f"{layer:g}",
        "wall_loops": str(int(walls)),
        "sparse_infill_density": f"{infill:g}%",
        "top_shell_layers": str(int(top_layers)),
        "bottom_shell_layers": str(int(bottom_layers)),
        "enable_support": "1" if supports else "0",
    }


def x2d_job(name: str, parts: Sequence[dict], *, assembly: bool, material: str, layer: float,
            nozzle: float, supports: bool, profile: dict, printer_notes: Sequence[str],
            settings: Optional[Dict[str, str]] = None, estimate: Optional[dict] = None,
            variants: Optional[Sequence[dict]] = None, variant: str = "standard", quantity: int = 1,
            first_print: Optional[bool] = None, suggested_nozzles: Optional[Dict[str, str]] = None,
            nozzle_options: Optional[Sequence[dict]] = None, external_spool: bool = True) -> dict:
    """Draft job for the x2d-print skill (format 2, see its SKILL.md).

    `template` and each part's `filament` stay empty on purpose: they come
    from the Bambu Studio template the person saves in x2d-print, because
    only that file knows which colour sits in which filament slot. x2d-print
    refuses the job until they are filled. `settings` carries the version
    chosen here (walls, infill, layer height) so the .3mf prints what was
    estimated; `variants` lists the other versions to compare by slicing.
    """
    stl_parts = [{"stl": p["stl"], "filament": None, "colour": p["colour"], "colour_hex": p["colour_hex"]}
                 for p in parts]
    if assembly:
        objects = [{"name": name, "parts": stl_parts}]
    else:
        objects = [{"name": Path(p["stl"]).stem, "parts": [p]} for p in stl_parts]
    spans = [{"stl": p["stl"], "z": p["z"], "colour": p["colour"]} for p in parts]
    mix = colour_layers(spans, layer)
    nozzles = (dict(suggested_nozzles) if suggested_nozzles is not None
               else suggest_nozzles(profile, parts, material, mix.get("mixed_layers"), external_spool))
    if settings is None:
        settings = {"enable_support": "1"} if supports else {}
    todo = [
        "template: the .3mf saved from Bambu Studio (x2d-print), after loading the colours below",
        "filament: for each part, the number of the template filament with that colour",
        "nozzles: filament number -> left/right, from design.suggested_nozzles (keyed by colour)",
        f"check that the template's filaments are {material}",
    ]
    design = {
        "from": "3d-print-design",
        "format": 2,
        "printer": profile["label"],
        "material": material,
        "layer_mm": layer,
        "nozzle_mm": nozzle,
        "supports": bool(supports),
        "assembly": bool(assembly),
        "variant": variant,
        "quantity": max(1, int(quantity)),
        "parts": [{"stl": p["stl"], "colour": p["colour"], "colour_hex": p["colour_hex"],
                   "z_mm": [round(p["z"][0], 3), round(p["z"][1], 3)], "layers": p["layers"],
                   "volume_mm3": round(p.get("volume_mm3", 0.0), 1)} for p in parts],
        "colour_layers": mix,
        "suggested_nozzles": nozzles,
        "external_spool": bool(external_spool),
        "notes": list(printer_notes),
        "todo": todo,
    }
    if first_print is not None:
        design["first_print"] = bool(first_print)
    if estimate:
        design["estimate"] = estimate
    if nozzle_options:
        design["nozzle_options"] = [dict(o) for o in nozzle_options]
    job = {
        "name": name,
        "template": "",
        "objects": objects,
        "nozzles": {},
        "settings": dict(settings),
        "output": f"{name}.3mf",
        "design": design,
    }
    if variants:
        job["variants"] = list(variants)
    return job


def keep_filled(new: dict, old: Optional[dict]) -> List[str]:
    """Carry over what x2d-print filled in (template, filament numbers, nozzles).

    Only when every part keeps its STL name and colour: otherwise the filament
    numbers could point at the wrong colour, so they are reset and the caller
    says so. Returns notes for the build log.
    """
    if not isinstance(old, dict):
        return []
    def colours(job):
        return sorted((str(p.get("stl")), str(p.get("colour"))) for o in job.get("objects", []) if isinstance(o, dict)
                      for p in o.get("parts", []) if isinstance(p, dict))
    filled = bool(old.get("template")) or any(isinstance(p.get("filament"), int) for o in old.get("objects", [])
                                              if isinstance(o, dict) for p in o.get("parts", []) if isinstance(p, dict))
    if not filled:
        return []
    if colours(new) != colours(old):
        return ["the parts or colours changed: template and filament numbers in the old x2d-job.json were reset, "
                "fill them again in x2d-print"]
    if isinstance(old.get("template"), str):
        new["template"] = old["template"]
    fil = {str(p.get("stl")): p.get("filament") for o in old.get("objects", []) if isinstance(o, dict)
           for p in o.get("parts", []) if isinstance(p, dict)}
    for o in new["objects"]:
        for p in o["parts"]:
            if isinstance(fil.get(p["stl"]), int):
                p["filament"] = fil[p["stl"]]
    if isinstance(old.get("nozzles"), dict):
        new["nozzles"] = dict(old["nozzles"])
    return ["kept the template, filament numbers and nozzles already filled in x2d-job.json"]


def read_handoff(out_dir: Path, filename: str) -> Optional[dict]:
    """The previous hand-off file, or None (missing, unreadable or a symlink)."""
    path = Path(out_dir) / filename
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_handoff(out_dir: Path, job: dict, filename: str) -> Path:
    """Write the draft job as out/<filename>, refusing symlinks like every other output."""
    if Path(filename).name != filename or not filename.endswith(".json"):
        raise ValueError(f"bad hand-off file name {filename!r}")
    path = Path(out_dir) / filename
    atomic_write(path, json.dumps(job, indent=2, ensure_ascii=False) + "\n")
    return path
