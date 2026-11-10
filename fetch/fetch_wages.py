"""Fetch average scheduled monthly earnings (所定内給与額) by prefecture and year and write docs/data/wages.json,
plus pay by industry and by job for each prefecture in docs/data/wages/.

The Basic Survey on Wage Structure is split into tables before and from 2020 (令和元年以前 / 令和２年以降),
so this finds every matching prefecture table, picks the Aichi + 'total' cell in each, and merges the years.
The industry and job breakdowns use the tables listed under "breakdowns" in fetch/wages.json.

Usage:
    ESTAT_APP_ID=... python fetch/fetch_wages.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import api_get, as_list, class_objects, fetch_meta, fetch_table, parse_number, text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "fetch" / "wages.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "wages.json"
LABELS_PATH = ROOT / "fetch" / "wage_labels.json"
BREAKDOWN_DIR = ROOT / "docs" / "data" / "wages"

TOTAL_WORDS = ("男女計", "年齢計", "産業計", "企業規模計", "学歴計", "雇用形態計", "就業形態計", "職種計", "計")


def pick_total(entries: list[dict]) -> dict | None:
    """The 'all' category of a dimension: the first whose name contains a total word, in priority order."""
    for word in TOTAL_WORDS:
        for e in entries:
            if word in e.get("@name", ""):
                return e
    return entries[0] if len(entries) == 1 else None


def resolve_cells(classes: dict[str, list[dict]], config: dict) -> dict | None:
    """Filters selecting Aichi, the scheduled-earnings tab, and the total of every other dimension.
    Returns None if the table doesn't have what we need."""
    filters = {}
    area_key = None
    for key, entries in classes.items():
        if key == "time":
            continue
        if any(config["area_match"] in e.get("@name", "") for e in entries):
            area_key = key
            hit = next(e for e in entries if config["area_match"] in e.get("@name", ""))
        elif key == "tab":
            hit = next((e for e in entries if config["tab_match"] in e.get("@name", "")), None)
        else:
            hit = pick_total(entries)
        if hit is None:
            return None
        filters[key] = hit
    if area_key is None or "tab" not in filters:
        return None
    return filters


def parse_year(code: str) -> int | None:
    m = re.match(r"^(\d{4})0{6,7}$", code)  # annual codes look like 2019000000 (some tables add a digit)
    return int(m.group(1)) if m else None


def extract(stat: dict, cells: dict) -> dict[int, float]:
    out = {}
    for v in as_list(stat["DATA_INF"]["VALUE"]):
        if any(v.get(f"@{k}") != e["@code"] for k, e in cells.items()):
            continue
        year, value = parse_year(v.get("@time", "")), parse_number(v.get("$"))
        if year and value is not None:
            out[year] = value
    return out


def merge_tabs(stat: dict, cells: dict, tabs: list[dict]) -> dict[int, float]:
    """Some tables list the pay item twice (e.g. codes 10 and 42) and spread the years across them
    (2021-2022 under one, 2020 and 2023 under the other). Combine them; where both have a year,
    the code with the most recent data wins."""
    results = [extract(stat, {**cells, "tab": tab}) for tab in tabs]
    results = sorted((r for r in results if r), key=lambda r: (max(r), len(r)))
    merged: dict[int, float] = {}
    for r in results:  # later (more recent) results overwrite earlier ones
        merged.update(r)
    return merged


def area_key_of(cells: dict, config: dict) -> str | None:
    return next((k for k, e in cells.items() if config["area_match"] in e.get("@name", "")), None)


def pref_name(name: str) -> str:
    """'２３ 愛知' / '愛知県' -> '愛知県' style name (leading codes dropped)."""
    return re.sub(r"^[\d０-９\s]+", "", name).strip()


def all_prefectures(stat: dict, cells: dict, tabs: list[dict], area_key: str, areas: list[dict]) -> dict[str, dict[int, float]]:
    """Same cells as Aichi's, for every prefecture in the table."""
    out = {}
    for a in areas:
        got = merge_tabs(stat, {**cells, area_key: a}, tabs)
        if got:
            out[pref_name(a.get("@name", ""))] = got
    return out


def candidate_tables(app_id: str, config: dict) -> list[str]:
    found = list(config.get("known_tables", []))
    for word in config["search_words"]:
        data = api_get("getStatsList", {"appId": app_id, "statsCode": config["stats_code"], "searchWord": word, "limit": 500})
        for t in as_list(data["GET_STATS_LIST"].get("DATALIST_INF", {}).get("TABLE_INF")):
            title = text(t.get("TITLE")) + " " + text(t.get("STATISTICS_NAME"))
            if all(w in title for w in config["title_must"]) and not any(w in title for w in config["title_exclude"]):
                found.append(t["@id"])
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- pay by industry and by job

def plan_breakdown(classes: dict[str, list[dict]], vary: str, area_match: str, tab_match: str) -> dict | None:
    """Which dimension to break down (the one with an entry named `vary`), the area dimension, the pay tab
    codes, and the total of every other dimension. None if the table doesn't fit."""
    keys = [k for k in classes if k != "time"]
    vary_key = next((k for k in keys if k != "tab" and any(vary in e.get("@name", "") for e in classes[k])), None)
    area_key = next((k for k in keys if k != "tab" and any(area_match in e.get("@name", "") for e in classes[k])), None)
    tab_codes = [e["@code"] for e in classes.get("tab", []) if tab_match in e.get("@name", "")]
    if not vary_key or not area_key or not tab_codes:
        return None
    fixed = {}
    for k in keys:
        if k in ("tab", vary_key, area_key):
            continue
        hit = pick_total(classes[k])
        if hit is None:
            return None
        fixed[k] = hit["@code"]
    return {"vary_key": vary_key, "area_key": area_key, "tab_codes": tab_codes, "fixed": fixed}


def collect(stat: dict, plan: dict) -> dict[tuple[str, str], dict[int, float]]:
    """{(area code, breakdown code): {year: value}}, merging duplicate pay tabs like merge_tabs."""
    per: dict[tuple[str, str], dict[str, dict[int, float]]] = {}
    for v in as_list(stat["DATA_INF"]["VALUE"]):
        if any(v.get(f"@{k}") != c for k, c in plan["fixed"].items()) or v.get("@tab") not in plan["tab_codes"]:
            continue
        year, value = parse_year(v.get("@time", "")), parse_number(v.get("$"))
        if year and value is not None:
            key = (v.get(f"@{plan['area_key']}"), v.get(f"@{plan['vary_key']}"))
            per.setdefault(key, {}).setdefault(v["@tab"], {})[year] = value
    out = {}
    for key, tabs in per.items():
        merged: dict[int, float] = {}
        for r in sorted(tabs.values(), key=lambda r: (max(r), len(r))):
            merged.update(r)
        out[key] = merged
    return out


def industry_key(name: str) -> tuple[str, str] | None:
    """'Ｅ３１ 輸送用機械器具製造業' -> ('E31', '輸送用機械器具製造業'); 'Ｉ５０～５５ 卸売業' -> ('I50-55', '卸売業').
    None for the all-industries total."""
    parts = name.strip().split(None, 1)
    if len(parts) != 2:
        return None
    code = unicodedata.normalize("NFKC", parts[0]).replace("~", "-")
    if not re.fullmatch(r"[A-Z]\d*(-\d+)?", code) or code == "T1":
        return None
    return code, parts[1].strip()


def job_key(code: str, name: str) -> tuple[str, str] | None:
    """Job codes as given ('010' for a major group, '1133' for a specific job); None for 不詳 (unknown)."""
    if code.startswith("999") or not name:
        return None
    return code, name.strip()


def entry_parent(kind: str, code: str, groups: list) -> str | None:
    if kind == "industry":
        return f"i:{code[0]}" if len(code) > 1 else None
    if len(code) == 4:
        n = int(code)
        return next((f"j:{g}" for g, lo, hi in groups if lo <= n <= hi), None)
    return None


def sort_key(entry: dict) -> tuple:
    code = entry["code"]
    if entry["kind"] == "industry":
        num = re.match(r"\d*", code[1:]).group(0)
        return (0, code[0], int(num) if num else -1)
    return (1, 1 if len(code) == 4 else 0, int(code))  # job groups first, then specific jobs


def fetch_breakdowns(app_id: str, config: dict) -> None:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    entries: dict[str, dict] = {}
    series: dict[str, dict[str, dict[int, float]]] = {}
    files: dict[str, str] = {}
    years: dict[str, list[int]] = {}
    for kind, spec in config["breakdowns"].items():
        if kind.startswith("_"):
            continue
        for tid in spec["tables"]:
            meta = fetch_meta(app_id, tid)
            classes = class_objects(meta)
            plan = plan_breakdown(classes, spec["vary"], config["area_match"], config["tab_match"])
            if not plan:
                print(f"  {kind}: skip {tid} (layout not recognised)")
                continue
            filters = {f"cd{k.capitalize()}": c for k, c in plan["fixed"].items()}
            filters["cdTab"] = ",".join(plan["tab_codes"])
            stat = fetch_table(app_id, tid, filters)
            areas = {e["@code"]: pref_name(e.get("@name", "")) for e in classes[plan["area_key"]]}
            names = {e["@code"]: e.get("@name", "") for e in classes[plan["vary_key"]]}
            got = collect(stat, plan)
            for (area, code), yv in got.items():
                key = industry_key(names.get(code, "")) if kind == "industry" else job_key(code, names.get(code, ""))
                if not key or area not in areas:
                    continue
                eid = f"{kind[0]}:{key[0]}"
                entries.setdefault(eid, {"id": eid, "kind": kind, "code": key[0], "ja": key[1],
                                         "en": labels.get(kind, {}).get(key[0]),
                                         "parent": entry_parent(kind, key[0], spec.get("groups", []))})
                files.setdefault(areas[area], area[:2])
                bucket = series.setdefault(areas[area], {}).setdefault(eid, {})
                for y, v in yv.items():
                    bucket.setdefault(y, v)  # first table wins if two overlap
                    years.setdefault(kind, []).append(y)
            print(f"  {kind}: use {tid} {text(meta.get('TABLE_INF', {}).get('TITLE'))}: "
                  f"{len({c for _, c in got})} categories, {len({a for a, _ in got})} areas")
    if not series:
        print("  breakdowns: no data")
        return
    missing = sorted(e["id"] for e in entries.values() if not e["en"])
    if missing:
        print(f"  breakdowns: no English name for {missing} (add them to fetch/wage_labels.json)")
    BREAKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    for pref, by_id in series.items():
        out = {"pref": pref, "series": {eid: [[y, yv[y]] for y in sorted(yv)] for eid, yv in sorted(by_id.items())}}
        (BREAKDOWN_DIR / f"{files[pref]}.json").write_text(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    catalog = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "years": {k: [min(v), max(v)] for k, v in years.items()},
        "prefs": dict(sorted(files.items(), key=lambda kv: kv[1])),
        "entries": sorted(entries.values(), key=sort_key),
    }
    (BREAKDOWN_DIR / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"  breakdowns: {len(entries)} industries and jobs, {len(series)} areas, years {catalog['years']}")


def main() -> None:
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        raise SystemExit("Set ESTAT_APP_ID")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    years: dict[int, float] = {}
    prefs: dict[str, dict[int, float]] = {}
    sources = []
    for tid in candidate_tables(app_id, config):
        meta = fetch_meta(app_id, tid)
        cells = resolve_cells(class_objects(meta), config)
        title = text(meta.get("TABLE_INF", {}).get("TITLE"))
        if not cells:
            print(f"  skip {tid} {title}")
            continue
        classes = class_objects(meta)
        for k, es in classes.items():  # log the table's shape, to check the choices above
            if k == "time":
                print(f"         time: {sorted(e['@code'] for e in es)}")
            elif len(es) <= 12 or k == "tab":
                print(f"         {k}: {[(e['@code'], e.get('@name', '')) for e in es][:15]}")
            else:
                print(f"         {k}: {len(es)} entries, e.g. {[e.get('@name', '') for e in es[:6]]}")
        tabs = [e for e in classes.get("tab", []) if config["tab_match"] in e.get("@name", "")]
        area_key = area_key_of(cells, config)
        filters = {f"cd{k.capitalize()}": e["@code"] for k, e in cells.items() if k != area_key}
        filters["cdTab"] = ",".join(e["@code"] for e in tabs)
        stat = fetch_table(app_id, tid, filters)
        got = merge_tabs(stat, cells, tabs)
        for pref, yv in all_prefectures(stat, cells, tabs, area_key, classes.get(area_key, [])).items():
            for y, v in yv.items():
                prefs.setdefault(pref, {}).setdefault(y, v)
        print(f"  use  {tid} {title}: {', '.join(e.get('@name', '') for e in cells.values())} -> "
              f"{min(got) if got else '-'}..{max(got) if got else '-'}")
        if got:
            sources.append({"stats_data_id": tid, "title": title})
            for y, v in got.items():
                years.setdefault(y, v)  # first table wins if two overlap
    if not years:
        raise SystemExit("No wage data found")
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "name_ja": config["name_ja"], "name_en": config["name_en"], "unit": "千円",
        "source": {"name_ja": "厚生労働省「賃金構造基本統計調査」(e-Stat)",
                   "name_en": "Ministry of Health, Labour and Welfare, Basic Survey on Wage Structure (e-Stat)",
                   "tables": sources},
        "break_year": 2020,
        "points": [[y, years[y]] for y in sorted(years)],
        "prefs": {k: [[y, v[y]] for y in sorted(v)] for k, v in sorted(prefs.items()) if k != "全国"},
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(years)} years: {out['points'][0]} .. {out['points'][-1]}; {len(out['prefs'])} prefectures")
    if config.get("breakdowns"):
        try:
            fetch_breakdowns(app_id, config)
        except (Exception, SystemExit) as e:  # the main pay line above is already saved
            print(f"  breakdowns failed: {e}")


if __name__ == "__main__":
    main()
