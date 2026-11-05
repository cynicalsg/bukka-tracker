import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import fetch_cpi as fc  # noqa: E402

CONFIG = json.loads((ROOT / "fetch" / "cpi.json").read_text(encoding="utf-8"))

META = {"CLASS_INF": {"CLASS_OBJ": [
    {"@id": "tab", "CLASS": [{"@code": "1", "@name": "指数"}, {"@code": "3", "@name": "前年同月比"}]},
    {"@id": "cat01", "CLASS": [{"@code": "0001", "@name": "0001 総合"}, {"@code": "0002", "@name": "0002 食料"},
                               {"@code": "0042", "@name": "0042 外食"}]},
    {"@id": "area", "CLASS": [{"@code": "13100", "@name": "13100 東京都区部"}, {"@code": "23100", "@name": "23100 名古屋市"}]},
]}}

STAT = {"DATA_INF": {"VALUE": [
    {"@tab": "1", "@cat01": "0002", "@area": "23100", "@time": "2026000909", "$": "112.4"},
    {"@tab": "1", "@cat01": "0002", "@area": "23100", "@time": "2026000808", "$": "111.9"},
    {"@tab": "3", "@cat01": "0002", "@area": "23100", "@time": "2026000909", "$": "6.1"},   # wrong tab
    {"@tab": "1", "@cat01": "0002", "@area": "13100", "@time": "2026000909", "$": "113.0"},  # wrong area
    {"@tab": "1", "@cat01": "0002", "@area": "23100", "@time": "2026000000", "$": "110.0"},  # annual
    {"@tab": "1", "@cat01": "0001", "@area": "23100", "@time": "2026000909", "$": "-"},       # missing
]}}


class CPI(unittest.TestCase):
    def test_bare_name(self):
        self.assertEqual(fc.bare_name("0002 食料"), "食料")

    def test_pick_codes_falls_back_to_food(self):
        codes = fc.pick_codes(META, CONFIG)
        self.assertEqual(codes["area"]["@code"], "23100")
        self.assertEqual(codes["tab"]["@code"], "1")
        self.assertEqual(codes["series"]["food"]["@code"], "0002")  # no groceries-only index in META
        self.assertEqual(codes["series"]["all"]["@code"], "0001")

    def test_build_keeps_only_monthly_index_for_nagoya(self):
        cpi = fc.build_cpi(STAT, fc.pick_codes(META, CONFIG), CONFIG)
        self.assertEqual(cpi["series"]["food"]["points"], [["2026-08", 111.9], ["2026-09", 112.4]])
        self.assertEqual(cpi["series"]["all"]["points"], [])
        self.assertEqual(cpi["series"]["food"]["estat_name"], "食料")


if __name__ == "__main__":
    unittest.main()
