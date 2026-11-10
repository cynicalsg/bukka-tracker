"""Temporary: print the layout of the wage survey's prefecture tables (jobs, newest years). Removed after use."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import api_get, as_list, class_objects, fetch_meta, text  # noqa: E402

app_id = os.environ["ESTAT_APP_ID"]
seen = {}
for word in ["都道府県別", "職種"]:
    data = api_get("getStatsList", {"appId": app_id, "statsCode": "00450091", "searchWord": word, "limit": 1000})
    for t in as_list(data["GET_STATS_LIST"].get("DATALIST_INF", {}).get("TABLE_INF")):
        seen[t["@id"]] = (text(t.get("TITLE")), text(t.get("STATISTICS_NAME")), t.get("SURVEY_DATE"), t.get("UPDATED_DATE"))
print(f"{len(seen)} tables")
for tid, (title, stat, survey, upd) in sorted(seen.items()):
    if "都道府県" in title or "都道府県" in stat:
        print(f"T {tid} | {stat} | {title} | survey {survey} | updated {upd}")
for tid, (title, stat, survey, upd) in sorted(seen.items()):
    full = title + " " + stat
    if "都道府県" not in full or not ("職種" in full or "年齢階級別DB" in full or "産業" in full):
        continue
    if "令和２年以降" not in full and "令和元年以前" not in full:
        continue
    print(f"\n== {tid} {stat} {title}")
    try:
        classes = class_objects(fetch_meta(app_id, tid))
    except Exception as e:  # keep going
        print("  meta failed", e)
        continue
    for k, es in classes.items():
        names = [f"{e['@code']}:{e.get('@name', '')}" for e in es]
        if k == "time" or len(names) <= 20:
            print(f"  {k} ({len(names)}): {names}")
        else:
            print(f"  {k} ({len(names)}): {names[:200]}")
