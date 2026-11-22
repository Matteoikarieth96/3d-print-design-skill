"""Printer profiles, multicolour (assembly) checks and the hand-off to x2d-print."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assembly  # noqa: E402
import cad  # noqa: E402
import printcheck  # noqa: E402
import printers  # noqa: E402
import serve  # noqa: E402

LAYER = 0.2


def coaster(inlay_t=0.6, overlap=False, lift=0.0):
    """40 mm square base 3 mm high with a 10 mm square inlay on top."""
    base = cad.box(40, 40, 3)
    inlay = cad.translate(cad.box(10, 10, inlay_t), z=3 - inlay_t + lift)
    parts = {"base": base if overlap else cad.difference(base, inlay), "inlay": inlay}
    return parts


def run_assembly(parts, nozzles=2, bed=(235.5, 256, 256)):
    return assembly.check_assembly(parts, bed=bed, layer=LAYER, nozzle=0.4, overhang_deg=45,
                                   supports=False, expected_bodies=1, nozzles=nozzles)


class ProfileTests(unittest.TestCase):
    def test_unknown_profile_refused_and_generic_default(self):
        with self.assertRaises(ValueError):
            printers.get("prusa-xl")
        self.assertEqual(printers.get(None)["name"], "generic")
        self.assertEqual(printers.get(" Bambu-X2D ")["name"], "bambu-x2d")

    def test_bed_for(self):
        x2d = printers.get("bambu-x2d")
        self.assertEqual(printers.bed_for(x2d, 1), (256.0, 256.0, 261.0))
        self.assertEqual(printers.bed_for(x2d, 2), (235.5, 256.0, 256.0))
        self.assertEqual(printers.bed_for(x2d, 3, (100, 100, 100)), (100.0, 100.0, 100.0))
        self.assertEqual(printers.bed_for(printers.get("generic"), 4), (220.0, 220.0, 250.0))
        with self.assertRaises(ValueError):
            printers.bed_for(x2d, 1, (100, 100))

    def test_colour_layers(self):
        parts = [{"stl": "a", "z": (0.0, 4.0)}, {"stl": "b", "z": (3.4, 4.0)}]
        self.assertEqual(printers.colour_layers(parts, LAYER),
                         {"layers": 20, "mixed_layers": 3, "max_colours_per_layer": 2})

    def test_suggest_nozzles(self):
        x2d = printers.get("bambu-x2d")
        parts = [{"stl": "star.stl", "colour": "yellow", "layers": 3, "volume_mm3": 600},
                 {"stl": "base.stl", "colour": "black", "layers": 20, "volume_mm3": 24000}]
        # the main colour stays on the left nozzle (the fast one), the accent goes on the right one
        self.assertEqual(printers.suggest_nozzles(x2d, parts, "PLA", mixed_layers=3),
                         {"black": "left", "yellow": "right"})
        plans = {p["option"]: p["nozzles"] for p in printers.nozzle_options(x2d, parts, "PLA", mixed_layers=3)}
        self.assertEqual(list(plans), ["all_left", "accent_right", "dominant_right"])
        self.assertEqual(plans["dominant_right"], {"black": "right", "yellow": "left"})
        self.assertEqual(set(printers.suggest_nozzles(x2d, parts, "TPU", mixed_layers=3).values()), {"left"})
        self.assertEqual(printers.suggest_nozzles(printers.get("generic"), parts, "PLA"), {})
        # colours only change by height: everything on the left nozzle (x2d-print colour rule 2)
        self.assertEqual(printers.suggest_nozzles(x2d, parts, "PLA", mixed_layers=0),
                         {"black": "left", "yellow": "left"})

    def test_one_colour_in_several_parts_stays_on_one_nozzle(self):
        x2d = printers.get("bambu-x2d")
        parts = [{"stl": "box.stl", "colour": "blue", "layers": 40, "volume_mm3": 9000},
                 {"stl": "lid.stl", "colour": "blue", "layers": 10, "volume_mm3": 2000}]
        self.assertEqual(printers.suggest_nozzles(x2d, parts, "PLA", mixed_layers=10), {"blue": "left"})

    def test_keep_filled_only_when_parts_and_colours_match(self):
        def job(colour="black"):
            return {"template": "", "nozzles": {}, "objects": [{"name": "a", "parts": [
                {"stl": "a-base.stl", "colour": colour, "filament": None}]}]}
        old = job()
        old["template"] = "/x/Cubo.3mf"
        old["objects"][0]["parts"][0]["filament"] = 5
        old["nozzles"] = {"5": "right"}
        new = job()
        notes = printers.keep_filled(new, old)
        self.assertIn("kept", notes[0])
        self.assertEqual((new["template"], new["objects"][0]["parts"][0]["filament"], new["nozzles"]),
                         ("/x/Cubo.3mf", 5, {"5": "right"}))
        changed = job("red")
        self.assertIn("reset", printers.keep_filled(changed, old)[0])
        self.assertIsNone(changed["objects"][0]["parts"][0]["filament"])
        self.assertEqual(printers.keep_filled(job(), job()), [])

    def test_notes_mention_tpu_and_two_nozzle_reach(self):
        x2d = printers.get("bambu-x2d")
        text = " ".join(printers.notes(x2d, "TPU", 2, True))
        self.assertIn("cannot print it", text)
        self.assertIn("235.5", text)
        self.assertEqual(printers.notes(printers.get("generic"), "TPU", 2, False), [])

    def test_handoff_refuses_symlink_and_bad_name(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "elsewhere.json"
            target.write_text("{}")
            (Path(d) / "x2d-job.json").symlink_to(target)
            with self.assertRaises(ValueError):
                printers.write_handoff(Path(d), {"a": 1}, "x2d-job.json")
            self.assertEqual(target.read_text(), "{}")
            for bad in ("../x.json", "sub/x.json", "x.txt"):
                with self.assertRaises(ValueError):
                    printers.write_handoff(Path(d), {}, bad)


class AssemblyTests(unittest.TestCase):
    def test_inlay_on_top_passes(self):
        res = run_assembly(coaster())
        self.assertTrue(res.ok, res.summary())
        self.assertEqual(res.get("on_bed").status, printcheck.PASS)
        self.assertEqual(res.get("colour_layers").data["mixed_layers"], 3)

    def test_inlay_alone_is_not_called_floating(self):
        mesh = cad.to_trimesh(coaster()["inlay"])
        alone = printcheck.check_printable(mesh, layer=LAYER, supports=False, thin_wall_samples=200)
        self.assertFalse(alone.ok)  # standalone: the inlay does not touch the bed
        part = printcheck.check_printable(mesh, layer=LAYER, supports=False, thin_wall_samples=200,
                                          standalone=False)
        self.assertTrue(part.ok, part.summary())
        self.assertEqual(part.get("on_bed").status, printcheck.SKIP)
        self.assertEqual(part.get("thin_walls").status, printcheck.PASS)  # 0.6 mm high, 10 mm wide

    def test_colour_part_off_layer_grid_is_reported(self):
        mesh = cad.to_trimesh(cad.translate(cad.box(10, 10, 0.6), z=2.3))
        part = printcheck.check_printable(mesh, layer=LAYER, standalone=False)
        self.assertEqual(part.get("layer_alignment").status, printcheck.WARN)

    def test_overlap_is_an_error(self):
        res = run_assembly(coaster(overlap=True))
        self.assertEqual(res.get("overlap").status, printcheck.FAIL)
        self.assertFalse(res.ok)

    def test_floating_colour_part_is_an_error(self):
        res = run_assembly(coaster(lift=1.0))
        self.assertFalse(res.ok)
        self.assertEqual(res.get("bodies").status, printcheck.FAIL)

    def test_thin_colour_part_warns(self):
        res = run_assembly(coaster(inlay_t=0.2))
        self.assertEqual(res.get("colour_thickness").status, printcheck.WARN)

    def test_many_colours_through_the_height_warn(self):
        stripes = {f"s{k}": cad.translate(cad.box(10, 30, 4), x=10 * k) for k in range(3)}
        res = run_assembly(stripes, nozzles=2)
        self.assertEqual(res.get("colour_layers").status, printcheck.WARN)
        self.assertEqual(res.get("colour_layers").data["layers_over_nozzles"], 20)
        res2 = run_assembly({k: stripes[k] for k in ("s0", "s1")}, nozzles=2)
        self.assertEqual(res2.get("colour_layers").status, printcheck.PASS)


class BuildHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "my-part"
        self.project.mkdir()
        self.env = dict(os.environ, PRINT3D_SKILL_DIR=str(ROOT))

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, src):
        (self.project / "build.py").write_text(src)
        return subprocess.run([sys.executable, "-P", "build.py", "--thin-walls", "0"], cwd=self.project,
                              env=self.env, capture_output=True, text=True, timeout=300)

    def test_quantity_gives_a_one_copy_estimate(self):
        src = (ROOT / "templates" / "build.py").read_text().replace(
            'PRINTER = "generic" ', 'PRINTER = "bambu-x2d" ').replace("QUANTITY = 1 ", "QUANTITY = 4 ")
        res = self.build(src)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        est = json.loads((self.project / "out" / "x2d-job.json").read_text())["design"]["estimate"]
        one = est["one_copy"]
        self.assertLess(one["grams"], est["grams"] / 3)
        # one copy alone pays the whole preparation: more than a quarter of the time for 4
        self.assertGreater(one["minutes"], est["minutes"] / 4)

    def test_generic_template_writes_no_handoff(self):
        res = self.build((ROOT / "templates" / "build.py").read_text())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertFalse((self.project / "out" / "x2d-job.json").exists())
        meta = json.loads((self.project / "out" / "mounting-plate.json").read_text())
        self.assertEqual(meta["printer"], "generic")
        self.assertEqual(meta["printer_bed"], [220.0, 220.0, 250.0])

    def test_x2d_single_colour_handoff(self):
        src = (ROOT / "templates" / "build.py").read_text().replace(
            'PRINTER = "generic" ', 'PRINTER = "bambu-x2d" ')
        res = self.build(src)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        job = json.loads((self.project / "out" / "x2d-job.json").read_text())
        self.assertEqual(job["template"], "")
        self.assertEqual(job["objects"][0]["parts"][0]["stl"], "mounting-plate.stl")
        self.assertIsNone(job["objects"][0]["parts"][0]["filament"])
        self.assertEqual(job["design"]["suggested_nozzles"], {"blue": "left"})
        self.assertEqual(job["design"]["format"], 2)
        self.assertEqual(job["settings"]["wall_loops"], "3")
        self.assertEqual(job["settings"]["sparse_infill_density"], "15%")
        self.assertEqual(job["settings"]["layer_height"], "0.2")
        self.assertGreater(job["design"]["estimate"]["grams"], 0)
        self.assertIn("estimate (standard", res.stdout)
        # x2d-print fills the job in place; a rebuild keeps what it filled
        job["template"] = "/somewhere/Cubo.3mf"
        job["objects"][0]["parts"][0]["filament"] = 2
        (self.project / "out" / "x2d-job.json").write_text(json.dumps(job))
        res = self.build(src)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        again = json.loads((self.project / "out" / "x2d-job.json").read_text())
        self.assertEqual(again["template"], "/somewhere/Cubo.3mf")
        self.assertEqual(again["objects"][0]["parts"][0]["filament"], 2)
        self.assertEqual(job["output"], "mounting-plate.3mf")
        meta = json.loads((self.project / "out" / "mounting-plate.json").read_text())
        self.assertEqual(meta["printer_bed"], [256.0, 256.0, 261.0])

    def test_unknown_printer_refused(self):
        src = (ROOT / "templates" / "build.py").read_text().replace(
            'PRINTER = "generic" ', 'PRINTER = "nope" ')
        res = self.build(src)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown printer profile", res.stderr)
        self.assertFalse((self.project / "out").exists())

    def test_coaster_example_builds_with_a_complete_handoff(self):
        shutil.copy(ROOT / "examples" / "two-colour-coaster" / "build.py", self.project / "build.py")
        res = subprocess.run([sys.executable, "-P", "build.py", "--thin-walls", "0"], cwd=self.project,
                             env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        out = self.project / "out"
        job = json.loads((out / "x2d-job.json").read_text())
        self.assertEqual(len(job["objects"]), 1)
        parts = job["objects"][0]["parts"]
        self.assertEqual([p["colour"] for p in parts], ["black", "yellow"])
        for p in parts:
            self.assertTrue((out / p["stl"]).is_file())
            self.assertIsNone(p["filament"])
        # colours meet in only 3 layers. Real slices: 34 min with the star on the right nozzle, 37 to
        # 38 min all left (3 swaps), 41 min with the base on the right nozzle (it prints slower)
        self.assertEqual(job["design"]["suggested_nozzles"], {"black": "left", "yellow": "right"})
        self.assertEqual(job["design"]["colour_layers"]["mixed_layers"], 3)
        opts = {o["option"]: o for o in job["design"]["nozzle_options"]}
        self.assertEqual(opts["accent_right"]["nozzles"], {"black": "left", "yellow": "right"})
        self.assertEqual(opts["dominant_right"]["nozzles"], {"black": "right", "yellow": "left"})
        self.assertLessEqual(opts["accent_right"]["minutes"], opts["all_left"]["minutes"])
        self.assertLess(opts["accent_right"]["grams"], opts["all_left"]["grams"])
        self.assertLess(opts["all_left"]["minutes"], opts["dominant_right"]["minutes"])
        self.assertIn("other nozzle choice", res.stdout)
        meta = json.loads((out / "coaster-star.json").read_text())
        self.assertTrue(meta["assembly"])
        self.assertTrue(meta["assembly_check"]["ok"])

    def two_discs(self, external=True):
        src = (ROOT / "templates" / "build.py").read_text()
        head, rest = src.split("PLATE_W = 60.0", 1)
        tail = rest.split("# ====================== GEOMETRY END ======================", 1)[1]
        params = (head.replace('PRINTER = "generic" ', 'PRINTER = "bambu-x2d" ')
                  .replace('COLOR = "#4f8cff"', 'COLOR = {"big": "#161616", "small": "#fff144"}')
                  .replace('COLOUR_NAME = "blue"', 'COLOUR_NAME = {"big": "black", "small": "yellow"}')
                  .replace("EXTERNAL_SPOOL = True ", f"EXTERNAL_SPOOL = {external} "))
        geom = ("PROBES_INSIDE = []\nPROBES_OUTSIDE = []\n"
                "# ====================== PARAMETERS END ======================\n\n"
                "def build_part():\n"
                "    return {'big': cad.extrude(cad.circle2d(60.0), 3.0),\n"
                "            'small': cad.translate(cad.extrude(cad.circle2d(40.0), 3.0), x=60.0)}\n"
                "# ====================== GEOMETRY END ======================")
        return params + geom + tail

    def test_separate_objects_of_two_colours_share_layers(self):
        """Two discs side by side: every layer holds both colours, so the smaller one goes right."""
        res = self.build(self.two_discs())
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        job = json.loads((self.project / "out" / "x2d-job.json").read_text())
        self.assertEqual(len(job["objects"]), 2)
        self.assertEqual(job["design"]["colour_layers"]["mixed_layers"], 15)
        self.assertEqual(job["design"]["suggested_nozzles"], {"black": "left", "yellow": "right"})
        self.assertTrue(job["design"]["external_spool"])
        # no spool on the external holder: everything on the left nozzle, even if slower
        res = self.build(self.two_discs(external=False))
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        job = json.loads((self.project / "out" / "x2d-job.json").read_text())
        self.assertEqual(job["design"]["suggested_nozzles"], {"black": "left", "yellow": "left"})
        self.assertFalse(job["design"]["external_spool"])
        self.assertIn("EXTERNAL_SPOOL = False", res.stdout)

    def test_assembly_with_overlap_writes_nothing(self):
        src = (ROOT / "examples" / "two-colour-coaster" / "build.py").read_text().replace(
            'return {"base": cad.difference(disc, star), "star": star}', 'return {"base": disc, "star": star}')
        res = self.build(src)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("overlap", res.stdout)
        self.assertFalse((self.project / "out").exists())


    def test_variants_compare_and_reach_the_handoff(self):
        src = (ROOT / "templates" / "build.py").read_text().replace(
            'PRINTER = "generic" ', 'PRINTER = "bambu-x2d" ').replace(
            "PLATE_T = 4.0 ", "PLATE_T = cad.vary(4.0, light=3.0) ")
        (self.project / "build.py").write_text(src)
        res = subprocess.run([sys.executable, "-P", "build.py", "--thin-walls", "0", "--variants"], cwd=self.project,
                             env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("| light |", res.stdout)
        out = self.project / "out"
        self.assertTrue((out / "variants.md").is_file())
        versions = json.loads((out / "variants.json").read_text())["versions"]
        self.assertEqual([v["name"] for v in versions], ["standard", "light", "strong", "fast"])
        est_by = {v["name"]: v["estimate"] for v in versions}
        self.assertFalse(est_by["fast"]["in_calibration"])          # 0.28 mm layers: rough
        grams = {v["name"]: v["estimate"]["grams"] for v in versions}
        self.assertLess(grams["light"], grams["standard"])
        self.assertLess(grams["standard"], grams["strong"])
        job = json.loads((out / "x2d-job.json").read_text())
        by = {v["name"]: v for v in job["variants"]}
        self.assertEqual(by["light"]["settings"]["wall_loops"], "2")
        self.assertEqual(by["strong"]["settings"]["sparse_infill_density"], "40%")
        # the light plate is thinner: its STL differs and is listed; strong has the same geometry
        self.assertEqual(by["light"]["stl"], {"mounting-plate.stl": "variants/light/mounting-plate.stl"})
        self.assertTrue((out / "variants" / "light" / "mounting-plate.stl").is_file())
        self.assertNotIn("stl", by["strong"])
        self.assertEqual(by["fast"]["settings"]["layer_height"], "0.28")
        self.assertEqual(by["light"]["settings"]["layer_height"], "0.2")

    def test_unknown_variant_and_unlisted_vary_name_refused(self):
        src = (ROOT / "templates" / "build.py").read_text()
        (self.project / "build.py").write_text(src)
        res = subprocess.run([sys.executable, "-P", "build.py", "--check", "--variant", "huge"], cwd=self.project,
                             env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 2)
        self.assertIn("unknown version", res.stderr)
        res = self.build(src.replace("PLATE_T = 4.0 ", "PLATE_T = cad.vary(4.0, tiny=3.0) "))
        self.assertEqual(res.returncode, 2)
        self.assertIn("VARIANTS does not list", res.stderr)

    def test_assembly_needs_one_colour_per_part(self):
        src = (ROOT / "examples" / "two-colour-coaster" / "build.py").read_text().replace(
            'COLOUR_NAME = {"base": "black", "star": "yellow"}', 'COLOUR_NAME = "black"')
        res = self.build(src)
        self.assertEqual(res.returncode, 2, res.stdout + res.stderr)
        self.assertIn("its own colour", res.stderr)


class EstimateTests(unittest.TestCase):
    """Numbers checked against real Bambu Studio 02.09 slices on the X2D (scripts/estimate.py)."""

    def est(self, mesh, walls=2, infill=15, colour="a", **kw):
        import estimate
        mv = estimate.material_volume(mesh, layer=LAYER, nozzle=0.4, walls=walls, infill=infill,
                                      top_layers=5, bottom_layers=3)
        mv["colour"] = colour
        return mv

    def test_cube_matches_the_slicer(self):
        import estimate
        cube = cad.to_trimesh(cad.translate(cad.box(40, 40, 40), z=0))
        e = estimate.estimate([self.est(cube)], profile="bambu-x2d", material="PLA", layer=LAYER)
        lo, hi = e["grams_range"]
        self.assertTrue(lo <= 19.8 <= hi, e)           # Bambu Studio: 19.8 g, 39m41s
        lo, hi = e["minutes_range"]
        self.assertTrue(lo <= 39.7 <= hi, e)

    def test_colour_swaps_cost_more_than_nozzle_switches(self):
        import estimate
        a = cad.to_trimesh(cad.translate(cad.box(30, 40, 10), x=-5))
        b = cad.to_trimesh(cad.translate(cad.box(10, 40, 10), x=15))
        parts = [self.est(a, colour="a"), self.est(b, colour="b")]
        one = estimate.estimate(parts, profile="bambu-x2d", material="PLA", layer=LAYER,
                                nozzle_of={"a": "left", "b": "left"})
        two = estimate.estimate(parts, profile="bambu-x2d", material="PLA", layer=LAYER,
                                nozzle_of={"a": "left", "b": "right"})
        self.assertEqual(one["swaps"], 50)
        self.assertEqual(two["swaps"], 0)
        self.assertTrue(one["minutes_range"][0] <= 124 <= one["minutes_range"][1], one)   # slicer 2 h 04 min
        self.assertTrue(two["minutes_range"][0] <= 42 <= two["minutes_range"][1], two)     # slicer 42m
        self.assertGreater(one["purge_g"], 30)
        self.assertIn("swap", estimate.describe(one, "standard", "PLA"))

    def test_generic_profile_says_rough(self):
        import estimate
        cube = cad.to_trimesh(cad.box(20, 20, 20))
        e = estimate.estimate([self.est(cube)], profile="generic", material="PETG", layer=LAYER, quantity=3)
        self.assertEqual(e["quantity"], 3)
        self.assertIn("rough", estimate.describe(e, "standard", "PETG"))


class ViewerManifestTests(unittest.TestCase):
    def test_assembly_flag_reaches_the_manifest_only_when_true(self):
        with tempfile.TemporaryDirectory() as d:
            mesh = cad.to_trimesh(cad.box(10, 10, 2))
            res = printcheck.check_printable(mesh)
            cad.write_part(Path(d), "a", mesh, res, extra={"assembly": True})
            cad.write_part(Path(d), "b", mesh, res, extra={"assembly": "yes"})
            parts = {p["name"]: p for p in serve.build_manifest(Path(d))["parts"]}
            self.assertIs(parts["a"].get("assembly"), True)
            self.assertNotIn("assembly", parts["b"])
        js = (ROOT / "scripts" / "viewer" / "viewer.js").read_text()
        self.assertIn("assembly: p.assembly === true", js)


if __name__ == "__main__":
    unittest.main()
