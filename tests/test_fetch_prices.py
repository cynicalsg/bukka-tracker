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

    def test_seasonal_profile_finds_cheap_and_dear_months(self):
        # 10 years of a price that is 20% cheaper every May and 20% dearer every November, with slow inflation.
        pts = []
        for y in range(2015, 2027):
            for mo in range(1, 13):
                level = 100 * (1.01 ** (y - 2015))
                bump = {5: 0.8, 11: 1.2}.get(mo, 1.0)
                pts.append([f"{y}-{mo:02d}", round(level * bump, 2)])
        prof = fp.seasonal_profile(pts)
        f = prof["factors"]
        self.assertEqual(f.index(min(f)), 4)    # May
        self.assertEqual(f.index(max(f)), 10)   # November
        self.assertAlmostEqual(sum(f) / 12, 1, places=3)
        self.assertGreater(prof["amplitude"], 0.4)

    def test_seasonal_profile_handles_out_of_season_gaps(self):
        pts = [[f"{y}-{mo:02d}", 500 + (mo - 10) * 20] for y in range(2014, 2027) for mo in (9, 10, 11, 12, 1, 2, 3)]
        pts.sort()
        prof = fp.seasonal_profile(pts)
        self.assertIsNotNone(prof)
        self.assertIsNone(prof["factors"][6])  # July: never surveyed

    def test_seasonal_profile_needs_enough_data(self):
        self.assertIsNone(fp.seasonal_profile([["2026-01", 100.0], ["2026-02", 101.0]]))

    def test_capital_areas_city_prices_and_national_average(self):
        classes = {"area": [{"@code": "23100", "@name": "名古屋市"}, {"@code": "43100", "@name": "熊本市"},
                            {"@code": "43201", "@name": "熊本市【～2012年３月】"}, {"@code": "23202", "@name": "岡崎市"}]}
        area_to_city = fp.capital_areas(classes, ["名古屋市", "熊本市"])
        self.assertEqual(area_to_city, {"23100": "名古屋市", "43100": "熊本市", "43201": "熊本市"})
        values = [
            {"@cat01": "01001", "@area": "23100", "@time": "2012000303", "$": "100"},
            {"@cat01": "01001", "@area": "43201", "@time": "2012000303", "$": "200"},   # old Kumamoto code
            {"@cat01": "01001", "@area": "23100", "@time": "2012000404", "$": "110"},
            {"@cat01": "01001", "@area": "43100", "@time": "2012000404", "$": "210"},   # new Kumamoto code
            {"@cat01": "01001", "@area": "43201", "@time": "2012000404", "$": "230"},   # overlap: averaged
            {"@cat01": "01001", "@area": "23202", "@time": "2012000404", "$": "999"},   # not a listed city
            {"@cat01": "01001", "@area": "23100", "@time": "2012000505", "$": "120"},
            {"@cat01": "01001", "@area": "23100", "@time": "2009000505", "$": "90"},
        ]
        by_city = fp.city_prices(values, "cat01", area_to_city)
        self.assertEqual(by_city["熊本市"]["01001"], {"2012-03": 200.0, "2012-04": 220.0})
        self.assertEqual(by_city["名古屋市"]["01001"]["2012-05"], 120.0)
        avg = fp.national_average(by_city, ["名古屋市", "熊本市"], "2010-01", min_cities=2)
        self.assertEqual(avg, {"01001": [["2012-03", 150.0], ["2012-04", 165.0]]})   # May: one city; 2009: too early

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
