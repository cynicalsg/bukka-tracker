import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import fetch_insights as fi  # noqa: E402

CONFIG = json.loads((ROOT / "fetch" / "news.json").read_text(encoding="utf-8"))

FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>キャベツ価格が下落 好天で出荷増 - NHK</title><link>https://news.google.com/a1</link>
  <pubDate>Tue, 07 Oct 2026 03:00:00 GMT</pubDate><source url="https://nhk.or.jp">NHK</source></item>
<item><title>キャベツのおいしいレシピ - 料理サイト</title><link>https://news.google.com/a2</link>
  <pubDate>Wed, 15 Oct 2026 03:00:00 GMT</pubDate><source url="https://x">料理サイト</source></item>
<item><title>キャベツ価格が下落 好天で出荷増 - 地方紙</title><link>https://news.google.com/a3</link>
  <pubDate>Wed, 08 Oct 2026 03:00:00 GMT</pubDate><source url="https://y">地方紙</source></item>
<item><title>白菜が値上がり - 日経</title><link>https://news.google.com/a4</link>
  <pubDate>Thu, 09 Oct 2026 03:00:00 GMT</pubDate><source url="https://z">日経</source></item>
<item><title>No date キャベツ高騰</title><link>https://news.google.com/a5</link></item>
</channel></rss>""".encode()


class Insights(unittest.TestCase):
    def test_base_name_and_terms(self):
        self.assertEqual(fi.base_name("豚肉(国産・バラ)"), "豚肉")
        self.assertEqual(fi.search_terms({"id": "cabbage", "name_ja": "キャベツ"}, CONFIG), ("キャベツ 価格", ["キャベツ"]))
        q, must = fi.search_terms({"id": "rice", "name_ja": "米(コシヒカリ)"}, CONFIG)
        self.assertEqual(q, "コメ 価格")
        self.assertNotIn("米", must)  # 米 alone would match 米国 (the US)

    def test_window_and_url(self):
        self.assertEqual(fi.window("2026-09"), ("2026-08-01", "2026-11-01"))
        self.assertEqual(fi.window("2026-12"), ("2026-11-01", "2027-02-01"))
        self.assertIn("after%3A2026-08-01", fi.feed_url(CONFIG, "キャベツ 価格", "2026-09"))

    def test_parse_feed_strips_source_and_reads_date(self):
        entries = fi.parse_feed(FEED)
        self.assertEqual(entries[0], {"title": "キャベツ価格が下落 好天で出荷増", "source": "NHK",
                                      "url": "https://news.google.com/a1", "date": "2026-10-07"})
        self.assertEqual(entries[4]["date"], "")

    def test_pick_headlines_filters_dedupes_and_ranks_causes_first(self):
        picked = fi.pick_headlines(fi.parse_feed(FEED), ["キャベツ"], CONFIG["cause_words"], 4)
        titles = [e["title"] for e in picked]
        self.assertNotIn("白菜が値上がり", titles)                        # doesn't name the item
        self.assertEqual(titles.count("キャベツ価格が下落 好天で出荷増"), 1)  # duplicate story dropped
        self.assertEqual(titles[-1], "キャベツのおいしいレシピ")             # no cause word: last
        self.assertEqual(len(fi.pick_headlines(fi.parse_feed(FEED), ["キャベツ"], CONFIG["cause_words"], 1)), 1)

    def test_pick_headlines_needs_price_words_and_skips_noise(self):
        entries = [{"title": t, "source": "s", "url": "https://x/" + str(i), "date": ""} for i, t in enumerate([
            "歯磨き粉おすすめランキング 価格比較",   # noise word
            "歯磨きの正しい使い方",                  # no price word
            "歯磨き粉が値上げ 原材料高で",            # keep
        ])]
        picked = fi.pick_headlines(entries, ["歯磨き"], CONFIG["cause_words"], 4,
                                   CONFIG["price_words"], CONFIG["exclude_words"])
        self.assertEqual([e["title"] for e in picked], ["歯磨き粉が値上げ 原材料高で"])

    def test_mover_changes_match_page(self):
        def it(id_, pts):
            return {"id": id_, "name_en": id_, "name_ja": id_, "series": {"nagoya": pts}}
        prices = {"items": [it("a", [["2025-09", 100.0], ["2026-08", 100.0], ["2026-09", 130.0]]),
                            it("b", [["2025-09", 100.0], ["2026-08", 100.0], ["2026-09", 100.0]])]}
        changes = fi.mover_changes(prices)
        self.assertEqual(set(changes), {"a"})
        self.assertEqual((changes["a"]["mom"], changes["a"]["yoy"]), (30.0, 30.0))


if __name__ == "__main__":
    unittest.main()
