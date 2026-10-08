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

import cad  # noqa: E402
import printcheck  # noqa: E402

BAD_NAMES = ["", "A", "Part", "a b", "a_b", "-a", "../x", "a/b", "a\\b", "x" * 65, "a\n", "café",
             "con.stl", ".hidden", "a;rm", None, 42]
HARNESS_MARK = "# ============ HARNESS: DO NOT EDIT BELOW THIS LINE ============"


class NameAndPathTests(unittest.TestCase):
    def test_bad_names_rejected(self):
        for name in BAD_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    cad.validate_name(name)

    def test_good_names_accepted(self):
        for name in ("a", "cable-clip", "0-1", "x" * 64, "left-bracket-v2"):
            self.assertEqual(cad.validate_name(name), name)

    def test_out_dir_must_stay_in_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            self.assertEqual(cad.safe_out_dir(project, "out"), (project / "out").resolve())
            for bad in ("../out", "/tmp", "out/../../x"):
                with self.subTest(out=bad):
                    with self.assertRaises(ValueError):
                        cad.safe_out_dir(project, bad)
            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            (project / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                cad.safe_out_dir(project, "link")

    def test_fits_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cad.load_fits(tmp)["sliding"], cad.DEFAULT_FITS["sliding"])
            Path(tmp, "fits.json").write_text(json.dumps({"clearance_per_side": {"sliding": 0.25}}))
            self.assertEqual(cad.load_fits(tmp)["sliding"], 0.25)
            Path(tmp, "fits.json").write_text(json.dumps({"clearance_per_side": {"press": 5}}))
            with self.assertRaises(ValueError):
                cad.load_fits(tmp)


class GeometryTests(unittest.TestCase):
    def test_chamfered_non_convex_outline(self):
        from shapely.geometry import Polygon
        outline = cad.rect(40, 20).difference(Polygon([(-1, -10.01), (0, -8), (1, -10.01)]))
        outline = outline.difference(cad.circle2d(6))
        solid = cad.chamfered_extrude(outline, 4.0, bottom=0.4, top=0.4)
        mesh = cad.to_trimesh(solid)
        self.assertTrue(mesh.is_watertight)
        self.assertLess(mesh.volume, outline.area * 4.0)
        self.assertGreater(mesh.volume, outline.area * 4.0 * 0.9)
        r = printcheck.check_printable(mesh)
        self.assertEqual(r.get("overhang").status, "pass")  # 45 degree chamfers need no support

    def test_chamfer_too_large_is_refused(self):
        with self.assertRaises(ValueError):
            cad.chamfered_extrude(cad.rect(2, 20), 4.0, bottom=1.2)

    def test_countersink_deeper_than_plate_is_refused(self):
        with self.assertRaises(ValueError):
            cad.countersunk_cutter(3.5, 12.0, 3.0)

    def test_polygon_hole_is_not_undersize(self):
        n = 24
        hole = cad.difference(cad.box(20, 20, 4), cad.hole(5.0, 4, 4, n=n))
        mesh = cad.to_trimesh(hole)
        r = printcheck.check_printable(mesh, min_hole_d=1.0)
        widths = [h["min_width_mm"] for h in r.get("small_holes").data["all"]]
        self.assertTrue(widths and min(widths) >= 4.99, widths)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "my-part"
        self.project.mkdir()
        self.env = dict(os.environ, PRINT3D_SKILL_DIR=str(ROOT))

    def tearDown(self):
        self.tmp.cleanup()

    def run_build(self, replace=None, args=()):
        src = (ROOT / "templates" / "build.py").read_text()
        for old, new in (replace or {}).items():
            self.assertIn(old, src)
            src = src.replace(old, new)
        (self.project / "build.py").write_text(src)
        return subprocess.run([sys.executable, "build.py", *args], cwd=self.project, env=self.env,
                              capture_output=True, text=True, timeout=300)

    def test_template_builds_and_writes_metadata(self):
        res = self.run_build()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        meta = json.loads((self.project / "out" / "mounting-plate.json").read_text())
        self.assertTrue(meta["printcheck"]["ok"])
        self.assertEqual(meta["units"], "mm")
        self.assertGreater(meta["estimated_mass_g_solid"], 0)
        self.assertEqual(meta["parameters"]["PLATE_T"], 4.0)
        self.assertTrue((self.project / "out" / "mounting-plate.stl").stat().st_size > 1000)

    def test_template_refuses_bad_name(self):
        res = self.run_build({'NAME = "mounting-plate"': 'NAME = "../../evil"'})
        self.assertEqual(res.returncode, 2)
        self.assertIn("refusing", res.stderr)
        self.assertFalse((self.project / "out").exists())

    def test_template_refuses_out_dir_outside_project(self):
        res = self.run_build(args=("--out", "../escape"))
        self.assertEqual(res.returncode, 2)
        self.assertFalse((self.project.parent / "escape").exists())

    def test_failed_check_writes_nothing(self):
        res = self.run_build({"PRINTER_BED = (220, 220, 250)": "PRINTER_BED = (40, 40, 40)"})
        self.assertEqual(res.returncode, 1)
        self.assertFalse((self.project / "out").exists())

    def test_examples_keep_the_template_harness(self):
        harness = (ROOT / "templates" / "build.py").read_text().split(HARNESS_MARK)[1]
        for build in (ROOT / "examples").glob("*/build.py"):
            with self.subTest(example=build.parent.name):
                self.assertEqual(build.read_text().split(HARNESS_MARK)[1], harness)


if __name__ == "__main__":
    unittest.main()
