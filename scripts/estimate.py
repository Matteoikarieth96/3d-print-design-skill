"""estimate: filament and print time before slicing, so the person can choose a version.

The slicer (Bambu Studio, PrusaSlicer, Cura...) gives the real figure. This
module answers the question a beginner asks first, "how long and how much
filament?", while the design is still numbers, and lets several versions
(light / standard / strong, smaller, fewer colours) be compared side by side.

Material model, per part:
  shell = up-facing area x top layers x layer height
        + down-facing area x bottom layers x layer height
        + side area x walls x line width           (capped at the part volume)
  core  = (volume - shell) x infill
  grams = (shell + core) x density, metres = volume / filament cross section

Time model (seconds), fitted on real slices:
  prep + shell x s_shell + core x s_core + layers x s_layer
  + same-nozzle colour swaps x s_swap + nozzle switches x s_switch

Bambu Lab X2D numbers were fitted on 31 Bambu Studio 02.09 command-line
slices (0.20mm Standard @BBL X2D, PLA, template from the person's own Bambu
Studio): 7 shapes from a 60 x 24 x 4 mm plate to a 100 x 80 x 10 mm slab and a
60 mm tall tube, at 2/10 %, 2/15 %, 3/15 % and 4/40 % walls/infill, plus a
40 x 40 x 10 mm block printed in one colour, two colours on one nozzle and two
colours on two nozzles, and the two-colour coaster example (star on the
other nozzle). Grams were within 9 % of the slicer, time within 17 % (mean
8 %). The generic profile is a rough guess for a typical bed-slinger
printer, not measured: say so.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

# g/cm3, same table as cad.DENSITY_G_CM3 (kept here so this module stands alone)
DENSITY = {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21, "ABS": 1.04, "ASA": 1.07}
FILAMENT_MM2 = math.pi * (1.75 / 2) ** 2   # 1.75 mm filament: 2.405 mm2, 1 m = 2405 mm3

# Spread of the time model on the calibration slices; shown as a range.
TIME_SPREAD = 0.20
GRAMS_SPREAD = 0.10

SPEEDS: Dict[str, dict] = {
    "bambu-x2d": {
        "measured": True,
        "prep_s": 466.0,          # heating, levelling, nozzle checks: about 8 minutes per print
        "shell_s_mm3": 0.090,     # walls and solid layers: about 11 mm3/s
        "core_s_mm3": 0.075,      # sparse infill: about 13 mm3/s
        "layer_s": 3.1,           # travel, layer change, wipe
        "swap_s": 125.0,          # AMS colour swap on the same nozzle: cut, change, flush
        "swap_g": 0.75,           # filament flushed per swap (plus prime tower share)
        "second_nozzle_s": 497.0, # using both nozzles: heating and priming the second one, once per print
        "second_nozzle_g": 0.8,   # prime tower base and first prime of the second nozzle
        "switch_s": 21.0,         # each switch to the other nozzle (already loaded)
        "switch_g": 0.09,         # prime tower share per switch
    },
    "generic": {
        "measured": False,
        "prep_s": 300.0,
        "shell_s_mm3": 0.25,      # about 4 mm3/s, typical 50 to 60 mm/s printer
        "core_s_mm3": 0.18,
        "layer_s": 2.0,
        "swap_s": 300.0,          # manual filament change (M600): the person swaps the spool
        "swap_g": 0.5,
        "second_nozzle_s": 0.0,
        "second_nozzle_g": 0.0,
        "switch_s": 0.0,
        "switch_g": 0.0,
    },
}


def material_volume(mesh, *, layer: float, nozzle: float, walls: int, infill: float,
                    top_layers: int, bottom_layers: int) -> dict:
    """Extruded volume (mm3) of one watertight trimesh at these slicer settings."""
    n = mesh.face_normals[:, 2]
    a = mesh.area_faces
    up = float(a[n >= 0.5].sum())
    down = float(a[n <= -0.5].sum())
    side = float(a[np.abs(n) < 0.5].sum())
    line = 1.125 * nozzle                       # slicer default line width (0.45 for 0.4)
    volume = float(abs(mesh.volume))
    shell = min(volume, up * top_layers * layer + down * bottom_layers * layer + side * walls * line)
    core = max(volume - shell, 0.0) * max(0.0, min(infill, 100.0)) / 100.0
    lo, hi = mesh.bounds
    return {"volume_mm3": volume, "shell_mm3": shell, "core_mm3": core,
            "z": (float(lo[2]), float(hi[2]))}


def colour_changes(spans: Sequence[dict], layer: float, nozzle_of: Dict[str, str]) -> dict:
    """Count same-nozzle swaps and nozzle switches layer by layer.

    spans: [{"colour": name, "z": (z0, z1)}]; nozzle_of: colour -> "left"/"right"
    (missing = "left"). Simulates the slicer's usual order: start each layer with
    the colour already loaded, then the others on the same nozzle, then the
    other nozzle. Good enough to show why colours in many layers are slow.
    """
    if not spans or layer <= 0:
        return {"swaps": 0, "switches": 0}
    top = max(s["z"][1] for s in spans)
    loaded: Dict[str, Optional[str]] = {"left": None, "right": None}
    current = None
    swaps = switches = 0
    for k in range(max(0, int(round(top / layer)))):
        zc = (k + 0.5) * layer
        here = sorted({s["colour"] for s in spans if s["z"][0] < zc < s["z"][1]})
        groups: Dict[str, List[str]] = {}
        for c in here:
            groups.setdefault(nozzle_of.get(c, "left"), []).append(c)
        order = sorted(groups, key=lambda nz: nz != current)
        for nz in order:
            cols = groups[nz]
            if current is not None and nz != current:
                switches += 1
            current = nz
            if loaded[nz] in cols:
                cols = [loaded[nz]] + [c for c in cols if c != loaded[nz]]
            for c in cols:
                if loaded[nz] is not None and loaded[nz] != c:
                    swaps += 1
                loaded[nz] = c
    return {"swaps": swaps, "switches": switches}


def estimate(parts: Sequence[dict], *, profile: str, material: str, layer: float, quantity: int = 1,
             nozzle_of: Optional[Dict[str, str]] = None) -> dict:
    """Totals for one print. parts: material_volume() dicts plus "colour".

    Copies (quantity) multiply material and printing time, not the preparation
    or the colour changes (copies on one plate share them).
    """
    sp = SPEEDS.get(profile, SPEEDS["generic"])
    q = max(1, int(quantity))
    shell = sum(p["shell_mm3"] for p in parts)
    core = sum(p["core_mm3"] for p in parts)
    top = max((p["z"][1] for p in parts), default=0.0)
    layers = int(round(top / layer)) if layer > 0 else 0
    ch = colour_changes([{"colour": p.get("colour", ""), "z": p["z"]} for p in parts], layer, nozzle_of or {})
    if sp["switch_s"] == 0 and ch["switches"]:      # one-nozzle printer: a switch is a swap
        ch = {"swaps": ch["swaps"] + ch["switches"], "switches": 0}
    two = 1 if ch["switches"] else 0
    purge_g = ch["swaps"] * sp["swap_g"] + ch["switches"] * sp["switch_g"] + two * sp["second_nozzle_g"]
    density = DENSITY.get((material or "PLA").upper(), DENSITY["PLA"])
    model_mm3 = (shell + core) * q
    model_g = model_mm3 * density / 1000.0
    total_g = model_g + purge_g
    print_s = (shell * sp["shell_s_mm3"] + core * sp["core_s_mm3"] + layers * sp["layer_s"]) * q
    colour_s = ch["swaps"] * sp["swap_s"] + ch["switches"] * sp["switch_s"] + two * sp["second_nozzle_s"]
    total_s = sp["prep_s"] + print_s + colour_s
    return {
        "measured_profile": sp["measured"],
        "quantity": q,
        "layers": layers,
        "model_g": round(model_g, 1),
        "purge_g": round(purge_g, 1),
        "grams": round(total_g, 1),
        "grams_range": [round(total_g * (1 - GRAMS_SPREAD), 1), round(total_g * (1 + GRAMS_SPREAD), 1)],
        "metres": round(total_g / density * 1000.0 / FILAMENT_MM2 / 1000.0, 2),
        "minutes": round(total_s / 60.0),
        "minutes_range": [_floor5(total_s / 60.0 * (1 - TIME_SPREAD)), _ceil5(total_s / 60.0 * (1 + TIME_SPREAD))],
        "prep_min": round(sp["prep_s"] / 60.0),
        "colour_min": round(colour_s / 60.0),
        "swaps": ch["swaps"],
        "nozzle_switches": ch["switches"],
    }


def _floor5(minutes: float) -> int:
    return max(5, int(5 * math.floor(minutes / 5.0)))


def _ceil5(minutes: float) -> int:
    return max(5, int(5 * math.ceil(minutes / 5.0)))


def duration(minutes: float) -> str:
    """'45 min', '1 h 20 min'."""
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def describe(est: dict, label: str, material: str) -> str:
    """One plain sentence for the build log and the print sheet."""
    lo, hi = est["minutes_range"]
    s = (f"estimate ({label}): about {est['grams']:g} g of {material} ({est['metres']:g} m), "
         f"{duration(lo)} to {duration(hi)} including about {est['prep_min']} min of printer preparation")
    if est["swaps"] or est["nozzle_switches"]:
        s += (f"; colour changes: {est['swaps']} swap(s) on one nozzle, {est['nozzle_switches']} nozzle switch(es), "
              f"about {est['colour_min']} min and {est['purge_g']:g} g of purge")
    if est["quantity"] > 1:
        s += f"; {est['quantity']} copies"
    if not est["measured_profile"]:
        s += " (rough: speeds of a typical printer, not measured)"
    return s + ". The slicer gives the exact figure."


def table(rows: Sequence[dict], material: str) -> str:
    """Markdown table of versions: rows = {name, about, estimate, ok}."""
    out = ["| Version | What changes | Filament | Print time | Checks |", "|---|---|---|---|---|"]
    for r in rows:
        e = r.get("estimate")
        if not e:
            out.append(f"| {r['name']} | {r['about']} | - | - | failed |")
            continue
        lo, hi = e["minutes_range"]
        fil = f"~{e['grams']:g} g {material} ({e['metres']:g} m)"
        if e["purge_g"]:
            fil += f", {e['purge_g']:g} g purge"
        out.append(f"| {r['name']} | {r['about']} | {fil} | {duration(lo)} to {duration(hi)} | "
                   f"{'pass' if r.get('ok') else 'failed'} |")
    return "\n".join(out)
