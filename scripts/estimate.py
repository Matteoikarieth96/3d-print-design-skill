"""estimate: filament and print time before slicing, so the person can choose a version.

The slicer (Bambu Studio, PrusaSlicer, Cura...) gives a closer figure. This
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
  prep + sum over layers of max(layer print time + s_layer, minimum layer time)
  + same-nozzle colour swaps x s_swap + nozzle switches x s_switch
  (+ once s_second_nozzle when both nozzles print)
  + what the slower right nozzle adds (right_nozzle_seconds)
where a part's printing time (shell x s_shell + core x s_core) is spread over
its layers in proportion to each layer's cross-section area. A part on the
right nozzle prints slower: its walls take 1.54 times as long and the rest
1.08 times (Bambu Studio's X2D process limits the right, Bowden nozzle to
50 mm/s on outer walls against 200 on the left one, and to a tenth of the
acceleration), and each prime tower layer it prints alone costs 12 s more.
Purge grams also count the prime tower layers below the last colour change
that hold no change (the tower is printed from the first layer). The minimum layer
time is Bambu Studio's own "slow down for better layer cooling" setting of the
Generic PLA profile (8 s): small layers are slowed down to it, never below its
20 mm/s minimum speed, which is why a tall thin part takes much longer than its
filament suggests.

Bambu Lab X2D numbers: Bambu Studio 02.09.01.70 command-line slices, process
"0.20mm Standard @BBL X2D", Generic PLA, 0.4 mm nozzle, Textured PEI plate
(references/estimate-calibration.md; every slice is a row of
references/estimate-calibration.csv, and tests/test_estimate_calibration.py
keeps that file and this code in step).
- Calibration error (43 slices: 7 simple shapes at 2/10 %, 2/15 %, 3/15 % and
  4/40 % walls/infill, a 40 x 40 x 10 mm block in one and two colours on one
  and two nozzles, the coaster example, and the 2026-11 run that refitted the
  second-nozzle numbers on a block, the coaster and a hollow ball with either
  colour, or the whole part, on the right nozzle):
  time within 13 % (mean 3 %), grams within 10 % (mean 4 %).
- Out-of-sample error, reported apart (24 holdout slices never used for
  fitting, parts designed with this skill and sliced through x2d-print; 23 of
  them inside the measured field): time within 32 % (mean 7 %), grams within
  16 % (mean 7 %). The slicer was slower than the model on parts with many
  small features (the calibration coupon +47 %, a plate with 25 holes +28 %),
  so the time range reaches 50 % above the estimate.
The minimum layer time was added after the first holdout (a 15 x 15 x 80 mm
post took 61 min against 39 estimated) and capped by the minimum speed after
the second (a 12 x 70 mm pin); the coefficients were refitted on the
calibration rows only. Those two holdout rows are marked in the CSV.

The generic profile is a rough guess for a typical bed-slinger printer, not
measured: it always gets the wide range and the "rough" label.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

# g/cm3, same table as cad.DENSITY_G_CM3 (kept here so this module stands alone)
DENSITY = {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21, "ABS": 1.04, "ASA": 1.07}
FILAMENT_MM2 = math.pi * (1.75 / 2) ** 2   # 1.75 mm filament: 2.405 mm2, 1 m = 2405 mm3

# Range shown around the estimate: (below, above) as fractions of the estimate.
# Inside the measured field every calibration and holdout row falls inside it
# (tests/test_estimate_calibration.py checks this on the published CSV). Time
# was widened upwards after the holdout: detailed parts print slower.
TIME_SPREAD = (0.15, 0.50)
GRAMS_SPREAD = (0.15, 0.10)
# Outside the measured field (another printer, material, nozzle, layer height,
# supports or infill above 40 %): a rough figure, trust the slicer.
ROUGH_TIME_SPREAD = (0.35, 0.80)
ROUGH_GRAMS_SPREAD = (0.35, 0.80)
TPU_SPREAD = (0.45, 1.20)        # TPU prints much slower and its speeds vary a lot
ROUGH_LABEL = "rough: outside the measured range, trust the slicer"

# What the X2D numbers were measured on (estimate-calibration.md).
CALIBRATED = {"profile": "bambu-x2d", "material": "PLA", "nozzle": 0.4, "layer": 0.2, "max_infill": 40.0,
              "walls": (2, 4), "top_bottom": (5, 3), "max_colours": 2}

SPEEDS: Dict[str, dict] = {
    "bambu-x2d": {
        "measured": True,
        "prep_s": 388.0,          # heating, levelling, nozzle checks: about 6.5 minutes per print
        "shell_s_mm3": 0.0964,    # walls and solid layers: about 10 mm3/s
        "core_s_mm3": 0.0835,     # sparse infill: about 12 mm3/s
        "layer_s": 1.95,          # travel, layer change, wipe
        "min_layer_s": 8.0,       # Generic PLA slow_down_layer_time: small layers are slowed to 8 s
        "min_speed_mm_s": 20.0,   # Generic PLA slow_down_min_speed: but never below 20 mm/s
        "swap_s": 127.0,          # AMS colour swap on the same nozzle: cut, change, flush
        "swap_g": 0.72,           # filament flushed per swap (plus prime tower share)
        # Second nozzle: refitted on 9 slices of 3 objects (2026-11 run, estimate-calibration.md)
        "second_nozzle_s": 275.0, # using both nozzles: priming the second one, about 4.5 min once
        "second_nozzle_g": 0.16,  # first prime of the second nozzle
        "switch_s": 23.9,         # each switch to the other nozzle (already loaded), with its prime tower layer
        "switch_g": 0.103,        # prime tower share per switch
        "tower_layer_g": 0.0315,  # each prime tower layer below the last change that holds no change
        "right_wall_x": 1.54,     # walls printed by the right nozzle take 1.54 times as long (outer wall 50 mm/s)
        "right_other_x": 1.08,    # solid layers and infill on the right nozzle: 1.08 times
        "right_tower_layer_s": 12.0,  # each no-change prime tower layer printed by the right nozzle
        "right_only_s": 182.0,    # a print that uses the right nozzle alone: about 3 min more preparation
    },
    "generic": {
        "measured": False,
        "prep_s": 300.0,
        "shell_s_mm3": 0.25,      # about 4 mm3/s, typical 50 to 60 mm/s printer
        "core_s_mm3": 0.18,
        "layer_s": 2.0,
        "min_layer_s": 8.0,       # most slicers slow small layers down to a few seconds each
        "min_speed_mm_s": 20.0,
        "swap_s": 300.0,          # manual filament change (M600): the person swaps the spool
        "swap_g": 0.5,
        "second_nozzle_s": 0.0,
        "second_nozzle_g": 0.0,
        "switch_s": 0.0,
        "switch_g": 0.0,
    },
}


def layer_areas(mesh, layer: float) -> np.ndarray:
    """Cross-section area (mm2) of a watertight mesh at the middle of each layer from z = 0.

    Each triangle that crosses a plane gives one directed segment; the shoelace
    sum over all segments is the section area (order does not matter, only the
    direction, which the face normal fixes).
    """
    if layer <= 0:
        return np.zeros(0)
    tri = np.asarray(mesh.vertices, dtype=float)[np.asarray(mesh.faces)]
    nrm = np.asarray(mesh.face_normals, dtype=float)
    top = float(tri[:, :, 2].max()) if len(tri) else 0.0
    n = max(0, int(round(top / layer)))
    zmin, zmax = tri[:, :, 2].min(1), tri[:, :, 2].max(1)
    out = np.zeros(n)
    edges = ((0, 1), (1, 2), (2, 0))
    for k in range(n):
        zc = (k + 0.5) * layer + 1e-7
        sel = (zmin < zc) & (zmax > zc)
        if not sel.any():
            continue
        t, nm = tri[sel], nrm[sel]
        above = t[:, :, 2] >= zc
        pts, cross = [], []
        for i, j in edges:
            c = above[:, i] != above[:, j]
            zi, zj = t[:, i, 2], t[:, j, 2]
            s = np.where(c, (zc - zi) / np.where(c, zj - zi, 1.0), 0.0)
            pts.append(t[:, i, :2] + s[:, None] * (t[:, j, :2] - t[:, i, :2]))
            cross.append(c)
        pts = np.stack(pts, 1)
        cross = np.stack(cross, 1)
        idx = np.argsort(~cross, axis=1, kind="stable")[:, :2]
        rows = np.arange(len(t))
        p, q = pts[rows, idx[:, 0]], pts[rows, idx[:, 1]]
        d = q - p
        flip = (d[:, 0] * -nm[:, 1] + d[:, 1] * nm[:, 0]) < 0
        p, q = np.where(flip[:, None], q, p), np.where(flip[:, None], p, q)
        out[k] = 0.5 * float(np.sum(p[:, 0] * q[:, 1] - p[:, 1] * q[:, 0]))
    return np.clip(out, 0.0, None)


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
    wall = min(shell, side * walls * line)      # the walls' share of the shell
    core = max(volume - shell, 0.0) * max(0.0, min(infill, 100.0)) / 100.0
    lo, hi = mesh.bounds
    return {"volume_mm3": volume, "shell_mm3": shell, "core_mm3": core,
            "z": (float(lo[2]), float(hi[2])), "layer_area": layer_areas(mesh, layer).tolist(),
            "wall_mm3": wall, "infill": float(infill), "nozzle": float(nozzle), "walls": int(walls),
            "top_layers": int(top_layers), "bottom_layers": int(bottom_layers)}


def colour_changes(spans: Sequence[dict], layer: float, nozzle_of: Dict[str, str]) -> dict:
    """Count same-nozzle swaps and nozzle switches layer by layer.

    spans: [{"colour": name, "z": (z0, z1)}]; nozzle_of: colour -> "left"/"right"
    (missing = "left"). Simulates the slicer's usual order: start each layer with
    the colour already loaded, then the others on the same nozzle, then the
    other nozzle. Good enough to show why colours in many layers are slow.
    "tower_layers" counts the layers below the last change that hold no change
    (the prime tower is printed from the first layer, so they are tower too);
    "tower_layers_right" those of them printed by the right nozzle.
    """
    if not spans or layer <= 0:
        return {"swaps": 0, "switches": 0, "tower_layers": 0, "tower_layers_right": 0}
    top = max(s["z"][1] for s in spans)
    loaded: Dict[str, Optional[str]] = {"left": None, "right": None}
    current = None
    swaps = switches = 0
    last = -1           # index of the last layer with a swap or a switch
    quiet = []          # (layer index, nozzle) of every layer without one
    for k in range(max(0, int(round(top / layer)))):
        before = swaps + switches
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
        if swaps + switches > before:
            last = k
        elif here:
            quiet.append((k, current))
    idle = [nz for k, nz in quiet if k < last]
    return {"swaps": swaps, "switches": switches, "tower_layers": len(idle),
            "tower_layers_right": sum(nz == "right" for nz in idle)}


def calibration_scope(*, profile: str, material: str, nozzle: float, layer: float, supports: bool,
                      infill: float, colours: int = 1, walls: Sequence[int] = (),
                      top_bottom: Sequence[Sequence[int]] = ()) -> List[str]:
    """Why an estimate falls outside the measured field ([] = inside it)."""
    why = []
    if profile != CALIBRATED["profile"]:
        why.append("printer speeds not measured (generic profile)")
    mat = (material or "PLA").upper()
    if mat != CALIBRATED["material"]:
        why.append(f"{mat} not measured (only PLA)")
    if abs(float(nozzle) - CALIBRATED["nozzle"]) > 1e-6:
        why.append(f"{float(nozzle):g} mm nozzle (measured: 0.4)")
    if abs(float(layer) - CALIBRATED["layer"]) > 1e-6:
        why.append(f"{float(layer):g} mm layers (measured: 0.2)")
    if supports:
        why.append("supports are not counted (they add filament and time)")
    if float(infill) > CALIBRATED["max_infill"] + 1e-6:
        why.append(f"{float(infill):g} % infill (measured up to 40 %)")
    if int(colours) > CALIBRATED["max_colours"]:
        why.append(f"{int(colours)} colours (measured: 1 or 2)")
    lo, hi = CALIBRATED["walls"]
    odd = sorted({int(w) for w in walls if not lo <= int(w) <= hi})
    if odd:
        why.append(f"{', '.join(map(str, odd))} walls (measured: {lo} to {hi})")
    odd_tb = sorted({tuple(int(x) for x in tb) for tb in top_bottom} - {CALIBRATED["top_bottom"]})
    if odd_tb:
        top, bottom = odd_tb[0]
        why.append(f"{top} top / {bottom} bottom layers (measured: 5 / 3)")
    return why


def print_seconds(parts: Sequence[dict], *, profile: str, layer: float, quantity: int = 1) -> float:
    """Printing time without preparation or colour changes, layer by layer (see module doc).

    A layer takes its share of the parts' printing time plus the layer change,
    but at least the slicer's minimum layer time; the slicer reaches that by
    slowing down, never below its minimum speed, so a layer with a very short
    path (a thin pin) stays shorter than the minimum layer time.
    """
    sp = SPEEDS.get(profile, SPEEDS["generic"])
    q = max(1, int(quantity))
    top = max((p["z"][1] for p in parts), default=0.0)
    n = int(round(top / layer)) if layer > 0 else 0
    per = np.zeros(n)       # seconds of extrusion per layer
    vol = np.zeros(n)       # mm3 extruded per layer
    # Thicker layers print walls and sparse infill at about the same mm/s, so faster per mm3;
    # top and bottom solid layers do not speed up (2 slices at 0.28 mm, estimate-calibration.md)
    f = CALIBRATED["layer"] / layer if layer > 0 else 1.0
    for p in parts:
        wall = min(p.get("wall_mm3", 0.0), p["shell_mm3"])
        t = ((p["shell_mm3"] - wall) * sp["shell_s_mm3"] + wall * sp["shell_s_mm3"] * f
             + p["core_mm3"] * sp["core_s_mm3"] * f)
        v = p["shell_mm3"] + p["core_mm3"]
        area = np.asarray(p.get("layer_area") or [], dtype=float)[:n]
        if area.size and area.sum() > 0:
            w = area / area.sum()
            per[:area.size] += t * w
            vol[:area.size] += v * w
        else:   # no layer profile: spread evenly over the part's own layers
            k0, k1 = int(round(p["z"][0] / layer)), max(int(round(p["z"][1] / layer)), 1)
            per[k0:k1] += t / max(k1 - k0, 1)
            vol[k0:k1] += v / max(k1 - k0, 1)
    per *= q
    vol *= q
    used = per > 0
    line = 1.125 * max((p.get("nozzle", 0.4) for p in parts), default=0.4)
    slowest = vol[used] / (line * layer) / sp["min_speed_mm_s"]     # whole layer path at the minimum speed
    floor = np.minimum(sp["min_layer_s"], slowest)
    return float(np.maximum(per[used] + sp["layer_s"], floor).sum())


def right_nozzle_seconds(parts: Sequence[dict], *, profile: str, layer: float, quantity: int = 1,
                         nozzle_of: Optional[Dict[str, str]] = None, tower_layers_right: int = 0) -> float:
    """Seconds the slower right nozzle adds: slower walls and fill of its parts, the prime tower
    layers it prints alone, and a longer preparation when no part is on the left nozzle."""
    sp = SPEEDS.get(profile, SPEEDS["generic"])
    nozzle_of = nozzle_of or {}
    f = CALIBRATED["layer"] / layer if layer > 0 else 1.0      # as in print_seconds
    extra = 0.0
    on_right = on_left = 0
    for p in parts:
        if nozzle_of.get(p.get("colour", ""), "left") != "right":
            on_left += 1
            continue
        on_right += 1
        wall = min(p.get("wall_mm3", 0.0), p["shell_mm3"])
        extra += (wall * sp["shell_s_mm3"] * f * (sp.get("right_wall_x", 1.0) - 1.0)
                  + ((p["shell_mm3"] - wall) * sp["shell_s_mm3"] + p["core_mm3"] * sp["core_s_mm3"] * f)
                  * (sp.get("right_other_x", 1.0) - 1.0))
    extra *= max(1, int(quantity))
    extra += tower_layers_right * sp.get("right_tower_layer_s", 0.0)
    if on_right and not on_left:
        extra += sp.get("right_only_s", 0.0)
    return extra


def estimate(parts: Sequence[dict], *, profile: str, material: str, layer: float, quantity: int = 1,
             nozzle_of: Optional[Dict[str, str]] = None, supports: bool = False,
             nozzle: Optional[float] = None) -> dict:
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
        ch = dict(ch, swaps=ch["swaps"] + ch["switches"], switches=0, tower_layers_right=0)
    two = 1 if ch["switches"] else 0
    purge_g = (ch["swaps"] * sp["swap_g"] + ch["switches"] * sp["switch_g"] + two * sp["second_nozzle_g"]
               + ch["tower_layers"] * sp.get("tower_layer_g", 0.0))
    density = DENSITY.get((material or "PLA").upper(), DENSITY["PLA"])
    model_mm3 = (shell + core) * q
    model_g = model_mm3 * density / 1000.0
    total_g = model_g + purge_g
    print_s = print_seconds(parts, profile=profile, layer=layer, quantity=q)
    colour_s = ch["swaps"] * sp["swap_s"] + ch["switches"] * sp["switch_s"] + two * sp["second_nozzle_s"]
    right_s = (right_nozzle_seconds(parts, profile=profile, layer=layer, quantity=q, nozzle_of=nozzle_of,
                                    tower_layers_right=ch["tower_layers_right"]) if sp["switch_s"] else 0.0)
    total_s = sp["prep_s"] + print_s + colour_s + right_s
    noz = nozzle if nozzle is not None else max((p.get("nozzle", 0.4) for p in parts), default=0.4)
    infill = max((p.get("infill", 0.0) for p in parts), default=0.0)
    why = calibration_scope(profile=profile, material=material, nozzle=noz, layer=layer, supports=supports,
                            infill=infill, colours=len({p.get("colour", "") for p in parts}),
                            walls=[p["walls"] for p in parts if "walls" in p],
                            top_bottom=[(p["top_layers"], p["bottom_layers"]) for p in parts
                                        if "top_layers" in p and "bottom_layers" in p])
    inside = not why and sp["measured"]
    if inside:
        t_sp, g_sp = TIME_SPREAD, GRAMS_SPREAD
    elif (material or "").upper() == "TPU":
        t_sp, g_sp = TPU_SPREAD, TPU_SPREAD
    else:
        t_sp, g_sp = ROUGH_TIME_SPREAD, ROUGH_GRAMS_SPREAD
    minutes = total_s / 60.0
    return {
        "measured_profile": sp["measured"],
        "in_calibration": inside,
        "outside_because": why,
        "quantity": q,
        "layers": layers,
        "model_g": round(model_g, 1),
        "purge_g": round(purge_g, 1),
        "grams": round(total_g, 1),
        "grams_range": [round(total_g * (1 - g_sp[0]), 1), round(total_g * (1 + g_sp[1]), 1)],
        "metres": round(total_g / density * 1000.0 / FILAMENT_MM2 / 1000.0, 2),
        "minutes": round(minutes),
        "minutes_exact": round(minutes, 2),
        "minutes_range": [_floor5(minutes * (1 - t_sp[0])), _ceil5(minutes * (1 + t_sp[1]))],
        "prep_min": round(sp["prep_s"] / 60.0),
        "colour_min": round(colour_s / 60.0),
        "right_nozzle_min": round(right_s / 60.0),
        "swaps": ch["swaps"],
        "nozzle_switches": ch["switches"],
        "tower_layers": ch["tower_layers"],
    }


def _floor5(minutes: float) -> int:
    return max(5, int(5 * math.floor(minutes / 5.0)))


def _ceil5(minutes: float) -> int:
    return max(5, int(5 * math.ceil(minutes / 5.0)))


def duration(minutes: float) -> str:
    """'45 min', '1 h 20 min'."""
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def time_text(est: dict) -> str:
    """'~39 min (30 to 50 min)'."""
    lo, hi = est["minutes_range"]
    return f"~{duration(est['minutes'])} ({duration(lo)} to {duration(hi)})"


def rough_text(est: dict) -> str:
    """The rough label with its reasons, or '' inside the measured range."""
    if est.get("in_calibration", est.get("measured_profile", False)):
        return ""
    why = est.get("outside_because") or []
    return ROUGH_LABEL + (f" ({'; '.join(why)})" if why else "")


def describe(est: dict, label: str, material: str) -> str:
    """One plain sentence for the build log and the print sheet."""
    lo, hi = est["minutes_range"]
    s = (f"estimate ({label}): about {est['grams']:g} g of {material} ({est['metres']:g} m), "
         f"about {duration(est['minutes'])} ({duration(lo)} to {duration(hi)}) including about "
         f"{est['prep_min']} min of printer preparation")
    if est["swaps"] or est["nozzle_switches"]:
        s += (f"; colour changes: {est['swaps']} swap(s) on one nozzle, {est['nozzle_switches']} nozzle switch(es), "
              f"about {est['colour_min']} min and {est['purge_g']:g} g of purge")
    if est.get("right_nozzle_min"):
        s += f"; the right nozzle prints slower: about {est['right_nozzle_min']} min of the total"
    if est["quantity"] > 1:
        s += f"; {est['quantity']} copies"
    other = est.get("other_nozzles")
    if other:
        s += f"; other nozzle choice ({other['label']}): ~{duration(other['minutes'])}, {other['grams']:g} g"
    rough = rough_text(est)
    if rough:
        s += f"; {rough}"
    return s + ". The slicer gives a closer figure."


def _signed(v: float, unit: str, fmt: str = "g") -> str:
    if unit == "min":
        return f"{'+' if v >= 0 else '-'}{duration(abs(v))}"
    return f"{v:+{fmt}} {unit}"


def table(rows: Sequence[dict], material: str) -> str:
    """Markdown table of versions: rows = {name, about, estimate, ok}; the first row is the reference."""
    out = ["| Version | What changes | Filament | Print time | vs standard | Checks |",
           "|---|---|---|---|---|---|"]
    ref = next((r.get("estimate") for r in rows if r.get("name") == "standard" and r.get("estimate")), None)
    rough = []
    notes = []
    for r in rows:
        e = r.get("estimate")
        if not e:
            out.append(f"| {r['name']} | {r['about']} | - | - | - | failed |")
            continue
        fil = f"~{e['grams']:g} g {material} ({e['metres']:g} m)"
        if e["purge_g"]:
            fil += f", of which {e['purge_g']:g} g purge"
        t = time_text(e)
        if rough_text(e):
            t += ", rough"
            rough.append(r["name"])
        if ref is None or e is ref:
            vs = "-"
        else:
            vs = f"{_signed(e['minutes'] - ref['minutes'], 'min')}, {_signed(round(e['grams'] - ref['grams'], 1), 'g')}"
        out.append(f"| {r['name']} | {r['about']} | {fil} | {t} | {vs} | {'pass' if r.get('ok') else 'failed'} |")
        other = e.get("other_nozzles")
        if other:
            notes.append(f"{r['name']}, other nozzle choice ({other['label']}): ~{duration(other['minutes'])}, "
                         f"{other['grams']:g} g")
    if rough:
        first = next(r["estimate"] for r in rows if r["name"] == rough[0])
        notes.append(f"{', '.join(rough)}: {rough_text(first)}")
    return "\n".join(out + ([""] + [f"- {n}" for n in notes] if notes else []))
