import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fetch"))

import fetch_wages as fw  # noqa: E402

CONFIG = json.loads((ROOT / "fetch" / "wages.json").read_text(encoding="utf-8"))
CLASSES = {
    "tab": [{"@code": "40", "@name": "きまって支給する現金給与額"}, {"@code": "41", "@name": "所定内給与額"}],
    "cat01": [{"@code": "1", "@name": "男女計"}, {"@code": "2", "@name": "男"}],
    "cat02": [{"@code": "01", "@name": "年齢計"}, {"@code": "02", "@name": "～19歳"}],
    "cat04": [{"@code": "T1", "@name": "Ｔ１ 産業計"}, {"@code": "E", "@name": "Ｅ 製造業"}],
    "area": [{"@code": "22000", "@name": "静岡県"}, {"@code": "23000", "@name": "愛知県"}],
    "time": [{"@code": "2019000000"}],
}


class Wages(unittest.TestCase):
    def test_resolve_cells_picks_aichi_tab_and_totals(self):
        cells = fw.resolve_cells(CLASSES, CONFIG)
        self.assertEqual({k: e["@code"] for k, e in cells.items()},
                         {"tab": "41", "cat01": "1", "cat02": "01", "cat04": "T1", "area": "23000"})

    def test_resolve_cells_rejects_table_without_aichi(self):
        classes = dict(CLASSES, area=[{"@code": "22000", "@name": "静岡県"}])
        self.assertIsNone(fw.resolve_cells(classes, CONFIG))

    def test_parse_year(self):
        self.assertEqual(fw.parse_year("2019000000"), 2019)
        self.assertEqual(fw.parse_year("20190000000"), 2019)   # the longer form seen in some tables
        self.assertIsNone(fw.parse_year("2019000101"))

    def test_extract_only_selected_cell(self):
        cells = fw.resolve_cells(CLASSES, CONFIG)
        base = {"@tab": "41", "@cat01": "1", "@cat02": "01", "@cat04": "T1", "@area": "23000"}
        stat = {"DATA_INF": {"VALUE": [
            dict(base, **{"@time": "2019000000", "$": "312.5"}),
            dict(base, **{"@time": "2018000000", "$": "309.0"}),
            dict(base, **{"@area": "22000", "@time": "2019000000", "$": "290.0"}),
            dict(base, **{"@cat01": "2", "@time": "2019000000", "$": "340.0"}),
        ]}}
        self.assertEqual(fw.extract(stat, cells), {2019: 312.5, 2018: 309.0})


    def test_merge_tabs_combines_years_split_across_codes(self):
        cells = fw.resolve_cells(CLASSES, CONFIG)
        base = {"@cat01": "1", "@cat02": "01", "@cat04": "T1", "@area": "23000"}
        stat = {"DATA_INF": {"VALUE": [
            dict(base, **{"@tab": "10", "@time": "2021000000", "$": "300"}),
            dict(base, **{"@tab": "10", "@time": "2022000000", "$": "301"}),
            dict(base, **{"@tab": "10", "@time": "2023000000", "$": "999"}),  # overlap: newer code wins
            dict(base, **{"@tab": "42", "@time": "2020000000", "$": "299"}),
            dict(base, **{"@tab": "42", "@time": "2023000000", "$": "305"}),
            dict(base, **{"@tab": "42", "@time": "2024000000", "$": "308"}),
        ]}}
        tabs = [{"@code": "10", "@name": "所定内給与額"}, {"@code": "42", "@name": "所定内給与額"}]
        self.assertEqual(fw.merge_tabs(stat, cells, tabs),
                         {2020: 299.0, 2021: 300.0, 2022: 301.0, 2023: 305.0, 2024: 308.0})

    def test_all_prefectures(self):
        cells = fw.resolve_cells(CLASSES, CONFIG)
        base = {"@tab": "41", "@cat01": "1", "@cat02": "01", "@cat04": "T1"}
        stat = {"DATA_INF": {"VALUE": [
            dict(base, **{"@area": "23000", "@time": "2023000000", "$": "320"}),
            dict(base, **{"@area": "22000", "@time": "2023000000", "$": "300"}),
        ]}}
        out = fw.all_prefectures(stat, cells, [{"@code": "41", "@name": "所定内給与額"}], "area", CLASSES["area"])
        self.assertEqual(out, {"愛知県": {2023: 320.0}, "静岡県": {2023: 300.0}})
        self.assertEqual(fw.pref_name("２３ 愛知"), "愛知")


if __name__ == "__main__":
    unittest.main()


JOB_CLASSES = {
    "tab": [{"@code": "10", "@name": "所定内給与額"}, {"@code": "40", "@name": "きまって支給する現金給与額"},
            {"@code": "42", "@name": "所定内給与額"}],
    "cat01": [{"@code": "01", "@name": "男女計"}, {"@code": "02", "@name": "男"}],
    "cat02": [{"@code": "010", "@name": "管理的職業従事者"}, {"@code": "1133", "@name": "看護師"},
              {"@code": "9999", "@name": "不詳"}],
    "area": [{"@code": "00000", "@name": "全国"}, {"@code": "23000", "@name": "愛知県"}],
    "time": [{"@code": "2023000000"}],
}


class WageBreakdowns(unittest.TestCase):
    def test_plan_breaks_down_jobs_and_fixes_totals(self):
        plan = fw.plan_breakdown(JOB_CLASSES, "管理的職業従事者", "愛知", "所定内給与額")
        self.assertEqual(plan, {"vary_key": "cat02", "area_key": "area", "tab_codes": ["10", "42"], "fixed": {"cat01": "01"}})

    def test_plan_breaks_down_industries(self):
        plan = fw.plan_breakdown(CLASSES, "産業計", "愛知", "所定内給与額")
        self.assertEqual(plan["vary_key"], "cat04")
        self.assertEqual(plan["fixed"], {"cat01": "1", "cat02": "01"})

    def test_plan_rejects_table_without_the_breakdown(self):
        self.assertIsNone(fw.plan_breakdown(JOB_CLASSES, "産業計", "愛知", "所定内給与額"))

    def test_collect_merges_tabs_and_ignores_other_cells(self):
        plan = fw.plan_breakdown(JOB_CLASSES, "管理的職業従事者", "愛知", "所定内給与額")
        def v(value, **kw):
            return {"@cat01": "01", "@area": "23000", "@cat02": "1133", "$": value, **{f"@{k}": x for k, x in kw.items()}}
        stat = {"DATA_INF": {"VALUE": [
            v("300.0", tab="10", time="2020000000"),
            v("320.0", tab="42", time="2023000000"),
            v("400.0", tab="40", time="2023000000"),           # other pay item
            v("350.0", tab="42", time="2022000000", cat01="02"),  # men only
            v("-", tab="42", time="2022000000"),               # suppressed cell
            v("310.0", tab="42", time="2021000000", area="00000"),
        ]}}
        self.assertEqual(fw.collect(stat, plan), {("23000", "1133"): {2020: 300.0, 2023: 320.0},
                                                  ("00000", "1133"): {2021: 310.0}})

    def test_industry_key(self):
        self.assertEqual(fw.industry_key("Ｅ３１ 輸送用機械器具製造業"), ("E31", "輸送用機械器具製造業"))
        self.assertEqual(fw.industry_key("Ｉ５０～５５ 卸売業"), ("I50-55", "卸売業"))
        self.assertEqual(fw.industry_key("Ｄ 建設業"), ("D", "建設業"))
        self.assertIsNone(fw.industry_key("Ｔ１ 産業計"))

    def test_job_key_and_parents(self):
        self.assertIsNone(fw.job_key("9999", "不詳"))
        groups = fw.json.loads((ROOT / "fetch" / "wages.json").read_text(encoding="utf-8"))["breakdowns"]["job"]["groups"]
        self.assertEqual(fw.entry_parent("job", "1133", groups), "j:020")
        self.assertEqual(fw.entry_parent("job", "1513", groups), "j:080")
        self.assertIsNone(fw.entry_parent("job", "020", groups))
        self.assertEqual(fw.entry_parent("industry", "E31", []), "i:E")
        self.assertIsNone(fw.entry_parent("industry", "E", []))

    def test_catalog_entries_have_english_names(self):
        path = ROOT / "docs" / "data" / "wages" / "catalog.json"
        if not path.exists():
            self.skipTest("no catalog yet")
        catalog = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual([e["id"] for e in catalog["entries"] if not e.get("en")], [])
        for e in catalog["entries"]:
            if e["parent"]:
                self.assertIn(e["parent"], {x["id"] for x in catalog["entries"]})
