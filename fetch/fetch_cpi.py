"""Fetch Nagoya's Consumer Price Index (food and overall) from e-Stat and write docs/data/cpi.json.

Usage:
    ESTAT_APP_ID=... python fetch/fetch_cpi.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import (  # noqa: E402
    as_list, class_objects, fetch_meta, fetch_table, iter_table_values, parse_month, parse_number, text,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "fetch" / "cpi.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "cpi.json"
CATALOG_PATH = ROOT / "docs" / "data" / "cpi_catalog.json"
CITY_INDEX_PATH = ROOT / "docs" / "data" / "cities.json"
CITY_DIR = ROOT / "docs" / "data" / "cities"


def bare_name(name: str) -> str:
    """'0002 食料' -> '食料'"""
    return re.sub(r"^\S+\s+", "", name).strip()


def pick_codes(meta: dict, config: dict) -> dict:
    """Resolve the area, the index tab, and each series' category code from the table metadata."""
    classes = class_objects(meta)
    area = next((e for e in classes.get("area", []) if config["area_match"] in e.get("@name", "")), None)
    if area is None:
        raise SystemExit(f"Area {config['area_match']} not in CPI table")
    tab = next((e for e in classes.get("tab", []) if e.get("@name") == "指数"), None)
    cats = {}
    for e in classes.get("cat01", []):  # keep the first entry when a name repeats (e.g. 総合 0001 and 0201)
        cats.setdefault(bare_name(e.get("@name", "")), e)
    series = {}
    for s in config["series"]:
        hit = next((cats[c] for c in s["candidates"] if c in cats), None)
        if hit is None:
            print(f"WARNING: no CPI category matches {s['candidates']}", file=sys.stderr)
            continue
        print(f"  {s['id']:<5} -> {hit['@code']} {hit['@name']}")
        series[s["id"]] = hit
    return {"area": area, "tab": tab, "series": series}


def build_cpi(stat: dict, codes: dict, config: dict, table_title: str = "") -> dict:
    by_code = {e["@code"]: sid for sid, e in codes["series"].items()}
    points = {sid: [] for sid in codes["series"]}
    tab_code = codes["tab"]["@code"] if codes["tab"] else None
    for v in as_list(stat["DATA_INF"]["VALUE"]):
        sid = by_code.get(v.get("@cat01"))
        month = parse_month(v.get("@time", ""))
        value = parse_number(v.get("$"))
        if sid is None or month is None or value is None:
            continue
        if v.get("@area") != codes["area"]["@code"] or (tab_code and v.get("@tab") != tab_code):
            continue
        points[sid].append([month, value])
    cfg = {s["id"]: s for s in config["series"]}
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "name_ja": "総務省統計局「消費者物価指数」(e-Stat)",
            "name_en": "Statistics Bureau of Japan, Consumer Price Index (e-Stat)",
            "stats_data_id": config["stats_data_id"], "table_title": table_title,
        },
        "series": {
            sid: {"name_ja": cfg[sid]["name_ja"], "name_en": cfg[sid]["name_en"],
                  "estat_code": e["@code"], "estat_name": bare_name(e["@name"]),
                  "points": sorted(points[sid])}
            for sid, e in codes["series"].items()
        },
    }


def city_cpi_points(values, codes: dict, area_to_key: dict[str, str], since: str) -> dict[str, dict[str, list]]:
    """{area key: {series id: [[month, index]]}} for the index tab, from `since`."""
    by_code = {e["@code"]: sid for sid, e in codes["series"].items()}
    tab_code = codes["tab"]["@code"] if codes["tab"] else None
    out: dict[str, dict[str, list]] = {}
    for v in values:
        key, sid = area_to_key.get(v.get("@area")), by_code.get(v.get("@cat01"))
        month, value = parse_month(v.get("@time", "")), parse_number(v.get("$"))
        if key and sid and month and month >= since and value is not None and (not tab_code or v.get("@tab") == tab_code):
            out.setdefault(key, {}).setdefault(sid, []).append([month, value])
    return {k: {sid: sorted(p) for sid, p in v.items()} for k, v in out.items()}


def add_city_cpi(app_id: str, config: dict, meta: dict, codes: dict, since: str = "2000-01") -> None:
    """Add food and overall CPI to each city file; cities the CPI doesn't cover get the national index."""
    index = json.loads(CITY_INDEX_PATH.read_text(encoding="utf-8"))
    areas = {bare_name(e.get("@name", "")): e["@code"] for e in class_objects(meta).get("area", [])}
    area_to_key = {areas[c["name_ja"]]: c["id"] for c in index["cities"] if c["name_ja"] in areas}
    if "全国" in areas:
        area_to_key[areas["全国"]] = "national"
    filters = {"cdArea": ",".join(sorted(area_to_key)), "cdCat01": ",".join(e["@code"] for e in codes["series"].values()),
               "cdTimeFrom": f"{since[:4]}00{since[5:]}{since[5:]}"}
    if codes["tab"]:
        filters["cdTab"] = codes["tab"]["@code"]
    pts = city_cpi_points(iter_table_values(app_id, config["stats_data_id"], filters), codes, area_to_key, since)
    own = 0
    for c in index["cities"]:
        path = CITY_DIR / f"{c['id']}.json"
        if not path.exists():
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        source = "city" if c["id"] in pts else "national"
        own += source == "city"
        body["cpi"] = {"source": source, **pts.get(c["id"] if source == "city" else "national", {})}
        path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"City CPI: {own}/{len(index['cities'])} cities have their own index; the rest use the national one")


def main() -> None:
    app_id = os.environ.get("ESTAT_APP_ID")
    if not app_id:
        raise SystemExit("Set ESTAT_APP_ID")
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    meta = fetch_meta(app_id, config["stats_data_id"])
    CATALOG_PATH.write_text(json.dumps(
        [{"code": e["@code"], "name": e.get("@name"), "level": e.get("@level")} for e in class_objects(meta).get("cat01", [])],
        ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    codes = pick_codes(meta, config)
    filters = {"cdArea": codes["area"]["@code"], "cdCat01": ",".join(e["@code"] for e in codes["series"].values())}
    if codes["tab"]:
        filters["cdTab"] = codes["tab"]["@code"]
    print(f"Filters: {filters}")
    stat = fetch_table(app_id, config["stats_data_id"], filters)
    cpi = build_cpi(stat, codes, config, text(meta.get("TABLE_INF", {}).get("TITLE")))
    OUTPUT_PATH.write_text(json.dumps(cpi, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    for sid, s in cpi["series"].items():
        p = s["points"]
        print(f"  {sid}: {len(p)} months, {p[0] if p else '-'} .. {p[-1] if p else '-'}")
    if CITY_INDEX_PATH.exists():
        add_city_cpi(app_id, config, meta, codes)


if __name__ == "__main__":
    main()
