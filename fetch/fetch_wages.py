"""Fetch Aichi's average scheduled monthly earnings (所定内給与額) by year and write docs/data/wages.json.

The Basic Survey on Wage Structure is split into tables before and from 2020 (令和元年以前 / 令和２年以降),
so this finds every matching prefecture table, picks the Aichi + 'total' cell in each, and merges the years.

Usage:
    ESTAT_APP_ID=... python fetch/fetch_wages.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import api_get, as_list, class_objects, fetch_meta, fetch_table, parse_number, text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "fetch" / "wages.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "wages.json"

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


def candidate_tables(app_id: str, config: dict) -> list[str]:
    found = list(config.get("known_tables", []))
    for word in config["search_words"]:
        data = api_get("getStatsList", {"appId": app_id, "statsCode": config["stats_code"], "searchWord": word, "limit": 500})
        for t in as_list(data["GET_STATS_LIST"].get("DATALIST_INF", {}).get("TABLE_INF")):
            title = text(t.get("TITLE")) + " " + text(t.get("STATISTICS_NAME"))
            if all(w in title for w in config["title_must"]) and not any(w in title for w in config["title_exclude"]):
                found.append(t["@id"])
    return list(dict.fromkeys(found))


def main() -> None:
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        raise SystemExit("Set ESTAT_APP_ID")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    years: dict[int, float] = {}
    sources = []
    for tid in candidate_tables(app_id, config):
        meta = fetch_meta(app_id, tid)
        cells = resolve_cells(class_objects(meta), config)
        title = text(meta.get("TABLE_INF", {}).get("TITLE"))
        if not cells:
            print(f"  skip {tid} {title}")
            continue
        filters = {f"cd{k.capitalize()}": e["@code"] for k, e in cells.items()}
        got = extract(fetch_table(app_id, tid, filters), cells)
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
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {len(years)} years: {out['points'][0]} .. {out['points'][-1]}")


if __name__ == "__main__":
    main()
