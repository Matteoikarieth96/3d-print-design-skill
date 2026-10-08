"""cad: small geometry helpers for FDM parts.

Conventions: millimetres, Z up, the finished part sits on z = 0 in its print
orientation. 2D outlines are shapely polygons; solids are manifold3d
Manifold objects (exact, always watertight booleans); export goes through
trimesh.

Only the helpers a typical bracket, clip, box or plate needs live here. Add
new ones in your project's build.py geometry block, not by editing this file,
so updates to the skill do not overwrite your work.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import manifold3d as m3
import numpy as np
import shapely
import shapely.affinity
import trimesh
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Per-side clearances (mm) used until you print the calibration coupon and
# record your own numbers in fits.json. See references/design-rules.md.
DEFAULT_FITS = {"press": 0.05, "snug": 0.10, "sliding": 0.20, "free": 0.30}

# Solid densities in g/cm3 for the mass estimate (100 % infill upper bound).
DENSITY_G_CM3 = {"PLA": 1.24, "PETG": 1.27, "TPU": 1.21, "ABS": 1.04, "ASA": 1.07}

EPS = 0.05  # cutters overshoot faces by this much so booleans never leave skins

Solid = m3.Manifold


# --------------------------------------------------------------------------
# Names, paths, fits
# --------------------------------------------------------------------------
def validate_name(name: str) -> str:
    """Return the name if it is a safe file stem, else raise ValueError."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid part name {name!r}: use 1-64 chars of a-z, 0-9 and '-', starting with a letter or digit")
    return name


def safe_out_dir(project_dir: Union[str, Path], out: Union[str, Path]) -> Path:
    """Resolve `out` relative to the project folder and refuse anything outside it."""
    project = Path(project_dir).resolve()
    target = (project / out).resolve()
    if target != project and project not in target.parents:
        raise ValueError(f"output folder {target} is outside the project folder {project}")
    return target


def load_fits(project_dir: Union[str, Path]) -> dict:
    """Read fits.json from the project folder (written after printing the coupon).

    Missing file: the generic defaults are used and `source` says so.
    Values are per-side clearances in mm and must be between 0 and 1.
    """
    fits = dict(DEFAULT_FITS)
    fits["source"] = "defaults (print the calibration coupon to measure your printer)"
    path = Path(project_dir).resolve() / "fits.json"
    if not path.is_file():
        return fits
    data = json.loads(path.read_text(encoding="utf-8"))
    clear = data.get("clearance_per_side", {})
    if not isinstance(clear, dict):
        raise ValueError("fits.json: clearance_per_side must be an object")
    for key in DEFAULT_FITS:
        if key in clear:
            value = float(clear[key])
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"fits.json: {key} = {value} is outside 0..1 mm")
            fits[key] = value
    if "overhang_ok_deg" in data:
        value = float(data["overhang_ok_deg"])
        if not 20.0 <= value <= 75.0:
            raise ValueError("fits.json: overhang_ok_deg must be between 20 and 75")
        fits["overhang_ok_deg"] = value
    fits["source"] = f"fits.json ({str(data.get('printer', 'printer not named'))[:60]}, " \
                     f"{str(data.get('material', 'material not named'))[:20]})"
    return fits


def segments_for(d: float, chord: float = 0.4, lo: int = 24, hi: int = 180) -> int:
    """Number of polygon sides so each chord is about `chord` mm (one nozzle)."""
    n = int(math.ceil(math.pi * max(d, 0.1) / chord))
    n = max(lo, min(hi, n))
    return n + (-n % 4)  # multiple of 4 so flats line up with the axes


def poly_radius(d: float, n: int) -> float:
    """Circumradius of an n-gon whose flats are at d/2 (a hole that is at least d)."""
    return (d / 2.0) / math.cos(math.pi / n)


# --------------------------------------------------------------------------
# 2D outlines (shapely)
# --------------------------------------------------------------------------
def rect(w: float, h: float, center: bool = True) -> Polygon:
    if center:
        return shapely.box(-w / 2, -h / 2, w / 2, h / 2)
    return shapely.box(0, 0, w, h)


def rounded_rect(w: float, h: float, r: float) -> Polygon:
    """Centred rectangle with corner radius r (r = 0 gives sharp corners)."""
    r = max(0.0, min(r, w / 2 - 1e-3, h / 2 - 1e-3))
    if r <= 0:
        return rect(w, h)
    core = rect(w - 2 * r, h - 2 * r)
    return core.buffer(r, quad_segs=max(4, segments_for(2 * r) // 4))


def box2d(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """Axis-aligned rectangle from corner (x0, y0) to corner (x1, y1)."""
    return shapely.box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def translate2d(shape, x: float = 0.0, y: float = 0.0):
    return shapely.affinity.translate(shape, xoff=x, yoff=y)


def mirror2d(shape, axis: str = "x"):
    """Mirror a 2D outline across the Y axis (axis='x' flips X) or the X axis."""
    fx, fy = (-1.0, 1.0) if axis == "x" else (1.0, -1.0)
    return shapely.affinity.scale(shape, xfact=fx, yfact=fy, origin=(0, 0))


def circle2d(d: float, n: Optional[int] = None, x: float = 0.0, y: float = 0.0) -> Polygon:
    n = n or segments_for(d)
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return Polygon(np.c_[x + d / 2 * np.cos(a), y + d / 2 * np.sin(a)])


def teardrop2d(d: float, n: Optional[int] = None, flat_top: bool = True, angle: float = 45.0) -> Polygon:
    """Circle with a pointed (or flat-topped) roof toward +Y.

    Rotated so +Y becomes +Z, it makes a horizontal hole whose ceiling never
    exceeds `angle` from vertical. flat_top cuts the tip at the circle top so
    the bridge is only a few millimetres.
    """
    if not 20.0 <= angle <= 70.0:
        raise ValueError("teardrop roof angle must be between 20 and 70 degrees from vertical")
    n = n or segments_for(d)
    r = poly_radius(d, n)
    # the roof lines are tangent to the circle at polar angles `angle` and 180 - angle;
    # put vertices exactly there so no facet between them pokes out steeper than the roof
    a = math.radians(angle)
    sweep = math.pi + 2 * a                       # from 180 - angle round the bottom to 360 + angle
    k = max(8, int(math.ceil(n * sweep / (2 * math.pi))))
    polar = np.linspace(math.pi - a, 2 * math.pi + a, k + 1)
    pts = [(r * math.cos(t), r * math.sin(t)) for t in polar]
    tip_y = r / math.sin(a)
    if flat_top and tip_y > r:
        half = (tip_y - r) * math.tan(a)
        pts += [(half, r), (-half, r)]
    else:
        pts.append((0.0, tip_y))
    return Polygon(pts)


# --------------------------------------------------------------------------
# 2D -> 3D
# --------------------------------------------------------------------------
def _rings(poly: Polygon) -> List[np.ndarray]:
    poly = orient(poly, sign=1.0)  # exterior CCW, holes CW: solid always on the left
    rings = [np.asarray(poly.exterior.coords, dtype=float)[:-1]]
    rings += [np.asarray(r.coords, dtype=float)[:-1] for r in poly.interiors]
    return rings


def _polys(shape) -> List[Polygon]:
    if isinstance(shape, Polygon):
        return [shape]
    if isinstance(shape, MultiPolygon):
        return list(shape.geoms)
    raise TypeError("expected a shapely Polygon or MultiPolygon")


def cross_section(shape) -> m3.CrossSection:
    contours = []
    for p in _polys(shape):
        contours.extend(_rings(p))
    return m3.CrossSection(contours, m3.FillRule.Positive)


def extrude(shape, height: float, z0: float = 0.0) -> Solid:
    """Straight extrusion of a 2D outline from z0 to z0 + height."""
    return m3.Manifold.extrude(cross_section(shape), float(height)).translate((0.0, 0.0, float(z0)))


def _mitre_inset(ring: np.ndarray, c: float) -> np.ndarray:
    """Move every vertex of a ring (solid on the left) inward by c with mitred corners."""
    prev_pt = np.roll(ring, 1, axis=0)
    next_pt = np.roll(ring, -1, axis=0)
    d1 = ring - prev_pt
    d2 = next_pt - ring
    d1 /= np.linalg.norm(d1, axis=1, keepdims=True)
    d2 /= np.linalg.norm(d2, axis=1, keepdims=True)
    n1 = np.c_[-d1[:, 1], d1[:, 0]]  # left normals = into the solid
    n2 = np.c_[-d2[:, 1], d2[:, 0]]
    denom = 1.0 + np.einsum("ij,ij->i", n1, n2)
    denom = np.where(denom < 1e-6, 1e-6, denom)
    return ring + c * (n1 + n2) / denom[:, None]


def chamfered_extrude(shape, height: float, bottom: float = 0.0, top: float = 0.0, z0: float = 0.0) -> Solid:
    """Extrude with 45 degree chamfers on the bottom and/or top outline edges.

    A 0.3 to 0.5 mm bottom chamfer hides elephant foot (first layer squish).
    A 45 degree chamfer is the steepest underside FDM prints cleanly, so it
    never needs support. Works for non-convex outlines with holes as long as
    the chamfer is smaller than half the narrowest feature.
    """
    bottom, top = float(bottom), float(top)
    if bottom < 0 or top < 0 or bottom + top >= height:
        raise ValueError("chamfers must be >= 0 and smaller than the height together")
    if bottom == 0 and top == 0:
        return extrude(shape, height, z0)
    parts = []
    for poly in _polys(shape):
        parts.append(_loft_polygon(poly, height, bottom, top))
    return union(*parts).translate((0.0, 0.0, float(z0)))


def _loft_polygon(poly: Polygon, height: float, bottom: float, top: float) -> Solid:
    rings = _rings(poly)
    levels: List[Tuple[float, float]] = []  # (z, inset)
    if bottom > 0:
        levels.append((0.0, bottom))
    levels.append((bottom, 0.0))
    levels.append((height - top, 0.0))
    if top > 0:
        levels.append((height, top))
    # inset rings must keep every edge direction, otherwise the chamfer is too big
    for _, inset in levels:
        if inset <= 0:
            continue
        for ring in rings:
            moved = _mitre_inset(ring, inset)
            e0 = np.roll(ring, -1, axis=0) - ring
            e1 = np.roll(moved, -1, axis=0) - moved
            if np.any(np.einsum("ij,ij->i", e0, e1) <= 0):
                raise ValueError(f"chamfer {inset} mm is too large for this outline (a feature collapses)")
    verts: List[np.ndarray] = []
    level_index: List[List[np.ndarray]] = []
    count = 0
    for z, inset in levels:
        per_ring = []
        for ring in rings:
            pts = _mitre_inset(ring, inset) if inset > 0 else ring
            verts.append(np.c_[pts, np.full(len(pts), z)])
            per_ring.append(np.arange(count, count + len(pts)))
            count += len(pts)
        level_index.append(per_ring)
    vertices = np.vstack(verts)
    tris: List[np.ndarray] = []
    # caps: manifold's triangulator indexes the concatenated ring points in order
    cap = np.asarray(m3.triangulate([r for r in (vertices[i][:, :2] for i in level_index[0])]), dtype=np.int64)
    flat0 = np.concatenate(level_index[0])
    tris.append(flat0[cap][:, ::-1])  # bottom faces down
    cap_t = np.asarray(m3.triangulate([vertices[i][:, :2] for i in level_index[-1]]), dtype=np.int64)
    flat1 = np.concatenate(level_index[-1])
    tris.append(flat1[cap_t])
    # side walls between consecutive levels
    for lv in range(len(levels) - 1):
        for a, b in zip(level_index[lv], level_index[lv + 1]):
            a1 = np.roll(a, -1)
            b1 = np.roll(b, -1)
            tris.append(np.c_[a, a1, b1])
            tris.append(np.c_[a, b1, b])
    faces = np.vstack(tris).astype(np.uint64)
    mesh = m3.Mesh64(vert_properties=np.ascontiguousarray(vertices, dtype=np.float64),
                     tri_verts=np.ascontiguousarray(faces))
    solid = m3.Manifold(mesh)
    if solid.status() != m3.Error.NoError or solid.volume() <= 0:
        raise ValueError(f"chamfered extrusion failed ({solid.status()}); try a smaller chamfer")
    return solid


# --------------------------------------------------------------------------
# 3D primitives (all sit on z = 0 unless moved)
# --------------------------------------------------------------------------
def box(x: float, y: float, z: float, center_xy: bool = True) -> Solid:
    b = m3.Manifold.cube((float(x), float(y), float(z)))
    return b.translate((-x / 2, -y / 2, 0.0)) if center_xy else b


def cylinder(d: float, h: float, n: Optional[int] = None, d_top: Optional[float] = None) -> Solid:
    """Cylinder (or cone with d_top) on z = 0, centred on the Z axis."""
    n = n or segments_for(max(d, d_top or 0))
    r_top = -1.0 if d_top is None else d_top / 2
    return m3.Manifold.cylinder(float(h), d / 2, r_top, n)


def hole(d: float, depth: float, z_top: float, n: Optional[int] = None,
         foot: float = 0.0, lead_in: float = 0.0, through: bool = True) -> Solid:
    """Vertical round hole cutter whose flats are at least d (polygon compensated).

    `foot` widens the bottom by that much per side (cancels elephant foot that
    would make the hole tight at the first layer). `lead_in` adds a 45 degree
    chamfer at the top. The cutter overshoots by EPS above z_top and, when
    `through`, below z_top - depth.
    """
    n = n or segments_for(d)
    r = poly_radius(d, n)
    z0 = z_top - depth - (EPS if through else 0.0)
    parts = [m3.Manifold.cylinder(depth + EPS + (EPS if through else 0.0), r, r, n).translate((0, 0, z0))]
    if foot > 0:
        parts.append(m3.Manifold.cylinder(foot + EPS, r + foot + EPS, r - 1e-3, n).translate((0, 0, z_top - depth - EPS)))
    if lead_in > 0:
        parts.append(m3.Manifold.cylinder(lead_in + EPS, r, r + lead_in + EPS, n).translate((0, 0, z_top - lead_in)))
    return union(*parts)


def countersunk_cutter(d_clear: float, d_head: float, thickness: float,
                       angle: float = 90.0, n: Optional[int] = None, head_sink: float = 0.2) -> Solid:
    """Through hole + countersink for a flat-head screw entering from the top.

    The plate spans z = 0..thickness. `angle` is the included head angle (90
    for ISO metric flat heads, 82 for many imperial ones). `head_sink` puts the
    head that far below the surface so it never stands proud.
    """
    n = n or segments_for(d_head)
    r = poly_radius(d_clear, n)
    rh = poly_radius(d_head, n)
    cone_h = (rh - r) / math.tan(math.radians(angle / 2))
    if cone_h + head_sink >= thickness:
        raise ValueError("countersink deeper than the plate: thicken the plate or use a smaller head")
    shaft = m3.Manifold.cylinder(thickness + 2 * EPS, r, r, n).translate((0, 0, -EPS))
    z_cone = thickness - head_sink - cone_h
    cone = m3.Manifold.cylinder(cone_h, r, rh, n).translate((0, 0, z_cone))
    recess = m3.Manifold.cylinder(head_sink + EPS, rh, rh, n).translate((0, 0, thickness - head_sink))
    return union(shaft, cone, recess)


def counterbore_cutter(d_clear: float, d_head: float, head_h: float, thickness: float,
                       n: Optional[int] = None) -> Solid:
    """Through hole + flat-bottom pocket for a socket-head screw from the top."""
    n = n or segments_for(d_head)
    shaft = m3.Manifold.cylinder(thickness + 2 * EPS, poly_radius(d_clear, n), -1.0, n).translate((0, 0, -EPS))
    pocket = m3.Manifold.cylinder(head_h + EPS, poly_radius(d_head, n), -1.0, n).translate((0, 0, thickness - head_h))
    return union(shaft, pocket)


def insert_hole(d: float, depth: float, z_top: float, lead_in: float = 0.5, n: Optional[int] = None) -> Solid:
    """Blind hole for a heat-set insert, opening at z_top, with a lead-in chamfer.

    Take d and depth from the insert maker's table; see references/design-rules.md.
    """
    return hole(d, depth, z_top, n=n, lead_in=lead_in, through=False)


def teardrop_hole(d: float, length: float, axis: str = "x", flat_top: bool = True,
                  n: Optional[int] = None) -> Solid:
    """Horizontal hole cutter along X or Y, centred on the origin, roof pointing +Z."""
    prof = teardrop2d(d, n=n, flat_top=flat_top)
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y' (vertical holes do not need a teardrop)")
    solid = extrude(prof, length + 2 * EPS, z0=-(length / 2 + EPS))  # profile in XY, length along Z
    return _orient_teardrop(solid, axis)


def _orient_teardrop(solid: Solid, axis: str) -> Solid:
    # rotate +90 about X: (x, y, z) -> (x, -z, y): profile +Y becomes +Z, length runs along -Y
    s = solid.rotate((90.0, 0.0, 0.0))
    if axis == "y":
        return s
    # then -90 about Z sends the length from Y to X and keeps Z
    return s.rotate((0.0, 0.0, -90.0))


# --------------------------------------------------------------------------
# Booleans and transforms
# --------------------------------------------------------------------------
def union(*parts: Solid) -> Solid:
    parts = [p for p in parts if p is not None]
    if not parts:
        return m3.Manifold()
    return m3.Manifold.batch_boolean(list(parts), m3.OpType.Add)


def difference(base: Solid, *cutters: Solid) -> Solid:
    cutters = [c for c in cutters if c is not None]
    if not cutters:
        return base
    return m3.Manifold.batch_boolean([base] + list(cutters), m3.OpType.Subtract)


def intersection(*parts: Solid) -> Solid:
    return m3.Manifold.batch_boolean(list(parts), m3.OpType.Intersect)


def translate(solid: Solid, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Solid:
    return solid.translate((float(x), float(y), float(z)))


def rotate(solid: Solid, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Solid:
    """Rotate in degrees about the global X, then Y, then Z axes."""
    return solid.rotate((float(x), float(y), float(z)))


def mirror(solid: Solid, axis: str = "x") -> Solid:
    """Mirror across the plane through the origin normal to `axis`.

    This turns a left part into a right part. Lock the result with probe
    points (see references/design-rules.md, chirality) instead of trusting a
    glance at the viewer.
    """
    normal = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[axis]
    return solid.mirror(normal)


def stand_up(solid: Solid) -> Solid:
    """Turn a solid extruded along Z from an XY profile so the profile stands in XZ.

    Profile +Y becomes world +Z, the extrusion runs along Y, centred on y = 0.
    Use it to draw side profiles (clips, brackets, hooks) in 2D.
    """
    s = solid.rotate((90.0, 0.0, 0.0))  # (x, y, z) -> (x, -z, y)
    lo, hi = s.bounding_box()[:3], s.bounding_box()[3:]
    return s.translate((0.0, -(lo[1] + hi[1]) / 2, 0.0))


def drop_to_bed(solid: Solid) -> Solid:
    lo = solid.bounding_box()[:3]
    return solid.translate((0.0, 0.0, -lo[2]))


def bodies(solid: Solid) -> List[Solid]:
    return list(solid.decompose())


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------
def to_trimesh(solid: Solid) -> trimesh.Trimesh:
    if solid.is_empty():
        raise ValueError("the solid is empty: a difference removed everything or nothing was built")
    mesh = solid.to_mesh64()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64)
    return trimesh.Trimesh(vertices=verts, faces=faces, process=True)


def _jsonable(value):
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return None


def param_snapshot(namespace: dict) -> dict:
    """UPPER_CASE names with JSON-friendly values, for the metadata file."""
    out = {}
    for key, value in namespace.items():
        if key.isupper() and not key.startswith("_"):
            j = _jsonable(value)
            if j is not None or value is None:
                out[key] = j
    return out


def write_part(out_dir: Path, name: str, mesh: trimesh.Trimesh, check_result, *,
               material: str = "PLA", params: Optional[dict] = None,
               color: Optional[str] = None, bed: Optional[Sequence[float]] = None,
               extra: Optional[dict] = None) -> Tuple[Path, Path]:
    """Write out/<name>.stl (binary) and out/<name>.json (metadata). Returns both paths."""
    validate_name(name)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / f"{name}.stl"
    json_path = out_dir / f"{name}.json"
    data = mesh.export(file_type="stl")
    stl_path.write_bytes(data)
    density = DENSITY_G_CM3.get(material.upper(), DENSITY_G_CM3["PLA"])
    lo, hi = mesh.bounds
    volume = float(mesh.volume)
    meta = {
        "name": name,
        "units": "mm",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "generator": "3d-print-design build script",
        "stl": stl_path.name,
        "stl_sha256": hashlib.sha256(data).hexdigest(),
        "material": material,
        "density_g_cm3": density,
        "bbox": {"min": [round(float(v), 3) for v in lo], "max": [round(float(v), 3) for v in hi],
                 "size": [round(float(v), 3) for v in hi - lo]},
        "volume_mm3": round(volume, 2),
        "estimated_mass_g_solid": round(volume / 1000.0 * density, 2),
        "mass_note": "upper bound at 100 % infill; a slicer estimate with your infill will be lower",
        "triangles": int(len(mesh.faces)),
        "printcheck": check_result.to_dict() if check_result is not None else None,
        "parameters": params or {},
    }
    if color and HEX_COLOR_RE.fullmatch(color):
        meta["preview_color"] = color
    if bed:
        meta["printer_bed"] = [float(b) for b in bed]
    if extra:
        meta.update(_jsonable(extra))
    json_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return stl_path, json_path
