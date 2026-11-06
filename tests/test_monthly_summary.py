import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import monthly_summary as ms  # noqa: E402


def item(id_, pts, seasonal=None):
    d = {"id": id_, "name_en": id_.title(), "name_ja": id_, "series": {"nagoya": pts}}
    if seasonal:
        d["seasonal"] = seasonal
    return d


PRICES = {"items": [
    item("rice", [["2025-09", 4700.0], ["2026-08", 3800.0], ["2026-09", 3550.0]]),
    item("eggs", [["2025-09", 300.0], ["2026-08", 320.0], ["2026-09", 322.0]]),
    # seasonal fruit: no price in Sep, last seen in Mar -> carried forward
    item("mikan", [["2025-03", 900.0], ["2026-03", 930.0]],
         seasonal={"factors": [1.1, 1.2, 1.25, None, None, None, None, None, None, 0.95, 0.83, 0.9], "amplitude": 0.48}),
]}
BASKET = {"household": {"adults": 2, "children": 0}, "child_factor": 0.6, "items": {
    "rice": {"per": 0.2, "default": 2.5}, "eggs": {"per": 0.1, "default": 15}, "mikan": {"per": 1, "default": None}}}


class Summary(unittest.TestCase):
    def test_months_back(self):
        self.assertEqual(ms.months_back("2026-01", 1), "2025-12")
        self.assertEqual(ms.months_back("2026-09", 60), "2021-09")

    def test_latest_month(self):
        self.assertEqual(ms.latest_month(PRICES), "2026-09")

    def test_basket_cost_uses_defaults_and_household(self):
        # 2 adults: rice 5 kg = 1 bag, eggs 30 = 3 packs
        self.assertAlmostEqual(ms.basket_cost(PRICES, BASKET, "2026-09"), 3550 + 3 * 322)

    def test_fixed_items_do_not_scale_with_people(self):
        prices = {"items": [item("electricity", [["2026-09", 12000.0]])]}
        basket = {"household": {"adults": 3, "children": 1}, "child_factor": 0.6,
                  "items": {"electricity": {"per": 1, "default": 1, "fixed": True}}}
        self.assertEqual(ms.basket_cost(prices, basket, "2026-09"), 12000.0)

    def test_carry_forward_limit(self):
        self.assertEqual(ms.price_with_carry(dict(PRICES["items"][2]["series"]["nagoya"]), "2026-09"), 930.0)
        self.assertIsNone(ms.price_with_carry({"2025-01": 1.0}, "2026-09"))

    def test_movers(self):
        ups, downs = ms.movers(PRICES, "2026-09", 12)
        self.assertEqual([i["id"] for _, i in ups], ["eggs"])
        self.assertEqual([i["id"] for _, i in downs], ["rice"])

    def test_seasonal_for(self):
        cheap, dear = ms.seasonal_for(PRICES, 10)  # November
        self.assertEqual([i["id"] for _, i in cheap], ["mikan"])
        self.assertEqual(ms.seasonal_for(PRICES, 6), ([], []))  # July: not surveyed

    def test_news_lines_only_for_current_month(self):
        ins = {"month": "2026-09", "items": {"rice": {"headlines": [
            {"title": "コメ価格が下落", "url": "https://n/1", "source": "NHK", "date": "2026-10-01"}]}}}
        self.assertEqual(ms.news_lines(ins, PRICES, "en"),
                         ["- **Rice**: [コメ価格が下落](https://n/1) (NHK, 2026-10-01)"])
        self.assertEqual(ms.news_lines(dict(ins, month="2026-08"), PRICES, "en"), [])
        text = ms.summary(PRICES, BASKET, None, today=datetime(2026, 10, 26), insights=ins)
        self.assertIn("**Related news**", text)
        self.assertIn("**関連ニュース**", text)

    def test_outlook_lines(self):
        ol = {"edition": "2026-11", "track_record": {"same_direction": 0.853, "since": "2023-07"},
              "items": {"rice": {"score": 2}, "eggs": {"score": -1}, "mikan": {"score": 0}}}
        en = ms.outlook_lines(ol, PRICES, "en")[0]
        self.assertIn("November 2026", en)
        self.assertIn("likely higher: Rice; likely lower: Eggs", en)
        self.assertIn("right about the direction 85% of the time since 2023-07", en)
        self.assertIn("高くなりそう: rice", ms.outlook_lines(ol, PRICES, "ja")[0])
        self.assertEqual(ms.outlook_lines({"edition": "2026-11", "items": {"rice": {"score": 0}}}, PRICES, "en"), [])

    def test_summary_text(self):
        text = ms.summary(PRICES, BASKET, None, today=datetime(2026, 10, 26))
        self.assertIn("## September 2026", text)
        self.assertIn("## 2026年9月", text)
        self.assertIn("Seasonal guide for November", text)
        self.assertIn("Mikan (-17%)", text)
        self.assertEqual(ms.title("2026-09"), "Nagoya prices: September 2026 / 名古屋の物価 2026年9月")


if __name__ == "__main__":
    unittest.main()
