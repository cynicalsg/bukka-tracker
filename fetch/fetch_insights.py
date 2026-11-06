"""Collect related news headlines for the month's biggest price changes and write docs/data/insights.json.

This is the free version of "why did prices change": it gathers headlines (title, source, date, link)
but does not write explanations. The file keeps a `summary_ja` / `summary_en` slot per item so an
AI step can fill in explanations later without changing the page.

Movers are picked exactly as on the page's "Biggest changes" card: the top 3 rises and falls since
last month and since last year.

Usage:
    python fetch/fetch_insights.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monthly_summary import latest_month, months_back, movers, series  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = ROOT / "docs" / "data" / "prices.json"
CONFIG_PATH = ROOT / "fetch" / "news.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "insights.json"
USER_AGENT = "bukka-tracker/1.0 (+https://github.com/cynicalsg/bukka-tracker)"


def base_name(name_ja: str) -> str:
    """'豚肉(国産・バラ)' -> '豚肉'"""
    return re.split(r"[(（]", name_ja)[0].strip()


def search_terms(item: dict, config: dict) -> tuple[str, list[str]]:
    o = config["overrides"].get(item["id"], {})
    name = base_name(item["name_ja"])
    return o.get("query", f"{name} 価格"), o.get("must", [name])


def window(month: str) -> tuple[str, str]:
    """News from the month before the data month through the month after it."""
    start = months_back(month, 1) + "-01"
    end = months_back(month, -2) + "-01"
    return start, end


def feed_url(config: dict, query: str, month: str) -> str:
    start, end = window(month)
    return config["feed"].format(query=urllib.parse.quote(f"{query} after:{start} before:{end}"))


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """RSS items -> [{title, source, url, date}]. Google News titles end with ' - Source'."""
    out = []
    for it in ET.fromstring(xml_bytes).iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        date = ""
        try:
            date = parsedate_to_datetime(it.findtext("pubDate") or "").date().isoformat()
        except (TypeError, ValueError):
            pass
        url = (it.findtext("link") or "").strip()
        if title and url.startswith("https://"):
            out.append({"title": title, "source": source, "url": url, "date": date})
    return out


def pick_headlines(entries: list[dict], must: list[str], cause_words: list[str], n: int,
                   price_words: list[str] | None = None, exclude_words: list[str] | None = None) -> list[dict]:
    """Keep headlines that name the item and talk about price, minus shopping noise (rankings, sales,
    recipes); put ones mentioning a likely cause first; drop near-duplicates."""
    seen, kept = set(), []
    for e in entries:
        t = e["title"]
        key = re.sub(r"\W", "", t)[:24]
        if key in seen or not any(w in t for w in must):
            continue
        if price_words and not any(w in t for w in price_words):
            continue
        if exclude_words and any(w in t for w in exclude_words):
            continue
        seen.add(key)
        kept.append(e)
    newest_first = lambda e: -int(e["date"].replace("-", "")) if e["date"] else 0  # noqa: E731
    kept.sort(key=lambda e: (not any(w in e["title"] for w in cause_words), newest_first(e)))
    return kept[:n]


def mover_changes(prices: dict) -> dict[str, dict]:
    """The items on the page's 'Biggest changes' card, with their % changes."""
    m = latest_month(prices)
    out: dict[str, dict] = {}
    for n, key in ((1, "mom"), (12, "yoy")):
        ups, downs = movers(prices, m, n)
        for change, item in ups + downs:
            out.setdefault(item["id"], {"item": item})[key] = round(change, 1)
    return out


def check_official(config: dict) -> list[dict]:
    """Official links that currently respond (the first working URL of each)."""
    ok = []
    for link in config["official"]["links"]:
        for url in link["urls"]:
            try:
                http_get(url, timeout=20)
                ok.append({"title_ja": link["title_ja"], "title_en": link["title_en"], "url": url})
                break
            except Exception as exc:  # noqa: BLE001 - any failure just means "don't show this link"
                print(f"  official link unavailable: {url} ({exc})")
    return ok


def keep_explained(new: dict, old: dict | None) -> dict:
    """Carry over explanations written for the same data month (by the monthly explainer session).
    An explained item keeps its old headline list too, so the explanation's [n] citations still
    point at the right headlines; its price changes and official links are refreshed."""
    if not old or old.get("month") != new["month"]:
        return new
    for item_id, item in new["items"].items():
        prev = old.get("items", {}).get(item_id)
        if prev and (prev.get("summary_ja") or prev.get("summary_en") or any(h.get("hide") for h in prev.get("headlines", []))):
            item.update({k: prev.get(k) for k in ("headlines", "summary_ja", "summary_en")})
    if old.get("explained"):
        new["explained"] = old["explained"]
    return new


def main() -> None:
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    month = latest_month(prices)
    official = check_official(config)
    items = {}
    for item_id, info in mover_changes(prices).items():
        item = info["item"]
        query, must = search_terms(item, config)
        try:
            entries = parse_feed(http_get(feed_url(config, query, month)))
        except Exception as exc:  # noqa: BLE001 - one failed search shouldn't drop the rest
            print(f"  {item_id}: search failed ({exc})")
            entries = []
        headlines = pick_headlines(entries, must, config["cause_words"], config["per_item"],
                                   config.get("price_words"), config.get("exclude_words"))
        print(f"  {item_id:<12} {query!r}: {len(entries)} results, kept {len(headlines)}"
              + (f" e.g. {headlines[0]['title'][:50]}" if headlines else ""))
        items[item_id] = {
            "mom": info.get("mom"), "yoy": info.get("yoy"),
            "headlines": headlines,
            "official": official if item.get("category") in config["official"]["categories"] else [],
            "summary_ja": None, "summary_en": None,  # filled in by the AI version, if enabled later
        }
    start, end = window(month)
    out = {
        "month": month, "method": "headlines",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "news_window": [start, end], "items": items,
    }
    try:
        old = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    out = keep_explained(out, old)
    OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote headlines for {len(items)} items ({sum(len(v['headlines']) for v in items.values())} total) "
          f"to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
