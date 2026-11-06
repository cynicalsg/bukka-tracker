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


import check_insights as ci  # noqa: E402


class KeepExplained(unittest.TestCase):
    def test_same_month_keeps_explanations_and_frozen_headlines(self):
        old = {"month": "2026-09", "explained": {"by": "x"}, "items": {"tomato": {
            "headlines": [{"title": "A", "url": "https://a", "title_en": "A en"}],
            "summary_ja": "雨で高い[1]", "summary_en": "Rain [1]", "mom": 10}}}
        new = {"month": "2026-09", "items": {"tomato": {
            "headlines": [{"title": "B", "url": "https://b"}], "summary_ja": None, "summary_en": None, "mom": 20}}}
        out = fi.keep_explained(new, old)
        self.assertEqual(out["items"]["tomato"]["headlines"][0]["title"], "A")
        self.assertEqual(out["items"]["tomato"]["summary_en"], "Rain [1]")
        self.assertEqual(out["items"]["tomato"]["mom"], 20)          # numbers refreshed
        self.assertEqual(out["explained"], {"by": "x"})

    def test_new_month_starts_fresh(self):
        old = {"month": "2026-08", "items": {"tomato": {"headlines": [], "summary_ja": "x[1]", "summary_en": "x[1]"}}}
        new = {"month": "2026-09", "items": {"tomato": {"headlines": [], "summary_ja": None, "summary_en": None}}}
        self.assertIsNone(fi.keep_explained(new, old)["items"]["tomato"]["summary_ja"])


class CheckInsights(unittest.TestCase):
    def base(self, **item):
        heads = [{"title": "見出し1", "url": "https://1"}, {"title": "見出し2", "url": "https://2", "hide": True}]
        return {"items": {"x": dict({"headlines": heads, "summary_ja": None, "summary_en": None}, **item)}}

    def test_ok(self):
        self.assertEqual(ci.problems(self.base(summary_ja="雨の影響と報じられています[1]。",
                                               summary_en="Reports point to rain [1].")), [])

    def test_catches_mistakes(self):
        found = " | ".join(ci.problems(self.base(summary_ja="理由[2]", summary_en=None)))
        self.assertIn("both be filled", found)
        self.assertIn("hidden headline", found)
        found = " | ".join(ci.problems(self.base(summary_ja="理由", summary_en="See https://x [3]")))
        self.assertIn("cite at least one", found)
        self.assertIn("plain text only", found)
        self.assertIn("[3] doesn't exist", found)
        self.assertIn("max 200", " ".join(ci.problems(self.base(summary_ja="あ" * 201 + "[1]", summary_en="a [1]"))))


class ResolveLinks(unittest.TestCase):
    def test_decode_batchexecute(self):
        inner = json.dumps(["garturlres", "https://news.yahoo.co.jp/articles/abc", 1])
        text = ")]}'\n\n" + json.dumps([["wrb.fr", "Fbv4je", inner, None, None, None, "generic"], ["di", 10]])
        self.assertEqual(fi.decode_batchexecute(text), "https://news.yahoo.co.jp/articles/abc")
        self.assertIsNone(fi.decode_batchexecute("garbage"))

    def test_non_google_links_are_left_alone(self):
        self.assertIsNone(fi.resolve_google_news("https://news.yahoo.co.jp/articles/abc"))
