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
        parts = [{"stl": "star.stl", "layers": 3, "volume_mm3": 600},
                 {"stl": "base.stl", "layers": 20, "volume_mm3": 24000}]
        self.assertEqual(printers.suggest_nozzles(x2d, parts, "PLA"),
                         {"base.stl": "right", "star.stl": "left"})
        self.assertEqual(set(printers.suggest_nozzles(x2d, parts, "TPU").values()), {"left"})
        self.assertEqual(printers.suggest_nozzles(printers.get("generic"), parts, "PLA"), {})

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
        self.assertEqual(job["design"]["suggested_nozzles"], {"mounting-plate.stl": "left"})
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
        self.assertEqual(job["design"]["suggested_nozzles"],
                         {"coaster-base.stl": "right", "coaster-star.stl": "left"})
        self.assertEqual(job["design"]["colour_layers"]["mixed_layers"], 3)
        meta = json.loads((out / "coaster-star.json").read_text())
        self.assertTrue(meta["assembly"])
        self.assertTrue(meta["assembly_check"]["ok"])

    def test_assembly_with_overlap_writes_nothing(self):
        src = (ROOT / "examples" / "two-colour-coaster" / "build.py").read_text().replace(
            'return {"base": cad.difference(disc, star), "star": star}', 'return {"base": disc, "star": star}')
        res = self.build(src)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertIn("overlap", res.stdout)
        self.assertFalse((self.project / "out").exists())


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
