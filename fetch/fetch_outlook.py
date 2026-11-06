"""Fetch MAFF's monthly vegetable price outlook (野菜の生育状況及び価格見通し), keep a history of its
verdicts, and score that history against Nagoya's retail prices.

Writes:
- fetch/outlook_history.json  verdict scores per edition month and item (small; only new editions are downloaded)
- docs/data/outlook.json      the latest edition's verdicts and reasons, plus the track record

Scores: +2 above normal (平年を上回る), +1 slightly above (やや上回る), 0 normal, -1 / -2 below.
"Normal" is the 5-year average for that month at the Tokyo central wholesale markets.

Usage: python fetch/fetch_outlook.py      (needs: pip install pypdf)
"""
from __future__ import annotations

import html
import io
import json
import re
import statistics
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_insights import http_get  # noqa: E402
from monthly_summary import months_back  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LISTING = "https://www.maff.go.jp/j/seisan/ryutu/yasai_zyukyu/index.html"
HISTORY_PATH = ROOT / "fetch" / "outlook_history.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "outlook.json"
PRICES_PATH = ROOT / "docs" / "data" / "prices.json"
CPI_PATH = ROOT / "docs" / "data" / "cpi.json"

TRACKED = {"だいこん": "daikon", "にんじん": "carrot", "キャベツ": "cabbage", "ほうれんそう": "spinach",
           "ねぎ": "negi", "きゅうり": "cucumber", "トマト": "tomato", "ばれいしょ": "potato", "たまねぎ": "onion"}
OTHERS = ["はくさい", "レタス", "ブロッコリー", "なす", "ピーマン", "さといも", "かぼちゃ", "えだまめ", "スイートコーン"]
NAMES = list(TRACKED) + OTHERS
VERDICT = re.compile(r"^(やや)?平年(を上回って|を下回って|並みで|を上回る|を下回る|並み)(推移)?")
REGION = re.compile(r"^\S+[（(]\d+%[）)]$")      # 群馬(61%)
NOISE = re.compile(r"^[（(]\d+/\d+[）)]$|^<[^>]*>$")  # page markers, <10月前半>


def score_of(line: str) -> float | None:
    """Score a verdict line. Only the short verdict phrase itself counts, not a sentence ending in it."""
    m = VERDICT.fullmatch(line)
    if not m:
        return None
    base = {"を上回って": 2, "を上回る": 2, "を下回って": -2, "を下回る": -2, "並みで": 0, "並み": 0}[m.group(2)]
    return base / 2 if m.group(1) and base else base


def parse_text(text: str) -> dict[str, dict]:
    """Per tracked item: mean verdict score, the verdict lines, and the reason text (Japanese)."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in text.splitlines()]
    blocks: dict[str, dict] = {}
    current = None
    pending_label = None  # "<11月前半>" on its own line labels the next verdict
    for line in lines:
        if not line:
            continue
        first = line.split(" ")[0]
        if first in NAMES:
            current = first
            blocks.setdefault(current, {"scores": [], "verdicts": [], "reason": []})
            pending_label = None
            continue
        if current is None:
            continue
        label = re.match(r"^<([^>]*)>\s*(.*)$", line)
        if label and not label.group(2):
            pending_label = label.group(1)
            continue
        body = label.group(2) if label else line
        tag = label.group(1) if label else pending_label
        s = score_of(body)
        if s is not None:
            blocks[current]["scores"].append(s)
            blocks[current]["verdicts"].append((tag + ": " if tag else "") + body)
            pending_label = None
        elif not REGION.match(line) and not NOISE.match(line) and len(blocks[current]["scores"]) == 0:
            blocks[current]["reason"].append(line)
    out = {}
    for name, b in blocks.items():
        if name in TRACKED and b["scores"]:
            out[TRACKED[name]] = {"score": round(statistics.mean(b["scores"]), 2),
                                  "verdict_ja": " / ".join(b["verdicts"]),
                                  "reason_ja": "".join(b["reason"]).strip()}
    return out


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader  # imported here so the rest can be tested without pypdf
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)


def editions() -> list[tuple[str, str]]:
    """[(YYYY-MM, pdf url)] from the ministry's listing page, newest first."""
    page = http_get(LISTING).decode("utf-8", "replace")
    out = {}
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.S):
        txt = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        e = re.search(r"野菜の生育状況及び価格見通し[（(]令和(\d+)年(\d+)月[）)]", txt)
        if e:
            month = f"{2018 + int(e.group(1))}-{int(e.group(2)):02d}"
            out.setdefault(month, urllib.parse.urljoin(LISTING, m.group(1)))
    return sorted(out.items(), reverse=True)


# ---------------------------------------------------------------- track record

def real_deviation(prices: dict, food: dict, item: str, month: str) -> float | None:
    """Nagoya price in `month` vs its 5-year same-month average, with food inflation removed."""
    s = prices.get(item, {})
    p = s.get(month)
    past = [(s.get(months_back(month, 12 * k)), food.get(months_back(month, 12 * k))) for k in range(1, 6)]
    past = [a / b for a, b in past if a and b]
    if p is None or month not in food or len(past) < 3:
        return None
    return (p / food[month]) / statistics.mean(past) - 1


def track_record(history: dict, prices: dict, food: dict) -> dict:
    """How often Nagoya moved the way the outlook said, when it called a move."""
    calls = {"up": [], "down": []}
    by_item: dict[str, list[bool]] = {}
    months = set()
    for month, items in history.items():
        for item, score in items.items():
            if abs(score) < 0.5:
                continue
            d = real_deviation(prices, food, item, month)
            if d is None:
                continue
            key = "up" if score > 0 else "down"
            right = (d > 0) == (key == "up")
            calls[key].append((right, d))
            by_item.setdefault(item, []).append(right)
            months.add(month)
    summary = {k: {"n": len(v), "same_direction": round(sum(r for r, _ in v) / len(v), 3) if v else None,
                   "median_change": round(statistics.median(d for _, d in v), 3) if v else None}
               for k, v in calls.items()}
    total = calls["up"] + calls["down"]
    return {
        "calls": len(total),
        "same_direction": round(sum(r for r, _ in total) / len(total), 3) if total else None,
        "since": min(months) if months else None, "until": max(months) if months else None,
        **summary,
        "by_item": {k: {"n": len(v), "right": sum(v)} for k, v in sorted(by_item.items())},
        "method": "Nagoya retail price vs its 5-year same-month average, food CPI removed; called moves only",
    }


def main() -> None:
    try:
        history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        history = {}
    eds = editions()
    if not eds:
        raise SystemExit("No outlook editions found on the listing page")
    latest_month, latest_url = eds[0]
    latest = None
    for month, url in eds:
        if month in history and month != latest_month:
            continue
        try:
            parsed = parse_text(pdf_text(http_get(url, timeout=60)))
        except Exception as exc:  # noqa: BLE001 - one bad PDF shouldn't stop the rest
            print(f"  {month}: failed ({exc})")
            continue
        history[month] = {k: v["score"] for k, v in parsed.items()}
        if month == latest_month:
            latest = parsed
        print(f"  {month}: {len(parsed)} tracked items")
        time.sleep(0.5)
    HISTORY_PATH.write_text(json.dumps(dict(sorted(history.items())), ensure_ascii=False, indent=0) + "\n",
                            encoding="utf-8")

    prices = {i["id"]: dict(i["series"].get("nagoya", [])) for i in json.loads(PRICES_PATH.read_text(encoding="utf-8"))["items"]}
    food = dict(json.loads(CPI_PATH.read_text(encoding="utf-8"))["series"]["food"]["points"])
    try:
        old = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {}
    items = {}
    for item, v in (latest or {}).items():
        prev = old.get("items", {}).get(item, {}) if old.get("edition") == latest_month else {}
        items[item] = {**v, "reason_en": prev.get("reason_en")}  # English is added by the monthly explainer
    out = {
        "edition": latest_month, "source_url": latest_url,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline": "5-year average for the month, Tokyo central wholesale markets",
        "items": items,
        "track_record": track_record(history, prices, food),
    }
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tr = out["track_record"]
    print(f"Outlook {latest_month}: {len(items)} items; track record {tr['calls']} calls, "
          f"same direction {tr['same_direction']}")


if __name__ == "__main__":
    main()
