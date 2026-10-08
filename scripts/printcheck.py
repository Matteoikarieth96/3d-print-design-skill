#!/usr/bin/env python3
"""printcheck: pre-flight checks for an FDM part before it goes to the slicer.

Library:
    from printcheck import check_printable
    result = check_printable(mesh, bed=(220, 220, 250), layer=0.2, nozzle=0.4)
    if not result.ok: ...

CLI:
    python printcheck.py part.stl --bed 220x220x250 --layer 0.2 --overhang 45
    (exit code 0 = no errors, 1 = at least one error, 2 = bad arguments)

Units are millimetres, Z is up, the bed is the plane z = 0.

The checks never talk to a printer. They only read geometry. An STL file is
untrusted data: it is parsed as numbers, its header text is ignored.

Dependencies: numpy, trimesh, shapely (see requirements.txt). No scipy,
networkx or rtree needed: connected components and ray casting are done here
with numpy.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:  # trimesh and shapely are required for the full check set
    import trimesh
    import trimesh.intersections
    import trimesh.sample
except ImportError:  # pragma: no cover - reported at call time
    trimesh = None

try:
    import shapely
    from shapely.geometry import MultiLineString, Polygon
except ImportError:  # pragma: no cover
    shapely = None

MAX_STL_BYTES = 300 * 1024 * 1024  # refuse absurd files instead of eating all memory
BED_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*$")

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
@dataclass
class Check:
    name: str
    status: str
    message: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "message": self.message, "data": self.data}


@dataclass
class CheckResult:
    checks: List[Check]
    stats: dict

    @property
    def ok(self) -> bool:
        return not any(c.status == FAIL for c in self.checks)

    @property
    def errors(self) -> List[Check]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.status == WARN]

    def get(self, name: str) -> Optional[Check]:
        for c in self.checks:
            if c.name == name:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [c.name for c in self.errors],
            "warnings": [c.name for c in self.warnings],
            "checks": [c.to_dict() for c in self.checks],
            "stats": self.stats,
        }

    def summary(self, title: str = "part") -> str:
        icon = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "skip"}
        lines = [f"printcheck: {title}"]
        for c in self.checks:
            lines.append(f"  [{icon[c.status]}] {c.name}: {c.message}")
        verdict = "OK" if self.ok else f"{len(self.errors)} error(s)"
        lines.append(f"  => {verdict}, {len(self.warnings)} warning(s)")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Small geometry helpers (numpy only)
# --------------------------------------------------------------------------
def _edge_stats(faces: np.ndarray) -> Tuple[int, int]:
    """Return (open_edges, non_manifold_edges) counts from triangle indices."""
    if len(faces) == 0:
        return 0, 0
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum())


def _components(faces: np.ndarray, n_vertices: int) -> np.ndarray:
    """Label each face with a connected-component id (union-find on vertices)."""
    parent = list(range(n_vertices))

    def find(a: int) -> int:
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:  # path compression
            parent[a], a = root, parent[a]
        return root

    edges = np.unique(np.sort(np.vstack([faces[:, [0, 1]], faces[:, [1, 2]]]), axis=1), axis=0)
    for a, b in edges.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(int(v)) for v in faces[:, 0]])
    _, labels = np.unique(roots, return_inverse=True)
    return labels.reshape(-1)


def _first_hits(origins: np.ndarray, dirs: np.ndarray, tris: np.ndarray, chunk: int = 16) -> np.ndarray:
    """Distance along each ray to the nearest triangle hit (inf when none).

    Vectorised Moller-Trumbore. Rays are processed in chunks to bound memory.
    """
    origins = np.asarray(origins, dtype=float)
    dirs = np.asarray(dirs, dtype=float)
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    out = np.full(len(origins), np.inf)
    # keep memory near 32 MB per temporary array
    chunk = max(1, min(chunk, int(1_300_000 // max(1, len(tris)))))
    for s in range(0, len(origins), chunk):
        o = origins[s:s + chunk, None, :]
        d = dirs[s:s + chunk, None, :]
        p = np.cross(d, e2[None, :, :])
        det = np.einsum("rfk,fk->rf", p, e1)
        valid = np.abs(det) > 1e-12
        inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
        tvec = o - v0[None, :, :]
        u = np.einsum("rfk,rfk->rf", tvec, p) * inv
        q = np.cross(tvec, e1[None, :, :])
        v = np.einsum("rfk,rfk->rf", np.broadcast_to(d, q.shape), q) * inv
        t = np.einsum("rfk,fk->rf", q, e2) * inv
        hit = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
        t = np.where(hit, t, np.inf)
        out[s:s + chunk] = t.min(axis=1)
    return out


def _count_hits(origin: np.ndarray, direction: np.ndarray, tris: np.ndarray) -> int:
    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    p = np.cross(direction, e2)
    det = np.einsum("fk,fk->f", p, e1)
    valid = np.abs(det) > 1e-12
    inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
    tvec = origin - v0
    u = np.einsum("fk,fk->f", tvec, p) * inv
    q = np.cross(tvec, e1)
    v = (q @ direction) * inv
    t = np.einsum("fk,fk->f", q, e2) * inv
    return int((valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)).sum())


def point_inside(mesh, point: Sequence[float]) -> bool:
    """Ray-parity inside test, majority vote over three skewed directions."""
    tris = np.asarray(mesh.triangles, dtype=float)
    o = np.asarray(point, dtype=float)
    dirs = np.array([[0.0123, 0.0271, 1.0], [1.0, 0.0173, 0.0311], [-0.0219, 1.0, -0.0137]])
    votes = 0
    for d in dirs:
        d = d / np.linalg.norm(d)
        votes += _count_hits(o, d, tris) % 2
    return votes >= 2


def parse_bed(text: str) -> Tuple[float, float, float]:
    m = BED_RE.fullmatch(text or "")
    if not m:
        raise ValueError(f"bed must look like 220x220x250 (mm), got {text!r}")
    dims = tuple(float(g) for g in m.groups())
    if not all(10 <= d <= 3000 for d in dims):
        raise ValueError("bed dimensions must be between 10 and 3000 mm")
    return dims  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------
def _flat_regions(mesh, mask: np.ndarray) -> List[np.ndarray]:
    """Group the faces in `mask` into edge-connected regions."""
    idx = np.nonzero(mask)[0]
    if len(idx) == 0:
        return []
    parent = {int(i): int(i) for i in idx}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    adj = mesh.face_adjacency
    both = mask[adj[:, 0]] & mask[adj[:, 1]]
    for a, b in adj[both].tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups = {}
    for i in idx.tolist():
        groups.setdefault(find(i), []).append(i)
    return [np.array(g) for g in groups.values()]


def _classify_bridges(mesh, flat_mask, max_bridge):
    """Split flat ceilings into bridges (held at both ends, short span) and the rest.

    A region counts as a bridge when at least 60 % of its outline joins faces
    that go down from it (walls holding both ends) and its narrowest span is
    at most `max_bridge` mm. A cantilever (a T arm) fails the first test.
    """
    bridges = np.zeros(len(mesh.faces), dtype=bool)
    info = []
    adj = mesh.face_adjacency
    adj_edges = mesh.face_adjacency_edges
    centers_z = mesh.triangles_center[:, 2]
    verts = mesh.vertices
    for region in _flat_regions(mesh, flat_mask):
        in_region = np.zeros(len(mesh.faces), dtype=bool)
        in_region[region] = True
        cross = in_region[adj[:, 0]] ^ in_region[adj[:, 1]]
        if not cross.any():
            continue
        pairs = adj[cross]
        other = np.where(in_region[pairs[:, 0]], pairs[:, 1], pairs[:, 0])
        e = adj_edges[cross]
        lengths = np.linalg.norm(verts[e[:, 0]] - verts[e[:, 1]], axis=1)
        z = float(centers_z[region].mean())
        below = centers_z[other] < z - 1e-4
        supported = float(lengths[below].sum() / max(lengths.sum(), 1e-9))
        tris = [Polygon(t[:, :2]) for t in mesh.triangles[region]]
        shape = shapely.union_all([t for t in tris if t.area > 1e-9])
        try:
            span = 2.0 * shapely.maximum_inscribed_circle(shape, 0.05).length
        except Exception:
            span = float("inf")
        is_bridge = supported >= 0.6 and span <= max_bridge
        if is_bridge:
            bridges[region] = True
        if len(info) < 10:
            info.append({"z": round(z, 2), "span_mm": round(span, 2), "supported_outline": round(supported, 2),
                         "area_mm2": round(float(mesh.area_faces[region].sum()), 2), "bridge": bool(is_bridge)})
    return bridges, info


def _check_overhang(mesh, zmin, z_tol, overhang_deg, supports, ignore_mm2, max_bridge):
    n = mesh.face_normals
    area = mesh.area_faces
    nz = np.clip(n[:, 2], -1.0, 1.0)
    angle = np.degrees(np.arcsin(np.clip(-nz, -1.0, 1.0)))  # 0 = vertical wall, 90 = flat ceiling
    tri_z = mesh.triangles[:, :, 2]
    on_bed = (nz < -0.999) & (tri_z.max(axis=1) <= zmin + z_tol)
    steep = (nz < 0) & (angle > overhang_deg + 0.5) & ~on_bed
    flat = steep & (angle > 89.0)
    bridges, bridge_info = _classify_bridges(mesh, flat, max_bridge) if flat.any() else (np.zeros_like(flat), [])
    bridge_area = float(area[bridges].sum())
    steep = steep & ~bridges
    flat = flat & ~bridges
    steep_area = float(area[steep].sum())
    flat_area = float(area[flat].sum())
    data = {
        "limit_deg": overhang_deg,
        "area_mm2": round(steep_area, 2),
        "flat_ceiling_area_mm2": round(flat_area, 2),
        "bridge_area_mm2": round(bridge_area, 2),
        "max_bridge_mm": max_bridge,
        "flat_regions": bridge_info,
        "faces": int(steep.sum()),
    }
    if steep.any():
        pts = mesh.triangles[steep].reshape(-1, 3)
        data["bbox_min"] = [round(float(v), 2) for v in pts.min(axis=0)]
        data["bbox_max"] = [round(float(v), 2) for v in pts.max(axis=0)]
        # the z levels that carry most of the overhang area, to point at the culprit
        zc = np.round(mesh.triangles_center[steep][:, 2], 1)
        levels = {}
        for z, a in zip(zc.tolist(), area[steep].tolist()):
            levels[z] = levels.get(z, 0.0) + a
        top = sorted(levels.items(), key=lambda kv: -kv[1])[:5]
        data["main_z_levels"] = [{"z": z, "area_mm2": round(a, 2)} for z, a in top]
    bridge_note = f"; {bridge_area:.1f} mm2 short bridges (<= {max_bridge:g} mm span) left to the slicer" \
        if bridge_area > 0 else ""
    if steep_area < ignore_mm2:
        return Check("overhang", PASS,
                     f"no overhang steeper than {overhang_deg:g} deg (beyond {ignore_mm2:g} mm2){bridge_note}", data)
    msg = (f"{steep_area:.1f} mm2 of downward faces steeper than {overhang_deg:g} deg "
           f"({flat_area:.1f} mm2 of it flat, not a short bridge){bridge_note}")
    if supports:
        return Check("overhang", WARN, msg + "; supports needed or redesign (chamfer, teardrop, split)", data)
    return Check("overhang", FAIL, msg + "; supports are not allowed for this part", data)


def _section_holes(mesh, axis: int, positions: Iterable[float]):
    """Find holes in planar sections perpendicular to `axis`."""
    other = [i for i in range(3) if i != axis]
    normal = np.zeros(3)
    normal[axis] = 1.0
    found = []
    for pos in positions:
        origin = np.zeros(3)
        origin[axis] = pos
        try:
            segs = trimesh.intersections.mesh_plane(mesh, normal, origin)
        except Exception:
            continue
        if len(segs) < 3:
            continue
        lines = [tuple(map(tuple, np.round(s[:, other], 5))) for s in segs]
        lines = [ln for ln in lines if ln[0] != ln[1]]
        if not lines:
            continue
        try:
            area = shapely.build_area(shapely.set_precision(MultiLineString(lines), 1e-4))
        except Exception:
            continue
        polys = getattr(area, "geoms", [area])
        for poly in polys:
            if not isinstance(poly, Polygon) or poly.is_empty:
                continue
            for ring in poly.interiors:
                hole = Polygon(ring)
                if hole.area < 1e-3:
                    continue
                try:
                    radius = shapely.maximum_inscribed_circle(hole, 0.01).length
                except Exception:
                    radius = 2.0 * hole.area / max(hole.length, 1e-9)
                c = hole.centroid
                center = [0.0, 0.0, 0.0]
                center[axis] = float(pos)
                center[other[0]] = float(c.x)
                center[other[1]] = float(c.y)
                found.append({
                    "axis": "xyz"[axis],
                    "min_width_mm": round(2.0 * radius, 2),
                    "center": [round(v, 2) for v in center],
                })
    return found


def _check_holes(mesh, min_hole_d):
    lo, hi = mesh.bounds
    holes = []
    for axis in range(3):
        span = hi[axis] - lo[axis]
        if span <= 0:
            continue
        positions = [lo[axis] + f * span for f in (0.11, 0.3, 0.5, 0.7, 0.89)]
        holes.extend(_section_holes(mesh, axis, positions))
    # de-duplicate: same axis and centre (ignoring the section coordinate); keep the narrowest
    uniq = {}
    for h in holes:
        ax = "xyz".index(h["axis"])
        key = (h["axis"],) + tuple(round(h["center"][i] * 2) / 2 for i in range(3) if i != ax)
        if key not in uniq or h["min_width_mm"] < uniq[key]["min_width_mm"]:
            uniq[key] = h
    holes = sorted(uniq.values(), key=lambda h: h["min_width_mm"])
    small = [h for h in holes if h["min_width_mm"] < min_hole_d]
    horizontal = [h for h in holes if h["axis"] != "z"]
    data = {"min_hole_mm": min_hole_d, "holes_found": len(holes), "small": small[:20],
            "horizontal": horizontal[:20], "all": holes[:40]}
    notes = []
    if horizontal:
        notes.append(f"{len(horizontal)} horizontal hole(s): use a teardrop or accept a rough top")
    if small:
        return Check("small_holes", WARN,
                     f"{len(small)} hole(s) narrower than {min_hole_d:g} mm: they print undersize, "
                     "compensate or drill out" + ("; " + notes[0] if notes else ""), data)
    msg = f"{len(holes)} hole(s) found, none narrower than {min_hole_d:g} mm"
    if notes:
        msg += "; " + notes[0]
    return Check("small_holes", PASS, msg, data)


def _check_thin_walls(mesh, nozzle, samples, seed):
    limit = 2.0 * nozzle
    pts, face_idx = trimesh.sample.sample_surface(mesh, samples, seed=seed)
    normals = mesh.face_normals[face_idx]
    eps = 1e-3
    dist = _first_hits(pts - normals * eps, -normals, np.asarray(mesh.triangles, dtype=float)) + eps
    finite = np.isfinite(dist)
    thin = finite & (dist < limit - 1e-6)
    data = {"limit_mm": limit, "samples": int(samples), "measured": int(finite.sum()),
            "thin_samples": int(thin.sum())}
    if finite.any():
        data["min_thickness_mm"] = round(float(dist[finite].min()), 3)
    if thin.any():
        order = np.argsort(dist[thin])[:5]
        data["thin_points"] = [[round(float(v), 2) for v in p] for p in pts[thin][order]]
        return Check("thin_walls", WARN,
                     f"{int(thin.sum())}/{int(finite.sum())} samples thinner than {limit:g} mm "
                     f"(2 x nozzle), thinnest {data['min_thickness_mm']} mm", data)
    return Check("thin_walls", PASS, f"no sampled wall thinner than {limit:g} mm (2 x nozzle)", data)


def _check_layers(mesh, layer, zmin, z_tol):
    nz = mesh.face_normals[:, 2]
    flat = np.abs(nz) > 0.999
    if not flat.any():
        return Check("layer_alignment", PASS, "no flat faces to align", {})
    z = np.round(mesh.triangles_center[flat][:, 2] - zmin, 3)
    areas = mesh.area_faces[flat]
    level_area = {}
    for zi, ai in zip(z.tolist(), areas.tolist()):
        level_area[zi] = level_area.get(zi, 0.0) + ai
    # ignore specks: near-flat facets of curved surfaces are not features
    levels = np.array(sorted(lv for lv, a in level_area.items() if lv > z_tol and a >= 1.0))
    off = []
    for lv in levels.tolist():
        k = round(lv / layer)
        if abs(lv - k * layer) > 0.01:
            off.append(round(lv, 3))
    data = {"layer_mm": layer, "levels_checked": int(len(levels)), "off_grid_levels": off[:12]}
    if off:
        return Check("layer_alignment", WARN,
                     f"{len(off)} flat face level(s) not on a {layer:g} mm layer boundary "
                     f"(e.g. z={off[0]}): the slicer will round them", data)
    return Check("layer_alignment", PASS, f"all flat faces sit on {layer:g} mm layer boundaries", data)


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------
def check_printable(
    mesh,
    bed: Sequence[float] = (220.0, 220.0, 250.0),
    layer: float = 0.2,
    nozzle: float = 0.4,
    overhang_deg: float = 45.0,
    expected_bodies: Optional[int] = 1,
    margin: float = 5.0,
    z_tol: float = 0.01,
    min_contact_mm2: float = 10.0,
    supports: bool = True,
    min_hole_d: float = 3.0,
    overhang_ignore_mm2: float = 1.0,
    max_bridge: float = 10.0,
    thin_wall_samples: int = 0,
    probes_inside: Sequence[Sequence[float]] = (),
    probes_outside: Sequence[Sequence[float]] = (),
    seed: int = 0,
) -> CheckResult:
    """Run every check on a trimesh.Trimesh and return a CheckResult.

    Errors (status "fail") mean: do not export or print this as it is.
    Warnings mean: read them, decide, and say so in the print sheet.
    """
    if trimesh is None or shapely is None:
        raise RuntimeError("printcheck needs numpy, trimesh and shapely (pip install -r requirements.txt)")
    for label, value in (("layer", layer), ("nozzle", nozzle)):
        if not (0.01 <= float(value) <= 3.0):
            raise ValueError(f"{label} must be between 0.01 and 3 mm")
    if not (0.0 < float(overhang_deg) < 90.0):
        raise ValueError("overhang_deg must be between 0 and 90")
    bed = tuple(float(b) for b in bed)
    if len(bed) != 3:
        raise ValueError("bed must have 3 values (x, y, z)")

    checks: List[Check] = []
    faces = np.asarray(mesh.faces)
    stats = {"triangles": int(len(faces)), "vertices": int(len(mesh.vertices))}
    if len(faces) == 0:
        checks.append(Check("mesh", FAIL, "the mesh is empty", {}))
        return CheckResult(checks, stats)

    lo, hi = (np.asarray(b, dtype=float) for b in mesh.bounds)
    size = hi - lo
    stats.update({
        "bbox_min": [round(float(v), 3) for v in lo],
        "bbox_max": [round(float(v), 3) for v in hi],
        "size": [round(float(v), 3) for v in size],
        "surface_area_mm2": round(float(mesh.area), 2),
    })

    # units sanity -----------------------------------------------------------
    biggest = float(size.max())
    if biggest < 1.0:
        checks.append(Check("units", WARN, f"largest dimension is {biggest:.3f} mm: exported in metres or cm?", {}))
    elif biggest > 2000.0:
        checks.append(Check("units", WARN, f"largest dimension is {biggest:.0f} mm: exported in microns or wrong scale?", {}))
    else:
        checks.append(Check("units", PASS, f"size {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm", {}))

    # watertight + winding --------------------------------------------------
    open_edges, nonmanifold = _edge_stats(faces)
    watertight = bool(mesh.is_watertight) and open_edges == 0 and nonmanifold == 0
    winding = bool(mesh.is_winding_consistent)
    wdata = {"open_edges": open_edges, "non_manifold_edges": nonmanifold, "winding_consistent": winding}
    if watertight and winding:
        checks.append(Check("watertight", PASS, "closed surface with consistent winding", wdata))
    else:
        problems = []
        if open_edges:
            problems.append(f"{open_edges} open edge(s)")
        if nonmanifold:
            problems.append(f"{nonmanifold} non-manifold edge(s)")
        if not winding:
            problems.append("inconsistent face winding")
        if not problems:
            problems.append("not watertight")
        checks.append(Check("watertight", FAIL, ", ".join(problems) + ": repair the model before slicing", wdata))

    # volume ----------------------------------------------------------------
    volume = float(mesh.volume) if watertight else float("nan")
    stats["volume_mm3"] = round(volume, 3) if watertight else None
    if not watertight:
        checks.append(Check("volume", SKIP, "skipped: volume is undefined for an open mesh", {}))
    elif volume > 1e-6:
        checks.append(Check("volume", PASS, f"{volume:.1f} mm3", {"volume_mm3": round(volume, 3)}))
    else:
        checks.append(Check("volume", FAIL, f"volume is {volume:.3f} mm3: inverted normals or empty solid", {}))

    # bodies ----------------------------------------------------------------
    labels = _components(faces, len(mesh.vertices))
    n_bodies = int(labels.max()) + 1
    stats["bodies"] = n_bodies
    body_zmin = [float(mesh.triangles[labels == k][:, :, 2].min()) for k in range(n_bodies)]
    bdata = {"bodies": n_bodies, "expected": expected_bodies}
    if expected_bodies is None:
        checks.append(Check("bodies", PASS, f"{n_bodies} separate bod{'y' if n_bodies == 1 else 'ies'}", bdata))
    elif n_bodies == int(expected_bodies):
        checks.append(Check("bodies", PASS, f"{n_bodies} bod{'y' if n_bodies == 1 else 'ies'} as expected", bdata))
    else:
        checks.append(Check("bodies", FAIL,
                            f"{n_bodies} separate bodies, expected {expected_bodies}: "
                            "a loose piece or a union that did not merge", bdata))

    # sits on bed -----------------------------------------------------------
    zmin = float(lo[2])
    nz = mesh.face_normals[:, 2]
    tri_z = mesh.triangles[:, :, 2]
    contact = (nz < -0.999) & (tri_z.max(axis=1) <= zmin + z_tol)
    contact_area = float(mesh.area_faces[contact].sum())
    floating = [k for k, z in enumerate(body_zmin) if z > zmin + z_tol]
    sdata = {"min_z": round(zmin, 4), "contact_area_mm2": round(contact_area, 2),
             "min_contact_mm2": min_contact_mm2, "floating_bodies": floating}
    if abs(zmin) > z_tol:
        checks.append(Check("on_bed", FAIL, f"lowest point is z = {zmin:.3f} mm, not 0: move the part onto the bed", sdata))
    elif contact_area < min_contact_mm2:
        checks.append(Check("on_bed", FAIL,
                            f"only {contact_area:.1f} mm2 flat on the bed (minimum {min_contact_mm2:g}): "
                            "add a flat base or reorient", sdata))
    elif floating:
        checks.append(Check("on_bed", FAIL, f"{len(floating)} body(ies) do not touch the bed", sdata))
    else:
        msg = f"{contact_area:.1f} mm2 flat contact on the bed"
        status = PASS
        if size[2] > 6.0 * math.sqrt(contact_area):
            status = WARN
            msg += "; tall and narrow, consider a brim or a wider base"
        checks.append(Check("on_bed", status, msg, sdata))

    # build volume ----------------------------------------------------------
    bx, by, bz = bed
    fits = size[0] + 2 * margin <= bx and size[1] + 2 * margin <= by
    fits_rot = size[1] + 2 * margin <= bx and size[0] + 2 * margin <= by
    fits_z = size[2] <= bz
    vdata = {"bed": list(bed), "margin": margin}
    if fits and fits_z:
        checks.append(Check("build_volume", PASS, f"fits {bx:g} x {by:g} x {bz:g} with {margin:g} mm margin", vdata))
    elif fits_rot and fits_z:
        checks.append(Check("build_volume", WARN, "fits only rotated 90 degrees about Z: rotate it in the slicer", vdata))
    else:
        why = []
        if not (fits or fits_rot):
            why.append(f"footprint {size[0]:.1f} x {size[1]:.1f} + {margin:g} mm margin > bed {bx:g} x {by:g}")
        if not fits_z:
            why.append(f"height {size[2]:.1f} > {bz:g}")
        checks.append(Check("build_volume", FAIL, "; ".join(why) + ": split the part or scale the design", vdata))

    # overhangs -------------------------------------------------------------
    checks.append(_check_overhang(mesh, zmin, z_tol, overhang_deg, supports, overhang_ignore_mm2, max_bridge))

    # layer alignment -------------------------------------------------------
    checks.append(_check_layers(mesh, layer, zmin, z_tol))

    # small holes -----------------------------------------------------------
    if watertight:
        checks.append(_check_holes(mesh, min_hole_d))
    else:
        checks.append(Check("small_holes", SKIP, "skipped: needs a closed mesh", {}))

    # thin walls ------------------------------------------------------------
    if thin_wall_samples and watertight:
        checks.append(_check_thin_walls(mesh, nozzle, int(thin_wall_samples), seed))
    elif thin_wall_samples:
        checks.append(Check("thin_walls", SKIP, "skipped: needs a closed mesh", {}))

    # probes (handedness and key features) ---------------------------------
    if probes_inside or probes_outside:
        if not watertight:
            checks.append(Check("probes", SKIP, "skipped: needs a closed mesh", {}))
        else:
            bad = []
            for p in probes_inside:
                if not point_inside(mesh, p):
                    bad.append({"point": list(map(float, p)), "expected": "solid"})
            for p in probes_outside:
                if point_inside(mesh, p):
                    bad.append({"point": list(map(float, p)), "expected": "empty"})
            pdata = {"inside": [list(map(float, p)) for p in probes_inside],
                     "outside": [list(map(float, p)) for p in probes_outside], "failed": bad}
            total = len(probes_inside) + len(probes_outside)
            if bad:
                checks.append(Check("probes", FAIL,
                                    f"{len(bad)}/{total} probe point(s) wrong: mirrored (wrong hand) "
                                    "or a feature moved", pdata))
            else:
                checks.append(Check("probes", PASS, f"{total} probe point(s) solid/empty as expected", pdata))

    return CheckResult(checks, stats)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def load_stl(path: str):
    if trimesh is None:
        raise RuntimeError("printcheck needs trimesh (pip install -r requirements.txt)")
    if not path.lower().endswith(".stl"):
        raise ValueError("only .stl files are accepted")
    if not os.path.isfile(path):
        raise ValueError(f"not a file: {path}")
    if os.path.getsize(path) > MAX_STL_BYTES:
        raise ValueError(f"file larger than {MAX_STL_BYTES // (1024 * 1024)} MB, refusing")
    mesh = trimesh.load(path, file_type="stl", force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("could not read a single mesh from the file")
    return mesh


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Pre-flight checks for an FDM part (STL, millimetres, Z up).")
    ap.add_argument("stl", help="path to an .stl file")
    ap.add_argument("--bed", default="220x220x250", help="build volume X x Y x Z in mm (default 220x220x250)")
    ap.add_argument("--layer", type=float, default=0.2, help="layer height in mm (default 0.2)")
    ap.add_argument("--nozzle", type=float, default=0.4, help="nozzle diameter in mm (default 0.4)")
    ap.add_argument("--overhang", type=float, default=45.0, help="overhang limit in degrees from vertical (default 45)")
    ap.add_argument("--bodies", type=int, default=None, help="expected number of separate bodies (default: report only)")
    ap.add_argument("--margin", type=float, default=5.0, help="free margin around the part on the bed, mm (default 5)")
    ap.add_argument("--min-contact", type=float, default=10.0, help="minimum flat area on the bed, mm2 (default 10)")
    ap.add_argument("--min-hole", type=float, default=3.0, help="warn for holes narrower than this, mm (default 3)")
    ap.add_argument("--max-bridge", type=float, default=10.0, help="flat ceilings held at both ends up to this span are bridges, mm (default 10)")
    ap.add_argument("--no-supports", action="store_true", help="treat overhangs as errors")
    ap.add_argument("--thin-walls", type=int, default=0, metavar="N", help="sample N surface points for thin walls")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args(argv)
    try:
        bed = parse_bed(args.bed)
        mesh = load_stl(args.stl)
        res = check_printable(
            mesh, bed=bed, layer=args.layer, nozzle=args.nozzle, overhang_deg=args.overhang,
            expected_bodies=args.bodies, margin=args.margin, min_contact_mm2=args.min_contact,
            supports=not args.no_supports, min_hole_d=args.min_hole, max_bridge=args.max_bridge,
            thin_wall_samples=args.thin_walls,
        )
    except (ValueError, RuntimeError) as exc:
        print(f"printcheck: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        print(res.summary(os.path.basename(args.stl)))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
