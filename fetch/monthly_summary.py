"""Write a short bilingual monthly summary (Markdown) from the data files, for a GitHub issue.

Usage:
    python fetch/monthly_summary.py                 # prints the summary
    python fetch/monthly_summary.py --latest-month  # prints the latest data month, e.g. 2026-09
    python fetch/monthly_summary.py --title         # prints the issue title
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
JST = timezone(timedelta(hours=9))
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def months_back(m: str, n: int) -> str:
    total = int(m[:4]) * 12 + int(m[5:7]) - 1 - n
    return f"{total // 12}-{total % 12 + 1:02d}"


def series(item: dict) -> list:
    return item["series"].get("nagoya") or next(iter(item["series"].values()), [])


def latest_month(prices: dict) -> str:
    return max((series(i)[-1][0] for i in prices["items"] if series(i)), default="")


def price_with_carry(points: dict, m: str, limit: int = 11):
    """Price at month m, or the last price within `limit` months before it (seasonal items)."""
    for n in range(limit + 1):
        v = points.get(months_back(m, n))
        if v is not None:
            return v
    return None


def basket_cost(prices: dict, basket: dict, m: str):
    """Cost of the default basket in month m (same rules as the page)."""
    mult = basket["household"]["adults"] + basket["child_factor"] * basket["household"]["children"]
    total = 0.0
    for item in prices["items"]:
        spec = basket["items"].get(item["id"])
        if not spec or spec.get("default") is None:
            continue
        p = price_with_carry(dict(series(item)), m)
        if p is None:
            return None
        total += spec["default"] * (1 if spec.get("fixed") else mult) * spec["per"] * p
    return total


def pct(now, before):
    return None if not now or not before else (now / before - 1) * 100


def fmt_pct(v) -> str:
    return "–" if v is None else f"{v:+.1f}%"


def movers(prices: dict, m: str, n: int, k: int = 3):
    rows = []
    for item in prices["items"]:
        pts = dict(series(item))
        change = pct(pts.get(m), pts.get(months_back(m, n)))
        if change is not None and abs(change) >= 0.05:
            rows.append((change, item))
    rows.sort(key=lambda r: r[0])
    ups = [r for r in reversed(rows) if r[0] > 0][:k]
    downs = [r for r in rows if r[0] < 0][:k]
    return ups, downs


def seasonal_for(prices: dict, month0: int, threshold: float = 0.10):
    """Items that are usually cheap / dear in calendar month `month0` (0 = January)."""
    cheap, dear = [], []
    for item in prices["items"]:
        prof = item.get("seasonal")
        if not prof or prof["amplitude"] < threshold:
            continue
        f = prof["factors"][month0]
        if f is None:
            continue
        if f <= 0.95:
            cheap.append((f - 1, item))
        elif f >= 1.05:
            dear.append((f - 1, item))
    cheap.sort(key=lambda r: r[0])
    dear.sort(key=lambda r: -r[0])
    return cheap, dear


def news_lines(insights: dict | None, prices: dict, lang: str, per_item: int = 2) -> list[str]:
    """Up to `per_item` headlines for each item on the Biggest changes list."""
    if not insights or insights.get("month") != latest_month(prices):
        return []
    names = {i["id"]: i[f"name_{lang}"] for i in prices["items"]}
    out = []
    for item_id, info in insights["items"].items():
        hs = info.get("headlines", [])[:per_item]
        if hs:
            links = "; ".join(f"[{h['title']}]({h['url']}) ({h['source']}{', ' + h['date'] if h['date'] else ''})" for h in hs)
            out.append(f"- **{names.get(item_id, item_id)}**: {links}")
    return out


def site_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "cynicalsg/bukka-tracker")
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def title(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"Nagoya prices: {MONTHS_EN[mo - 1]} {y} / 名古屋の物価 {y}年{mo}月"


def summary(prices: dict, basket: dict | None, cpi: dict | None, today: datetime | None = None,
            insights: dict | None = None) -> str:
    m = latest_month(prices)
    today = today or datetime.now(JST)
    next_month0 = today.month % 12  # the month after today, 0-based
    y, mo = int(m[:4]), int(m[5:7])

    basket_line_en = basket_line_ja = None
    if basket:
        now = basket_cost(prices, basket, m)
        if now:
            ch = {n: pct(now, basket_cost(prices, basket, months_back(m, n))) for n in (1, 12, 60)}
            basket_line_en = (f"**Default basket ({basket['household']['adults']} adults): ¥{now:,.0f}** — "
                              f"1 month {fmt_pct(ch[1])}, 1 year {fmt_pct(ch[12])}, 5 years {fmt_pct(ch[60])}")
            basket_line_ja = (f"**標準のかご(大人{basket['household']['adults']}人): ¥{now:,.0f}** — "
                              f"前月比 {fmt_pct(ch[1])}、前年比 {fmt_pct(ch[12])}、5年前比 {fmt_pct(ch[60])}")

    cpi_en = cpi_ja = None
    food = (cpi or {}).get("series", {}).get("food")
    if food and food.get("points"):
        pts = dict(food["points"])
        if m in pts:
            c1, c5 = pct(pts[m], pts.get(months_back(m, 12))), pct(pts[m], pts.get(months_back(m, 60)))
            cpi_en = f"Nagoya food CPI: 1 year {fmt_pct(c1)}, 5 years {fmt_pct(c5)}"
            cpi_ja = f"名古屋市の食料CPI: 前年比 {fmt_pct(c1)}、5年前比 {fmt_pct(c5)}"

    def mover_lines(lang: str) -> list[str]:
        out = []
        for n, label_en, label_ja in ((1, "Since last month", "前月から"), (12, "Since last year", "前年同月から")):
            ups, downs = movers(prices, m, n)
            name = (lambda i: i["name_en"]) if lang == "en" else (lambda i: i["name_ja"])
            sep = ", " if lang == "en" else "、"
            up = sep.join(f"{name(i)} {fmt_pct(c)}" for c, i in ups) or "–"
            down = sep.join(f"{name(i)} {fmt_pct(c)}" for c, i in downs) or "–"
            if lang == "en":
                out.append(f"- **{label_en}** — up: {up}; down: {down}")
            else:
                out.append(f"- **{label_ja}** — 値上がり: {up}／値下がり: {down}")
        return out

    cheap, dear = seasonal_for(prices, next_month0)
    nm_en, nm_ja = MONTHS_EN[next_month0], f"{next_month0 + 1}月"

    en = [f"## {MONTHS_EN[mo - 1]} {y}", ""]
    if basket_line_en:
        en.append(basket_line_en)
    if cpi_en:
        en.append(cpi_en)
    en += ["", *mover_lines("en"), ""]
    if cheap or dear:
        en.append(f"**Seasonal guide for {nm_en}** — usually cheap: "
                  + (", ".join(f"{i['name_en']} ({c:+.0%})" for c, i in cheap) or "–")
                  + "; usually expensive: " + (", ".join(f"{i['name_en']} ({c:+.0%})" for c, i in dear) or "–"))

    news_en, news_ja = news_lines(insights, prices, "en"), news_lines(insights, prices, "ja")
    if news_en:
        en += ["", "**Related news** (collected automatically; headlines may not explain the change):", *news_en]

    ja = [f"## {y}年{mo}月", ""]
    if basket_line_ja:
        ja.append(basket_line_ja)
    if cpi_ja:
        ja.append(cpi_ja)
    ja += ["", *mover_lines("ja"), ""]
    if cheap or dear:
        ja.append(f"**{nm_ja}の旬ガイド** — 例年安い: "
                  + ("、".join(f"{i['name_ja']}({c:+.0%})" for c, i in cheap) or "–")
                  + "／例年高い: " + ("、".join(f"{i['name_ja']}({c:+.0%})" for c, i in dear) or "–"))

    if news_ja:
        ja += ["", "**関連ニュース**(自動収集。値動きの理由を示すとは限りません):", *news_ja]

    footer = ["", "---", f"Charts / グラフ: {site_url()}",
              "Source / 出典: 総務省統計局「小売物価統計調査」「消費者物価指数」(e-Stat)"]
    return "\n".join(en + ["", "---", ""] + ja + footer) + "\n"


def main() -> None:
    prices = load(DATA / "prices.json")
    if "--latest-month" in sys.argv:
        print(latest_month(prices) if prices else "")
        return
    if not prices:
        raise SystemExit("docs/data/prices.json not found")
    if "--title" in sys.argv:
        print(title(latest_month(prices)))
        return
    print(summary(prices, load(ROOT / "docs" / "basket.json"), load(DATA / "cpi.json"),
                  insights=load(DATA / "insights.json")), end="")


if __name__ == "__main__":
    main()
