"""harness: what every build.py runs below its DO NOT EDIT line.

name check -> geometry -> printcheck (per part, then joined for colours) ->
estimate of filament and time -> STL + metadata -> hand-off for the printer
skill. With --variants it also builds every version listed in VARIANTS (each
in a fresh process, so vary() parameters are computed from scratch) and
prints a comparison table, so the person picks a version by time and
material before printing anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import assembly
import cad
import estimate as est
import printcheck
import printers
from safeio import atomic_write, safe_text

VARIANTS_FILE = "variants.json"


def _per_part(value, suffix):
    return value.get(suffix, value.get("", None)) if isinstance(value, dict) else value


def _refuse(msg) -> int:
    print(f"refusing: {safe_text(msg)}", file=sys.stderr)
    return 2


def _settings(g: dict) -> dict:
    """Print settings that drive time and material (defaults = Bambu 0.20mm Standard)."""
    return {
        "layer": float(g["LAYER"]),
        "walls": int(g.get("WALLS", 2)),
        "infill": float(g.get("INFILL", 15)),
        "top_layers": int(g.get("TOP_LAYERS", 5)),
        "bottom_layers": int(g.get("BOTTOM_LAYERS", 3)),
    }


def _variants(g: dict) -> dict:
    v = g.get("VARIANTS") or {}
    if not isinstance(v, dict):
        raise ValueError("VARIANTS must be a dict {name: what changes}")
    for name in v:
        cad.validate_name(name)
        if name == cad.BASE_VARIANT:
            raise ValueError(f"VARIANTS: '{cad.BASE_VARIANT}' is the base version, do not list it")
    unknown = cad.vary_names() - set(v)
    if unknown:
        raise ValueError(f"vary() names version(s) {', '.join(sorted(unknown))} that VARIANTS does not list")
    return v


def _about(g: dict, name: str, variants: dict) -> str:
    if name == cad.BASE_VARIANT:
        return str(g.get("STANDARD_ABOUT") or "the version as designed")
    return str(variants.get(name, ""))


def run(g: dict, argv=None, script: Path = None) -> int:
    ap = argparse.ArgumentParser(description=f"Build {g.get('NAME')} and check it before export.")
    ap.add_argument("--out", default="out", help="output folder inside the project folder (default out)")
    ap.add_argument("--check", action="store_true", help="run printcheck and the estimate only, write nothing")
    ap.add_argument("--variant", default=cad.BASE_VARIANT,
                    help="which version of VARIANTS to build (default standard)")
    ap.add_argument("--variants", action="store_true",
                    help="also build every version in VARIANTS into out/variants/ and compare them")
    ap.add_argument("--no-handoff", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--nozzle-plan", default=None, help=argparse.SUPPRESS)   # the chosen version's plan, for --variants
    ap.add_argument("--thin-walls", type=int, default=400, metavar="N",
                    help="surface samples for the thin wall check (0 to skip)")
    args = ap.parse_args(argv)
    project_dir = Path(script).resolve().parent
    try:
        name = cad.validate_name(g["NAME"])
        out_dir = cad.safe_out_dir(project_dir, args.out)
        profile = printers.get(g.get("PRINTER"))
        variants = _variants(g)
        if args.variant != cad.BASE_VARIANT and args.variant not in variants:
            raise ValueError(f"unknown version {args.variant!r}: VARIANTS lists "
                             f"{', '.join([cad.BASE_VARIANT, *variants]) or cad.BASE_VARIANT}")
        if args.variant != cad.selected_variant():
            raise ValueError("--variant must be on the command line of build.py (vary() reads it at start)")
    except ValueError as exc:
        return _refuse(exc)

    built = _build_one(g, args, name, out_dir, profile, project_dir, variants)
    if not isinstance(built, dict):
        return built
    if not args.variants:
        return _handoff(g, args, name, out_dir, profile, project_dir, built, None)

    rows = [{"name": args.variant, "about": _about(g, args.variant, variants), "estimate": built["estimate"],
             "ok": True, "dir": "."}]
    others = [v for v in [cad.BASE_VARIANT, *variants] if v != args.variant]
    for v in others:
        sub = f"{args.out}/variants/{v}"
        cmd = [sys.executable, "-P", str(Path(script).resolve()), "--variant", v, "--out", sub,
               "--thin-walls", str(args.thin_walls), "--no-handoff",
               "--nozzle-plan", json.dumps(built["nozzles"])] + (["--check"] if args.check else [])
        res = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True)
        row = {"name": v, "about": _about(g, v, variants), "ok": res.returncode == 0, "dir": f"variants/{v}"}
        summary = None
        for line in res.stdout.splitlines():
            if line.startswith("@@estimate "):
                summary = json.loads(line[len("@@estimate "):])
        if summary:
            row["estimate"] = summary["estimate"]
            row["parts"] = summary["parts"]
        else:
            print(f"version {v} failed:\n{safe_text(res.stdout[-1500:] + res.stderr[-1500:])}", file=sys.stderr)
        rows.append(row)
    material = g["MATERIAL"]
    text = est.table(rows, material)
    rough = any(r.get("estimate") and est.rough_text(r["estimate"]) for r in rows)
    print("\nVersions to compare (estimates before slicing; the slicer gives a closer figure"
          + ("; " + est.ROUGH_LABEL if rough else "") + "):\n" + text)
    if args.check:
        print("\ncheck only: nothing written")
        return 0
    scope = ("**" + est.ROUGH_LABEL + ".**\n\n" if rough else "")
    atomic_write(out_dir / "variants.md", "# Versions of " + name + "\n\n" + scope + text + "\n\nEstimates before "
                 "slicing. Measured field: Bambu Lab X2D, PLA, 0.4 mm nozzle, 0.2 mm layers, no supports, infill up "
                 "to 40 %; there every calibration and holdout slice fell inside the range shown. Outside it the "
                 "range is wider and marked rough. The slicer gives a closer figure. "
                 "Build one with `build.py --variant NAME`.\n")
    atomic_write(out_dir / VARIANTS_FILE, json.dumps({"chosen": args.variant, "versions": [
        {k: r.get(k) for k in ("name", "about", "ok", "dir", "estimate")} for r in rows]}, indent=2) + "\n")
    print(f"wrote {(out_dir / 'variants.md').relative_to(project_dir)}")
    return _handoff(g, args, name, out_dir, profile, project_dir, built, rows)


def _build_one(g, args, name, out_dir, profile, project_dir, variants):
    """Check, estimate and (unless --check) write the version this process was started for."""
    parts = g["build_part"]()
    if not isinstance(parts, dict):
        parts = {"": parts}
    together = bool(g.get("ASSEMBLY", False)) and len(parts) > 1
    colours = {sfx: str(_per_part(g.get("COLOUR_NAME"), sfx) or "") for sfx in parts}
    hexes = {sfx: _per_part(g.get("COLOR"), sfx) for sfx in parts}
    if together and (len(set(colours.values())) < len(parts) or len(set(map(str, hexes.values()))) < len(parts)):
        return _refuse(f"ASSEMBLY has {len(parts)} colour parts but COLOUR_NAME/COLOR do not give each its own "
                       "colour: set them as {suffix: value}, e.g. COLOUR_NAME = {'base': 'black', 'star': 'yellow'}")
    n_colours = len(set(colours.values())) if len(parts) > 1 else 1
    try:
        bed = printers.bed_for(profile, n_colours, g.get("PRINTER_BED"))
    except ValueError as exc:
        return _refuse(exc)
    results = []
    for suffix, solid in parts.items():
        try:
            part_name = name if not suffix else cad.validate_name(f"{name}-{suffix}")
        except ValueError as exc:
            return _refuse(exc)
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

    st = _settings(g)
    handoff = []
    vols = []
    for part_name, suffix, mesh, res in results:
        z0, z1 = float(mesh.bounds[0][2]), float(mesh.bounds[1][2])
        handoff.append({"stl": f"{part_name}.stl", "colour": colours[suffix], "colour_hex": hexes[suffix], "z": (z0, z1),
                        "layers": int(round((z1 - z0) / g["LAYER"])), "volume_mm3": float(mesh.volume)})
        mv = est.material_volume(mesh, layer=g["LAYER"], nozzle=g["NOZZLE"], walls=st["walls"],
                                 infill=st["infill"], top_layers=st["top_layers"], bottom_layers=st["bottom_layers"])
        mv["colour"] = colours[suffix]
        vols.append(mv)
    # colours that share layers anywhere on the plate (one object or several side by side)
    mix = printers.colour_layers([{"stl": h["stl"], "z": h["z"], "colour": h["colour"]} for h in handoff],
                                 g["LAYER"])
    external = bool(g.get("EXTERNAL_SPOOL", True))
    plans = (printers.nozzle_options(profile, handoff, g["MATERIAL"], mix.get("mixed_layers", 0), external)
             if profile["nozzles"] >= 2 else [])
    forced = json.loads(args.nozzle_plan) if args.nozzle_plan else None
    if isinstance(forced, dict) and set(colours.values()) <= set(forced):
        plans = [{"option": "chosen", "label": "the chosen version's nozzles",
                  "nozzles": {c: forced[c] for c in set(colours.values())}}]

    def run_estimate(nozzle_of, quantity=None):
        return est.estimate(vols, profile=profile["name"], material=g["MATERIAL"], layer=g["LAYER"],
                            quantity=int(g.get("QUANTITY", 1)) if quantity is None else quantity,
                            nozzle_of=nozzle_of,
                            supports=bool(g["SUPPORTS_ALLOWED"]), nozzle=g["NOZZLE"])

    options = []
    for plan in plans:
        pe = run_estimate(plan["nozzles"])
        options.append(dict(plan, minutes=pe["minutes"], grams=pe["grams"], estimate=pe))
    if options:
        # fastest plan; equal minutes: less filament; still equal: the first (all_left, nothing to load)
        best = min(options, key=lambda o: (o["estimate"]["minutes"], o["estimate"]["grams"]))
        e = best["estimate"]
        nozzle_of = best["nozzles"]
        others = sorted((o for o in options if o is not best),
                        key=lambda o: (o["estimate"]["minutes"], o["estimate"]["grams"]))
        if others:
            e["other_nozzles"] = {k: others[0][k] for k in ("option", "label", "minutes", "grams")}
    else:
        nozzle_of = {}
        e = run_estimate({})
    if int(g.get("QUANTITY", 1)) > 1:   # for x2d-print when only one copy fits on the plate
        one = run_estimate(nozzle_of, quantity=1)
        e["one_copy"] = {k: one[k] for k in ("grams", "model_g", "metres", "minutes", "minutes_range")}
    label = f"{args.variant}, {st['walls']} walls, {st['infill']:g}% infill, {g['LAYER']:g} mm layers"
    print(est.describe(e, label, g["MATERIAL"]))
    if len(options) > 1:
        rest = "; ".join(f"{o['label']} (~{o['minutes']} min, {o['grams']:g} g)" for o in others)
        print(f"nozzles: {best['label']} is faster (~{best['minutes']} min, {best['grams']:g} g) than {rest}")
    elif profile["nozzles"] >= 2 and len(set(colours.values())) > 1 and not external:
        print("nozzles: EXTERNAL_SPOOL = False, every colour on the left nozzle (AMS)")

    stls = {}
    if not args.check:
        params = cad.param_snapshot(g)
        params["FITS"] = g.get("FITS")
        extra = {"printer": profile["name"], "assembly": together, "printer_notes": notes, "variant": args.variant,
                 "print_settings": st, "estimate": e}
        if joined is not None:
            extra["assembly_check"] = joined.to_dict()
        for part_name, suffix, mesh, res in results:
            try:
                stl, meta = cad.write_part(out_dir, part_name, mesh, res, material=g["MATERIAL"], params=params,
                                           color=hexes[suffix], bed=bed, extra=dict(extra, colour=colours[suffix]))
            except (ValueError, OSError) as exc:
                return _refuse(exc)
            stls[stl.name] = hashlib.sha256(stl.read_bytes()).hexdigest()
            print(f"wrote {stl.relative_to(project_dir)} and {meta.relative_to(project_dir)}")
    if args.no_handoff:   # a version built for --variants: the parent reads this line
        print("@@estimate " + json.dumps({"estimate": e, "parts": stls}))
    if args.check and not args.variants:
        print("\ncheck only: nothing written")
    return {"estimate": e, "parts": stls, "handoff": handoff, "together": together, "notes": notes,
            "settings": st, "nozzles": nozzle_of, "external_spool": external,
            "nozzle_options": [{k: o[k] for k in ("option", "label", "nozzles", "minutes", "grams")}
                               for o in options if o["option"] != "chosen"]}


def _handoff(g, args, name, out_dir, profile, project_dir, built, rows) -> int:
    if args.check or args.no_handoff or not profile.get("handoff"):
        return 0
    st = built["settings"]
    settings = printers.slicer_settings(walls=st["walls"], infill=st["infill"], layer=g["LAYER"],
                                        top_layers=st["top_layers"], bottom_layers=st["bottom_layers"],
                                        supports=g["SUPPORTS_ALLOWED"])
    job_variants = []
    old = printers.read_handoff(out_dir, profile["handoff_file"])
    if rows is None and isinstance(old, dict):
        # a plain rebuild keeps the versions compared earlier, if their files are still there
        job_variants = [v for v in old.get("variants", []) if isinstance(v, dict)
                        and (out_dir / "variants" / str(v.get("name"))).is_dir()
                        and v.get("name") != args.variant]
    for r in rows or []:
        if r["name"] == args.variant or not r.get("ok") or not r.get("estimate"):
            continue
        vdir = out_dir / r["dir"]
        meta = sorted(vdir.glob(f"{name}*.json"))
        vs = None
        for m in meta:
            try:
                vs = json.loads(m.read_text(encoding="utf-8")).get("print_settings") or vs
            except (OSError, ValueError):
                pass
        vs = vs or st
        entry = {"name": r["name"], "about": r["about"],
                 "settings": printers.slicer_settings(walls=vs["walls"], infill=vs["infill"],
                                                      layer=vs.get("layer", g["LAYER"]),
                                                      top_layers=vs["top_layers"], bottom_layers=vs["bottom_layers"],
                                                      supports=g["SUPPORTS_ALLOWED"]),
                 "estimate": {k: r["estimate"][k] for k in ("grams", "metres", "minutes", "minutes_range",
                                                            "in_calibration") if k in r["estimate"]}}
        changed = {stl: f"{r['dir']}/{stl}" for stl, h in (r.get("parts") or {}).items()
                   if built["parts"].get(stl) != h}
        if changed:
            entry["stl"] = changed
        job_variants.append(entry)
    e = built["estimate"]
    job = printers.x2d_job(name, built["handoff"], assembly=built["together"], material=g["MATERIAL"],
                           layer=g["LAYER"], nozzle=g["NOZZLE"], supports=g["SUPPORTS_ALLOWED"], profile=profile,
                           printer_notes=built["notes"], settings=settings,
                           estimate={k: e[k] for k in ("grams", "metres", "minutes", "minutes_range", "purge_g",
                                                       "in_calibration", "outside_because", "one_copy")
                                     if k in e},
                           variants=job_variants, variant=args.variant, quantity=int(g.get("QUANTITY", 1)),
                           first_print=g.get("FIRST_PRINT"), suggested_nozzles=built["nozzles"],
                           nozzle_options=built["nozzle_options"] or None, external_spool=built["external_spool"])
    for note in printers.keep_filled(job, old):
        print(f"note: {note}")
    try:
        path = printers.write_handoff(out_dir, job, profile["handoff_file"])
    except (ValueError, OSError) as exc:
        return _refuse(exc)
    print(f"wrote {path.relative_to(project_dir)}: draft job for the {profile['handoff']} skill "
          "(template and filament numbers are filled there)")
    return 0
