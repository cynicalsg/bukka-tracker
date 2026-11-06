import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import fetch_outlook as fo  # noqa: E402

SAMPLE = """2.主要な野菜の生育、出荷及び価格の見通し
品目
だいこん
青森(36%)
北海道(30%)
北海道産・青森県産中心の出荷。千葉県産は長雨により
生育の遅れが発生しており、価格はやや平年を上回って推移する見込み。
<10月前半>
平年並みで推移
<10月後半>
やや平年を上回って推移
トマト 熊本(40%)
生育は順調で、10月の出荷数量・価格は
平年並みで推移する見込み。
平年並みで推移
(2/5)
たまねぎ
北海道(95%)
大玉傾向。価格は平年を下回って推移する見込み。
平年を下回って推移
レタス
茨城(57%)
平年を上回って推移
"""


class Outlook(unittest.TestCase):
    def test_score_of_needs_the_exact_phrase(self):
        self.assertEqual(fo.score_of("平年を上回って推移"), 2)
        self.assertEqual(fo.score_of("やや平年を上回って推移"), 1)
        self.assertEqual(fo.score_of("平年並みで推移"), 0)
        self.assertEqual(fo.score_of("やや平年を下回って推移"), -1)
        self.assertIsNone(fo.score_of("平年並みで推移する見込み。"))  # end of a reason sentence

    def test_parse_text(self):
        out = fo.parse_text(SAMPLE)
        self.assertEqual(set(out), {"daikon", "tomato", "onion"})          # レタス isn't tracked
        self.assertEqual(out["daikon"]["score"], 0.5)                       # halves averaged
        self.assertEqual(out["daikon"]["verdict_ja"], "10月前半: 平年並みで推移 / 10月後半: やや平年を上回って推移")
        self.assertIn("長雨により", out["daikon"]["reason_ja"])
        self.assertNotIn("北海道(30%)", out["daikon"]["reason_ja"])         # region shares dropped
        self.assertTrue(out["tomato"]["reason_ja"].endswith("平年並みで推移する見込み。"))
        self.assertEqual(out["tomato"]["verdict_ja"], "平年並みで推移")
        self.assertEqual(out["onion"]["score"], -2)

    def test_track_record(self):
        food = {f"{y}-11": 100.0 for y in range(2020, 2027)}
        prices = {"cabbage": {f"{y}-11": 200.0 for y in range(2021, 2026)}}
        prices["cabbage"]["2026-11"] = 260.0                               # 30% above its 5-year average
        prices["onion"] = {f"{y}-11": 300.0 for y in range(2021, 2026)}
        prices["onion"]["2026-11"] = 330.0                                 # +10%, but the outlook said down
        history = {"2026-11": {"cabbage": 2, "onion": -2, "tomato": 0}}
        tr = fo.track_record(history, prices, food)
        self.assertEqual(tr["calls"], 2)
        self.assertEqual(tr["same_direction"], 0.5)
        self.assertEqual(tr["up"]["n"], 1)
        self.assertAlmostEqual(tr["up"]["median_change"], 0.3)
        self.assertEqual(tr["by_item"]["onion"], {"n": 1, "right": 0})


if __name__ == "__main__":
    unittest.main()
