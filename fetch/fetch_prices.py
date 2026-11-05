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
CATALOG_PATH = ROOT / "docs" / "data" / "catalog.json"
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
    by_city = [t for t in monthly if "都市別" in text(t.get("TITLE"))] or monthly
    chosen = by_city[0]["@id"]
    print(f"Using table {chosen}. Pin it as stats_data_id in fetch/items.json if this is wrong.")
    return chosen


def fetch_meta(app_id: str, stats_data_id: str) -> dict:
    """Return the table's metadata in the same shape as STATISTICAL_DATA (CLASS_INF, TABLE_INF)."""
    data = api_get("getMetaInfo", {"appId": app_id, "statsDataId": stats_data_id})["GET_META_INFO"]
    if data["RESULT"]["STATUS"] not in (0, "0"):
        raise SystemExit(f"e-Stat error: {data['RESULT'].get('ERROR_MSG')}")
    return data["METADATA_INF"]


def fetch_table(app_id: str, stats_data_id: str, filters: dict | None = None) -> dict:
    """Download a table (optionally filtered, e.g. {"cdArea": "23100,13100"}), following
    NEXT_KEY paging. Returns the merged STATISTICAL_DATA."""
    merged = None
    start = 1
    while True:
        data = api_get("getStatsData", {
            "appId": app_id, "statsDataId": stats_data_id,
            "startPosition": start, "limit": 100000, "metaGetFlg": "Y",
            **(filters or {}),
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


def find_item_dimension(classes: dict[str, list[dict]], items: list[dict]) -> str:
    """The item (品目/銘柄) dimension is the cat0x dimension that matches the most configured items."""
    scores = {key: sum(match_item(i, entries) is not None for i in items)
              for key, entries in classes.items() if key.startswith("cat")}
    best = max(scores, key=scores.get, default=None)
    if not best or scores[best] == 0:
        for key, entries in classes.items():
            print(f"  {key}: {[e.get('@name') for e in entries[:8]]}", file=sys.stderr)
        raise SystemExit(f"Could not find the item dimension among {list(classes)}")
    return best


def resolve_filters(meta: dict, config: dict) -> dict:
    """Turn configured areas/items into e-Stat code filters so we download only what we chart."""
    classes = class_objects(meta)
    item_dim = find_item_dimension(classes, config["items"])
    areas = [e["@code"] for e in classes.get("area", [])
             if any(a["match"] in e.get("@name", "") for a in config["areas"])]
    items = [hit["@code"] for i in config["items"] if (hit := match_item(i, classes[item_dim]))]
    filters = {"cd" + item_dim.capitalize(): ",".join(items)}
    if areas:
        filters["cdArea"] = ",".join(areas)
    return filters


def match_item(item: dict, entries: list[dict]) -> dict | None:
    if item.get("code"):
        return next((e for e in entries if e["@code"] == item["code"]), None)
    hits = [e for e in entries
            if all(w in e.get("@name", "") for w in item["match"])
            and not any(x in e.get("@name", "") for x in item.get("exclude", []))]
    return hits[0] if hits else None


def build_dataset(stat: dict, config: dict) -> dict:
    classes = class_objects(stat)
    item_dim = find_item_dimension(classes, config["items"])
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
            "category": item.get("category", ""),
            "unit_ja": item.get("unit_ja", ""), "unit_en": item.get("unit_en", ""),
            **{k: item[k] for k in ("note_ja", "note_en") if k in item},
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
        "categories": config.get("categories", []),
        "items": items_out,
    }


def dump_dataset(dataset: dict) -> str:
    """Compact JSON with one item per line, so monthly updates give readable diffs."""
    head = {k: v for k, v in dataset.items() if k != "items"}
    lines = ["{"] + [f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head.items()]
    items = [json.dumps(i, ensure_ascii=False, separators=(",", ":")) for i in dataset["items"]]
    lines += ['"items": [', ",\n".join(items), "]", "}"]
    return "\n".join(lines) + "\n"


def write_catalog(meta: dict) -> None:
    """Save every dimension of the table except time, so items and cities can be chosen by hand."""
    catalog = {key: [{k.lstrip("@"): v for k, v in e.items()} for e in entries]
               for key, entries in class_objects(meta).items() if key != "time"}
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote table catalog ({', '.join(f'{k}: {len(v)}' for k, v in catalog.items())}) to {CATALOG_PATH.relative_to(ROOT)}")


# ---------------------------------------------------------------- main

def main() -> None:
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        raise SystemExit("Set ESTAT_APP_ID (free from https://www.e-stat.go.jp/api/)")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    table_id = config.get("stats_data_id") or find_table(app_id, config["survey_stats_code"])
    meta = fetch_meta(app_id, table_id)
    write_catalog(meta)
    filters = resolve_filters(meta, config)
    print(f"Filters: {filters}")
    stat = fetch_table(app_id, table_id, filters)
    dataset = build_dataset(stat, config)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(dump_dataset(dataset), encoding="utf-8")
    n = sum(len(p) for i in dataset["items"] for p in i["series"].values())
    print(f"Wrote {len(dataset['items'])} items, {n} data points to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
