import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import build_pages as bp  # noqa: E402


class CityPages(unittest.TestCase):
    """If this fails after editing docs/index.html, run: python fetch/build_pages.py"""

    def test_pages_are_up_to_date(self):
        template = bp.TEMPLATE.read_text(encoding="utf-8")
        self.assertEqual(bp.apply_head(template, bp.head_tags(None), None), template, "root head is stale")
        index = json.loads(bp.INDEX.read_text(encoding="utf-8"))
        for city in index["cities"]:
            if city["id"] == index["default"]:
                continue
            with self.subTest(city=city["id"]):
                page = (bp.DOCS / city["id"] / "index.html").read_text(encoding="utf-8")
                self.assertEqual(page, bp.apply_head(template, bp.head_tags(city), city["id"]),
                                 "stale city page: run python fetch/build_pages.py")

    def test_city_page_head(self):
        page = bp.apply_head(bp.TEMPLATE.read_text(encoding="utf-8"),
                             bp.head_tags({"id": "osaka", "name_ja": "大阪市", "name_en": "Osaka"}), "osaka")
        self.assertIn('<base href="../">', page)
        self.assertIn('window.PRESET_CITY = "osaka"', page)
        self.assertIn("<title>大阪 物価トラッカー | Osaka Price Tracker</title>", page)
        self.assertIn('<link rel="canonical" href="https://cynicalsg.github.io/bukka-tracker/osaka/">', page)
        self.assertEqual(page.count("<title>"), 1)


if __name__ == "__main__":
    unittest.main()
