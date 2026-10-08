import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cad  # noqa: E402
import calibration_coupon as cc  # noqa: E402
import printcheck  # noqa: E402


class CouponTests(unittest.TestCase):
    def test_clearances_and_tally(self):
        self.assertEqual(cc.clearances(), [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4])
        self.assertEqual(cc.tally(0), [])
        self.assertEqual(cc.tally(3), ["shallow"] * 3)
        self.assertEqual(cc.tally(5), ["deep"])
        self.assertEqual(cc.tally(8), ["deep", "shallow", "shallow", "shallow"])

    def test_coupon_is_watertight_and_printable(self):
        solid, legend = cc.build_coupon()
        mesh = cad.to_trimesh(solid)
        self.assertTrue(mesh.is_watertight)
        r = printcheck.check_printable(mesh, expected_bodies=4, supports=True)
        self.assertTrue(r.ok, r.summary())
        self.assertEqual(len(legend["round_holes_front_edge"]), 9)
        # 18 holes: 9 round + 9 square
        self.assertGreaterEqual(r.get("small_holes").data["holes_found"], 18)

    def test_peg_size_is_validated(self):
        with self.assertRaises(ValueError):
            cc.build_coupon(peg_d=50)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def run_main(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cc.main(list(args))

    def test_record_round_trip(self):
        code = self.run_main("record", "--press", "0.1", "--snug", "0.15", "--sliding", "0.2", "--free", "0.3",
                             "--overhang", "50", "--printer", "test printer 1", "--material", "petg")
        self.assertEqual(code, 0)
        data = json.loads(Path("fits.json").read_text())
        self.assertEqual(data["clearance_per_side"]["sliding"], 0.2)
        fits = cad.load_fits(".")
        self.assertEqual(fits["press"], 0.1)
        self.assertEqual(fits["overhang_ok_deg"], 50.0)

    def test_record_rejects_bad_input(self):
        for args in (["--press", "3"], ["--press", "0.1", "--printer", "<script>"],
                     ["--press", "0.1", "--material", "wood"], ["--press", "0.1", "--overhang", "89"], []):
            with self.subTest(args=args):
                self.assertEqual(self.run_main("record", *args), 2)
        self.assertFalse(Path("fits.json").exists())

    def test_build_refuses_out_outside(self):
        self.assertEqual(self.run_main("build", "--out", "../elsewhere"), 2)


if __name__ == "__main__":
    unittest.main()
