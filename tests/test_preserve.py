import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = json.loads((ROOT / "docs" / "preserve.json").read_text(encoding="utf-8"))
ITEMS = {i["id"] for i in json.loads((ROOT / "fetch" / "items.json").read_text(encoding="utf-8"))["items"]}


class PreserveLibrary(unittest.TestCase):
    def test_guides_are_complete_and_bilingual(self):
        ids = [g["id"] for g in LIB["guides"]]
        self.assertEqual(len(ids), len(set(ids)), "guide ids must be unique")
        for g in LIB["guides"]:
            with self.subTest(guide=g["id"]):
                self.assertTrue(g["items"] and set(g["items"]) <= ITEMS, "items must exist in fetch/items.json")
                self.assertIn(g["method"], LIB["methods"])
                for key in ("title", "needs", "keeps"):
                    self.assertTrue(g[f"{key}_ja"].strip() and g[f"{key}_en"].strip())
                self.assertEqual(len(g["steps_ja"]), len(g["steps_en"]))
                self.assertGreaterEqual(len(g["steps_ja"]), 2)
                self.assertEqual("note_ja" in g, "note_en" in g)
                if "veranda" in g:
                    self.assertIn(g["veranda"], ("south", "east", "north"))
                    self.assertTrue(g["veranda_ja"] and g["veranda_en"])
                text = json.dumps(g, ensure_ascii=False)
                self.assertNotRegex(text, r"<[a-zA-Z/]|https?://", "plain text only")

    def test_every_seasonal_item_has_a_guide(self):
        prices = json.loads((ROOT / "docs" / "data" / "prices.json").read_text(encoding="utf-8"))
        seasonal = {i["id"] for i in prices["items"] if i.get("seasonal", {}).get("amplitude", 0) >= 0.10}
        covered = {item for g in LIB["guides"] for item in g["items"]}
        self.assertEqual(seasonal - covered, set())

    def test_safety_block(self):
        s = LIB["safety"]
        self.assertEqual(len(s["ja"]), len(s["en"]))
        self.assertTrue(re.match(r"^https://www\.maff\.go\.jp/", s["source"]["url"]))


if __name__ == "__main__":
    unittest.main()
