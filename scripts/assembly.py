"""assembly: checks for a multicolour object printed in place.

A multicolour print is one object made of several parts, one STL per
colour, all in the same coordinate frame (a top inlay sits on the base, it
does not touch the bed). Checking each part alone would call the inlay
"floating", so the bed, build volume and overhang checks run on the parts
joined together, and three checks are added:

  overlap        two colour parts must touch, never share volume: the
                 slicer would have to pick a colour for the shared plastic
  colour_layers  how many layers hold more colours than the printer has
                 nozzles: each one costs a filament change and a purge
  colour_thickness  a colour part thinner than 3 layers may let the colour
                 under it show through

Each part still gets its own watertight, bodies, holes, thin walls, layer
and probe checks (printcheck with standalone=False).
"""
from __future__ import annotations

from typing import Dict, Sequence

import cad
import printcheck
from printcheck import FAIL, PASS, WARN, Check, CheckResult
from printers import MIN_COLOUR_LAYERS, colour_layers

OVERLAP_TOL_MM3 = 0.05      # booleans of touching faces leave crumbs far smaller than this
MIXED_LAYERS_WARN = 10      # more layers than this with extra colour changes gets a warning


def check_assembly(solids: Dict[str, "cad.Solid"], *, bed, layer: float, nozzle: float,
                   overhang_deg: float, supports: bool, expected_bodies=1, nozzles: int = 1,
                   margin: float = 5.0) -> CheckResult:
    """Check the joined object and the relations between its colour parts."""
    names = list(solids)
    joined = cad.union(*solids.values())
    mesh = cad.to_trimesh(joined)
    res = printcheck.check_printable(
        mesh, bed=bed, layer=layer, nozzle=nozzle, overhang_deg=overhang_deg,
        supports=supports, expected_bodies=expected_bodies, margin=margin, thin_wall_samples=0)
    checks = [c for c in res.checks if c.name not in ("small_holes",)]

    # overlap ---------------------------------------------------------------
    overlaps = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            vol = float(cad.intersection(solids[a], solids[b]).volume())
            if vol > OVERLAP_TOL_MM3:
                overlaps.append({"parts": [a or "(main)", b or "(main)"], "volume_mm3": round(vol, 3)})
    if overlaps:
        first = overlaps[0]
        checks.append(Check("overlap", FAIL,
                            f"{len(overlaps)} pair(s) of colour parts share volume (e.g. {first['parts'][0]} and "
                            f"{first['parts'][1]}, {first['volume_mm3']:g} mm3): subtract one from the other",
                            {"overlaps": overlaps}))
    else:
        checks.append(Check("overlap", PASS, f"{len(names)} colour parts touch without sharing volume", {}))

    # colour layers ---------------------------------------------------------
    spans = []
    for n in names:
        lo = solids[n].bounding_box()
        spans.append({"stl": n, "z": (float(lo[2]), float(lo[5]))})
    mix = colour_layers(spans, layer)
    extra = _layers_over(spans, layer, nozzles)
    mix["layers_over_nozzles"] = extra
    if extra > MIXED_LAYERS_WARN:
        checks.append(Check("colour_layers", WARN,
                            f"{extra} of {mix['layers']} layers hold more colours than the {nozzles} nozzle(s): "
                            "each costs a filament change and a purge; keep accents in few layers",
                            mix))
    else:
        checks.append(Check("colour_layers", PASS,
                            f"colours meet in {mix['mixed_layers']} of {mix['layers']} layers, "
                            f"{extra} need a filament change on the same nozzle", mix))

    # colour thickness ------------------------------------------------------
    thin = [{"part": s["stl"] or "(main)", "layers": round((s["z"][1] - s["z"][0]) / layer, 2)}
            for s in spans if (s["z"][1] - s["z"][0]) < MIN_COLOUR_LAYERS * layer - 1e-6]
    if thin:
        checks.append(Check("colour_thickness", WARN,
                            f"{len(thin)} colour part(s) thinner than {MIN_COLOUR_LAYERS} layers "
                            f"({MIN_COLOUR_LAYERS * layer:g} mm): the colour beneath may show through",
                            {"thin": thin}))
    else:
        checks.append(Check("colour_thickness", PASS,
                            f"every colour part is at least {MIN_COLOUR_LAYERS} layers thick", {}))
    return CheckResult(checks, res.stats)


def _layers_over(spans: Sequence[dict], layer: float, nozzles: int) -> int:
    """Layers where the colour count is above the nozzle count (changes that need a purge)."""
    top = max(s["z"][1] for s in spans)
    n = max(0, int(round(top / layer)))
    count = 0
    for k in range(n):
        zc = (k + 0.5) * layer
        if sum(1 for s in spans if s["z"][0] < zc < s["z"][1]) > max(1, int(nozzles)):
            count += 1
    return count
