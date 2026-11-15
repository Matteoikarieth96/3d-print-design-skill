"""The published calibration data (references/estimate-calibration.csv) and the estimate code cannot drift.

Every box-like calibration row is rebuilt from its parameters (no slicer) and
must give the CSV's model columns exactly; every row, calibration and holdout,
must fall inside the range the current spreads give.
"""
import csv
import math
import sys
import unittest
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import estimate  # noqa: E402

CSV = ROOT / "references" / "estimate-calibration.csv"


def _box(x, y, z, cx=0.0):
    m = trimesh.creation.box((x, y, z))
    m.apply_translation((cx, 0, z / 2))
    return m


def _cyl(d, h):
    m = trimesh.creation.cylinder(radius=d / 2, height=h, sections=96)
    m.apply_translation((0, 0, h / 2))
    return m


def _tube(d, w, h):
    m = trimesh.creation.annulus(r_min=d / 2 - w, r_max=d / 2, height=h, sections=96)
    m.apply_translation((0, 0, h / 2))
    return m


def _mv(mesh, row, colour="a"):
    mv = estimate.material_volume(mesh, layer=float(row["layer_mm"]), nozzle=0.4, walls=int(row["walls"]),
                                  infill=float(row["infill_pct"]), top_layers=5, bottom_layers=3)
    mv["colour"] = colour
    return mv


def _rows():
    with CSV.open(newline="") as f:
        return list(csv.DictReader(f))


class CalibrationCsvTests(unittest.TestCase):
    def test_csv_has_both_sets(self):
        rows = _rows()
        sets = {r["set"] for r in rows}
        self.assertEqual(sets, {"calibration", "holdout"})
        self.assertGreaterEqual(sum(r["set"] == "holdout" for r in rows), 6)

    def test_box_like_rows_match_the_code(self):
        checked = 0
        for row in _rows():
            if row["set"] != "calibration" or row["shape"] not in ("box", "cylinder", "tube", "stripes"):
                continue
            dims = [float(v) for v in row["size_mm"].split("+")[0].split("x")]
            nozzle_of = {}
            if row["shape"] == "box":
                parts = [_mv(_box(*dims), row)]
            elif row["shape"] == "cylinder":
                parts = [_mv(_cyl(*dims), row)]
            elif row["shape"] == "tube":
                parts = [_mv(_tube(*dims), row)]
            else:   # a 40 x 40 x 10 block: 30 mm in colour a, a 10 mm stripe in colour b
                parts = [_mv(_box(30, 40, 10, -5), row, "a"), _mv(_box(10, 40, 10, 15), row, "b")]
                nozzle_of = {"a": "left", "b": row["nozzles"].split("+")[1]}
            e = estimate.estimate(parts, profile="bambu-x2d", material=row["material"],
                                  layer=float(row["layer_mm"]), nozzle_of=nozzle_of)
            with self.subTest(part=row["part"], walls=row["walls"], infill=row["infill_pct"]):
                self.assertEqual(e["minutes"], int(row["model_min"]))
                self.assertAlmostEqual(e["minutes_exact"], float(row["model_min_exact"]), places=2)
                self.assertAlmostEqual(e["grams"], float(row["model_g"]), places=1)
                self.assertTrue(e["in_calibration"])
            checked += 1
        self.assertGreaterEqual(checked, 31)

    def test_every_row_is_inside_the_range_shown(self):
        for row in _rows():
            inside = row["in_calibration"] == "yes"
            t_sp = estimate.TIME_SPREAD if inside else estimate.ROUGH_TIME_SPREAD
            g_sp = estimate.GRAMS_SPREAD if inside else estimate.ROUGH_GRAMS_SPREAD
            minutes = float(row["model_min_exact"])
            lo, hi = estimate._floor5(minutes * (1 - t_sp[0])), estimate._ceil5(minutes * (1 + t_sp[1]))
            glo, ghi = float(row["model_g"]) * (1 - g_sp[0]), float(row["model_g"]) * (1 + g_sp[1])
            with self.subTest(set=row["set"], part=row["part"], nozzles=row["nozzles"]):
                self.assertTrue(lo <= float(row["slicer_min"]) <= hi, (lo, hi, row["slicer_min"]))
                self.assertTrue(glo - 0.1 <= float(row["slicer_g"]) <= ghi + 0.1, (glo, ghi, row["slicer_g"]))
                self.assertEqual(row["in_range"], "yes")
                err = 100 * (minutes - float(row["slicer_min"])) / float(row["slicer_min"])
                self.assertTrue(math.isclose(err, float(row["err_min_pct"]), abs_tol=0.11))

    def test_docs_quote_the_csv(self):
        md = (ROOT / "references" / "estimate-calibration.md").read_text()
        self.assertIn("estimate-calibration.csv", md)
        self.assertIn("02.09.01.70", md)
        self.assertIn("NOT covered", md)


class EstimateScopeTests(unittest.TestCase):
    def setUp(self):
        self.mesh = _box(40, 40, 10)

    def est(self, **kw):
        args = dict(profile="bambu-x2d", material="PLA", layer=0.2, supports=False, nozzle=0.4)
        infill = kw.pop("infill", 15)
        args.update(kw)
        mv = estimate.material_volume(self.mesh, layer=args["layer"], nozzle=args["nozzle"], walls=3, infill=infill,
                                      top_layers=5, bottom_layers=3)
        mv["colour"] = "a"
        return estimate.estimate([mv], **args)

    def test_inside_the_measured_field(self):
        e = self.est()
        self.assertTrue(e["in_calibration"])
        self.assertNotIn("rough", estimate.describe(e, "standard", "PLA"))

    def test_outside_gets_a_wider_range_and_the_label(self):
        base = self.est()
        width = base["minutes_range"][1] - base["minutes_range"][0]
        for kw in ({"supports": True}, {"infill": 60}, {"material": "PETG"}, {"layer": 0.28},
                   {"nozzle": 0.6}, {"profile": "generic"}):
            with self.subTest(**kw):
                e = self.est(**kw)
                self.assertFalse(e["in_calibration"])
                self.assertTrue(e["outside_because"])
                self.assertIn(estimate.ROUGH_LABEL, estimate.describe(e, "standard", kw.get("material", "PLA")))
                lo, hi = e["minutes_range"]
                self.assertGreaterEqual(hi - lo, width)
        sup = self.est(supports=True)
        self.assertIn("supports are not counted", " ".join(sup["outside_because"]))
        tpu = self.est(material="TPU")
        self.assertGreater(tpu["minutes_range"][1] / tpu["minutes_exact"],
                           self.est(material="PETG")["minutes_range"][1] / self.est(material="PETG")["minutes_exact"])

    def test_table_shows_point_estimate_difference_and_rough(self):
        std = self.est()
        strong = self.est(infill=40)
        rows = [{"name": "standard", "about": "3 walls", "estimate": std, "ok": True},
                {"name": "strong", "about": "40 %", "estimate": strong, "ok": True}]
        text = estimate.table(rows, "PLA")
        self.assertIn("| vs standard |", text)
        self.assertIn(f"~{estimate.duration(std['minutes'])} (", text)
        self.assertIn(f"+{round(strong['grams'] - std['grams'], 1):g} g", text)
        gen = self.est(profile="generic")
        text = estimate.table([{"name": "standard", "about": "-", "estimate": gen, "ok": True}], "PLA")
        self.assertIn(estimate.ROUGH_LABEL, text)
        self.assertIn(", rough", text)

    def test_thin_layers_are_slowed_down(self):
        """A 15 x 15 x 80 post: 400 small layers, each held to about 8 s by the slicer (61 min real)."""
        mv = estimate.material_volume(_box(15, 15, 80), layer=0.2, nozzle=0.4, walls=3, infill=15,
                                      top_layers=5, bottom_layers=3)
        e = estimate.estimate([mv], profile="bambu-x2d", material="PLA", layer=0.2)
        self.assertTrue(e["minutes_range"][0] <= 61 <= e["minutes_range"][1], e)

    def test_layer_areas_add_up_to_the_volume(self):
        for mesh in (_box(30, 20, 10), _cyl(40, 12), _tube(40, 3, 20)):
            a = estimate.layer_areas(mesh, 0.2)
            self.assertAlmostEqual(a.sum() * 0.2 / mesh.volume, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
