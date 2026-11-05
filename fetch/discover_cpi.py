"""One-off helper: list e-Stat CPI tables that might hold Nagoya's monthly food index.

Prints candidate tables and, for the likeliest ones, whether they include 名古屋市 and which
food-related categories they have. Output goes to the workflow log only.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_prices import api_get, as_list, class_objects, text  # noqa: E402

CPI_STATS_CODE = "00200573"  # 消費者物価指数


def main() -> None:
    app_id = os.environ["ESTAT_APP_ID"]
    seen = {}
    for word in ("都市別", "中分類指数", "食料"):
        data = api_get("getStatsList", {"appId": app_id, "statsCode": CPI_STATS_CODE, "searchWord": word, "limit": 200})
        for t in as_list(data["GET_STATS_LIST"].get("DATALIST_INF", {}).get("TABLE_INF")):
            seen[t["@id"]] = t
    print(f"{len(seen)} CPI tables found")
    rows = sorted(seen.values(), key=lambda t: text(t.get("UPDATED_DATE")), reverse=True)
    for t in rows:
        print(f"  {t['@id']}  [{text(t.get('CYCLE'))}] {text(t.get('STATISTICS_NAME'))} / {text(t.get('TITLE'))}"
              f"  updated {text(t.get('UPDATED_DATE'))}")

    likely = [t for t in rows if text(t.get("CYCLE")) == "月次"
              and any(w in text(t.get("TITLE")) + text(t.get("STATISTICS_NAME")) for w in ("都市", "市別", "地域"))]
    print(f"\nInspecting {min(len(likely), 8)} likely tables:")
    for t in likely[:8]:
        meta = api_get("getMetaInfo", {"appId": app_id, "statsDataId": t["@id"]})["GET_META_INFO"]
        if "METADATA_INF" not in meta:
            print(f"  {t['@id']}: no metadata ({meta['RESULT'].get('ERROR_MSG')})")
            continue
        classes = class_objects(meta["METADATA_INF"])
        print(f"\n  {t['@id']}  {text(t.get('TITLE'))}")
        for key, entries in classes.items():
            names = [e.get("@name", "") for e in entries]
            if key == "time":
                print(f"    time: {len(names)} periods, {names[-1] if names else ''} .. {names[0] if names else ''}")
            elif key == "area":
                print(f"    area: {len(names)} areas; Nagoya: {[ (e['@code'], e['@name']) for e in entries if '名古屋' in e.get('@name','')]}")
            else:
                food = [(e["@code"], e["@name"]) for e in entries if "食料" in e.get("@name", "") or "総合" in e.get("@name", "")]
                print(f"    {key}: {len(names)} entries, e.g. {names[:4]}; food/総合: {food[:8]}")


if __name__ == "__main__":
    main()
