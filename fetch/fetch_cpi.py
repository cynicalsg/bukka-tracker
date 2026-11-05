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
    as_list, class_objects, fetch_meta, fetch_table, parse_month, parse_number, text,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "fetch" / "cpi.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "cpi.json"
CATALOG_PATH = ROOT / "docs" / "data" / "cpi_catalog.json"


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
    cats = {bare_name(e.get("@name", "")): e for e in classes.get("cat01", [])}
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


if __name__ == "__main__":
    main()
