"""Fetch monthly retail prices from the e-Stat API (小売物価統計調査) and write docs/data/prices.json.

Usage:
    ESTAT_APP_ID=... python fetch/fetch_prices.py

Standard library only, so it runs on a bare GitHub Actions runner.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "fetch" / "items.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "prices.json"
API = "https://api.e-stat.go.jp/rest/3.0/app/json"

# e-Stat monthly time codes look like 2024000909 (year, "00", month, month).
MONTHLY_TIME = re.compile(r"^(\d{4})00(0[1-9]|1[0-2])\2$")


# ---------------------------------------------------------------- API calls

def api_get(endpoint: str, params: dict) -> dict:
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.load(resp)


def find_table(app_id: str, stats_code: str) -> str:
    """Find the monthly 'major items by city' table of the Retail Price Survey."""
    data = api_get("getStatsList", {
        "appId": app_id, "statsCode": stats_code,
        "searchWord": "主要品目 都市別 小売価格", "collectArea": "",
    })
    result = data["GET_STATS_LIST"]
    tables = as_list(result.get("DATALIST_INF", {}).get("TABLE_INF"))
    if not tables:
        raise SystemExit(f"No tables found: {result.get('RESULT')}")
    print("Candidate tables:")
    for t in tables[:20]:
        print(f"  {t['@id']}  {text(t.get('TITLE'))}  ({text(t.get('CYCLE'))})")
    monthly = [t for t in tables if text(t.get("CYCLE")) == "月次"] or tables
    # Prefer the most recently updated table.
    monthly.sort(key=lambda t: text(t.get("UPDATED_DATE")), reverse=True)
    chosen = monthly[0]["@id"]
    print(f"Using table {chosen}. Pin it as stats_data_id in fetch/items.json if this is wrong.")
    return chosen


def fetch_table(app_id: str, stats_data_id: str) -> dict:
    """Download a whole table, following NEXT_KEY paging. Returns the merged STATISTICAL_DATA."""
    merged = None
    start = 1
    while True:
        data = api_get("getStatsData", {
            "appId": app_id, "statsDataId": stats_data_id,
            "startPosition": start, "limit": 100000, "metaGetFlg": "Y",
        })["GET_STATS_DATA"]
        status = data["RESULT"]["STATUS"]
        if status not in (0, "0"):
            raise SystemExit(f"e-Stat error {status}: {data['RESULT'].get('ERROR_MSG')}")
        stat = data["STATISTICAL_DATA"]
        if merged is None:
            merged = stat
        else:
            merged["DATA_INF"]["VALUE"] = as_list(merged["DATA_INF"]["VALUE"]) + as_list(stat["DATA_INF"]["VALUE"])
        next_key = stat.get("RESULT_INF", {}).get("NEXT_KEY")
        if not next_key:
            return merged
        start = next_key


# ---------------------------------------------------------------- parsing

def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def text(x) -> str:
    """e-Stat fields are either plain strings or {'@code':..., '$': ...}."""
    if isinstance(x, dict):
        return str(x.get("$", ""))
    return "" if x is None else str(x)


def parse_month(code: str) -> str | None:
    m = MONTHLY_TIME.match(code)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def parse_number(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (AttributeError, ValueError):
        return None  # "-", "…", "***" etc. mean no data


def class_objects(stat: dict) -> dict[str, list[dict]]:
    return {obj["@id"]: as_list(obj.get("CLASS")) for obj in as_list(stat["CLASS_INF"]["CLASS_OBJ"])}


def find_item_dimension(classes: dict[str, list[dict]]) -> str:
    """The item (銘柄) dimension is a cat0x whose names include our food words."""
    for key, entries in classes.items():
        if key.startswith("cat") and any("牛乳" in e.get("@name", "") for e in entries):
            return key
    raise SystemExit(f"Could not find the item dimension among {list(classes)}")


def match_item(item: dict, entries: list[dict]) -> dict | None:
    if item.get("code"):
        return next((e for e in entries if e["@code"] == item["code"]), None)
    hits = [e for e in entries if all(w in e.get("@name", "") for w in item["match"])]
    return hits[0] if hits else None


def build_dataset(stat: dict, config: dict) -> dict:
    classes = class_objects(stat)
    item_dim = find_item_dimension(classes)
    area_entries = classes.get("area", [])

    area_codes = {}
    for area in config["areas"]:
        hit = next((e for e in area_entries if area["match"] in e.get("@name", "")), None)
        if hit is None:
            print(f"WARNING: area {area['match']} not in table", file=sys.stderr)
            continue
        area_codes[hit["@code"]] = area["id"]

    items_out, code_to_item = [], {}
    for item in config["items"]:
        hit = match_item(item, classes[item_dim])
        if hit is None:
            print(f"WARNING: no e-Stat item matches {item['id']} {item.get('match')}", file=sys.stderr)
            continue
        print(f"  {item['id']:<8} -> {hit['@code']} {hit['@name']}")
        entry = {
            "id": item["id"], "name_ja": item["name_ja"], "name_en": item["name_en"],
            "estat_code": hit["@code"], "estat_name": hit["@name"],
            "unit": hit.get("@unit", "円"),
            "series": {a["id"]: [] for a in config["areas"] if a["id"] in area_codes.values()},
        }
        items_out.append(entry)
        code_to_item[hit["@code"]] = entry

    for v in as_list(stat["DATA_INF"]["VALUE"]):
        entry = code_to_item.get(v.get(f"@{item_dim}"))
        area_id = area_codes.get(v.get("@area"))
        month = parse_month(v.get("@time", ""))
        price = parse_number(v.get("$"))
        if entry and area_id and month and price is not None:
            entry["series"][area_id].append([month, price])

    for entry in items_out:
        for points in entry["series"].values():
            points.sort()

    table = stat.get("TABLE_INF", {})
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name_ja": "総務省統計局「小売物価統計調査」(e-Stat)",
            "name_en": "Statistics Bureau of Japan, Retail Price Survey (e-Stat)",
            "stats_data_id": table.get("@id"),
            "table_title": text(table.get("TITLE")),
        },
        "areas": [{k: a[k] for k in ("id", "name_ja", "name_en")} for a in config["areas"]
                  if a["id"] in area_codes.values()],
        "items": items_out,
    }


# ---------------------------------------------------------------- main

def main() -> None:
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        raise SystemExit("Set ESTAT_APP_ID (free from https://www.e-stat.go.jp/api/)")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    table_id = config.get("stats_data_id") or find_table(app_id, config["survey_stats_code"])
    stat = fetch_table(app_id, table_id)
    dataset = build_dataset(stat, config)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n = sum(len(p) for i in dataset["items"] for p in i["series"].values())
    print(f"Wrote {len(dataset['items'])} items, {n} data points to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
