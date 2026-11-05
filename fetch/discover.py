"""Temporary: find a national-average retail price table and Aichi's monthly wage table on e-Stat."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import api_get, as_list, class_objects, text  # noqa: E402

APP = os.environ["ESTAT_APP_ID"]


def tables(**params):
    data = api_get("getStatsList", {"appId": APP, "limit": 60, **params})
    return as_list(data["GET_STATS_LIST"].get("DATALIST_INF", {}).get("TABLE_INF"))


def show(ts, label):
    print(f"\n=== {label}: {len(ts)} tables")
    for t in ts[:40]:
        print(f"  {t['@id']} [{text(t.get('CYCLE'))}] {text(t.get('STAT_NAME'))} | {text(t.get('STATISTICS_NAME'))} | {text(t.get('TITLE'))} | {text(t.get('SURVEY_DATE'))}")


def meta(tid, words):
    m = api_get("getMetaInfo", {"appId": APP, "statsDataId": tid})["GET_META_INFO"]
    if "METADATA_INF" not in m:
        print(f"  {tid}: no metadata"); return
    print(f"\n--- {tid} {text(m['METADATA_INF'].get('TABLE_INF', {}).get('TITLE'))}")
    for k, es in class_objects(m["METADATA_INF"]).items():
        names = [e.get("@name", "") for e in es]
        hits = [n for n in names if any(w in n for w in words)]
        if k == "time":
            codes = sorted(e["@code"] for e in es); print(f"    time {len(codes)}: {codes[:1]}..{codes[-1:]}")
        else:
            print(f"    {k} ({len(names)}): {names[:5]} hits: {hits[:12]}")


# Wages: try likely statistics codes for the Monthly Labour Survey, and simpler searches.
seen = {}
for code in ("00450071", "00450072", "00450073", "00450091", "00450092", "00450093"):
    ts = tables(statsCode=code)
    show(ts, f"statsCode {code}")
    for t in ts:
        seen.setdefault(t["@id"], t)
for word in ("毎月勤労統計", "きまって支給する給与", "現金給与総額 愛知県"):
    ts = tables(searchWord=word)
    show(ts, f"search {word}")
    for t in ts:
        seen.setdefault(t["@id"], t)
aichi = [t["@id"] for t in seen.values() if "愛知" in text(t.get("TITLE")) + text(t.get("STATISTICS_NAME"))]
monthly = [t["@id"] for t in seen.values() if text(t.get("CYCLE")) == "月次"
           and any(w in text(t.get("TITLE")) for w in ("都道府県", "地方", "給与"))]
for tid in list(dict.fromkeys(aichi[:4] + monthly[:4])):
    meta(tid, ("愛知", "きまって", "現金給与", "調査産業計", "5人以上", "事業所規模"))
