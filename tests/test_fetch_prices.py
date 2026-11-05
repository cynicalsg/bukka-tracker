import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import fetch_prices as fp  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "stats_data_sample.json").read_text(encoding="utf-8"))
CONFIG = json.loads((ROOT / "fetch" / "items.json").read_text(encoding="utf-8"))
# Tests also cover a second comparison city, which the live config may not use.
CONFIG["areas"].append({"id": "tokyo", "match": "東京都区部", "name_ja": "東京都区部", "name_en": "Tokyo"})


class ParseHelpers(unittest.TestCase):
    def test_parse_month(self):
        self.assertEqual(fp.parse_month("2024000909"), "2024-09")
        self.assertIsNone(fp.parse_month("2024000000"))  # annual
        self.assertIsNone(fp.parse_month("2024000103"))  # quarter-like range

    def test_parse_number(self):
        self.assertEqual(fp.parse_number("2,450"), 2450.0)
        for missing in ("-", "…", "***", None):
            self.assertIsNone(fp.parse_number(missing))


class BuildDataset(unittest.TestCase):
    def setUp(self):
        self.ds = fp.build_dataset(json.loads(json.dumps(FIXTURE)), CONFIG)
        self.items = {i["id"]: i for i in self.ds["items"]}

    def test_areas_matched_by_name(self):
        self.assertEqual([a["id"] for a in self.ds["areas"]], ["nagoya", "tokyo"])

    def test_rice_picks_koshihikari_monthly_sorted(self):
        rice = self.items["rice"]
        self.assertEqual(rice["estat_code"], "01001")
        self.assertEqual((rice["unit_ja"], rice["unit_en"]), ("5kg", "5 kg"))
        self.assertEqual(rice["series"]["nagoya"], [["2024-01", 2400.0], ["2024-02", 2450.0]])
        self.assertEqual(rice["series"]["tokyo"], [["2024-01", 2500.0]])

    def test_items_json_milk_skips_discontinued_bottle(self):
        entries = [{"@code": "01301", "@name": "1301 牛乳(配達,瓶入り)【2021年12月調査終了】"},
                   {"@code": "01303", "@name": "1303 牛乳(紙パック入り)"}]
        milk = next(i for i in CONFIG["items"] if i["id"] == "milk")
        self.assertEqual(fp.match_item(milk, entries)["@code"], "01303")

    def test_categories_carried_through(self):
        self.assertEqual(self.items["rice"]["category"], "grains")
        self.assertTrue(any(c["id"] == "grains" for c in self.ds["categories"]))
        known = {c["id"] for c in CONFIG["categories"]}
        self.assertTrue(all(i["category"] in known for i in CONFIG["items"]))

    def test_dump_dataset_round_trips(self):
        self.assertEqual(json.loads(fp.dump_dataset(self.ds)), self.ds)

    def test_adjust_series_since_and_rescale(self):
        pts = [["2012-12", 14.0], ["2013-06", 15.0], ["2014-01", 150.0]]
        item = {"since": "2013-01", "rescale": [{"before": "2014-01", "factor": 10}]}
        self.assertEqual(fp.adjust_series(pts, item), [["2013-06", 150.0], ["2014-01", 150.0]])
        self.assertEqual(fp.adjust_series(pts, {}), pts)

    def test_missing_values_skipped(self):
        self.assertEqual(self.items["milk"]["series"]["nagoya"], [["2024-01", 250.0]])

    def test_unmatched_items_dropped(self):
        self.assertNotIn("cabbage", self.items)

    def test_pinned_code_overrides_match(self):
        config = json.loads(json.dumps(CONFIG))
        config["items"] = [{"id": "rice2", "code": "01002", "match": ["x"], "name_ja": "米", "name_en": "Rice"}]
        ds = fp.build_dataset(json.loads(json.dumps(FIXTURE)), config)
        self.assertEqual(ds["items"][0]["series"]["nagoya"], [["2024-01", 2100.0]])

    def test_resolve_filters_requests_only_needed_codes(self):
        filters = fp.resolve_filters(json.loads(json.dumps(FIXTURE)), CONFIG)
        self.assertEqual(filters["cdArea"], "13100,23100")  # Osaka left out
        self.assertEqual(filters["cdCat01"], "01001,03001,04001")  # non-Koshihikari rice left out


if __name__ == "__main__":
    unittest.main()
