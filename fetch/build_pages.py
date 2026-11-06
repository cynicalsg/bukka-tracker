"""Build a page per city (docs/<city>/index.html) and sitemap.xml from docs/index.html.

Each city page is the main page with its own title, description and link-preview tags, a <base> so
its data paths resolve to the site root, and the city preset. Run after changing docs/index.html or
the city list (the monthly workflow runs it too):

    python fetch/build_pages.py
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
TEMPLATE = DOCS / "index.html"
INDEX = DOCS / "data" / "cities.json"
SITE = "https://cynicalsg.github.io/bukka-tracker/"


def short_ja(name: str) -> str:
    return re.sub(r"市$", "", name)


def head_tags(city: dict | None) -> dict[str, str]:
    """Title, description and URL for the root page (city=None) or a city page."""
    if city is None:
        return {"title": "名古屋 物価トラッカー | Nagoya Price Tracker",
                "description": "名古屋市など全国52都市の食品・日用品・光熱費の小売価格を毎月更新。値上がり・値下がりした品目、旬の安い野菜、"
                               "家計のかごの費用、物価と賃金の比較。Monthly retail prices of food and essentials in Nagoya and 51 other Japanese cities.",
                "url": SITE}
    ja, en = short_ja(city["name_ja"]), city["name_en"]
    return {"title": f"{ja} 物価トラッカー | {en} Price Tracker",
            "description": f"{city['name_ja']}の食品・日用品・光熱費の小売価格を毎月更新。値上がり・値下がりした品目、旬の安い野菜、"
                           f"家計のかごの費用、全国平均との比較。Monthly retail prices of food and essentials in {en}, Japan.",
            "url": f"{SITE}{city['id']}/"}


def apply_head(page: str, tags: dict[str, str], city_id: str | None) -> str:
    """Replace the managed block between <!-- head:start --> and <!-- head:end -->."""
    t, d, u = (html.escape(tags[k], quote=True) for k in ("title", "description", "url"))
    block = "\n".join([
        "<!-- head:start (managed by fetch/build_pages.py) -->",
        *([f'<base href="../">', f'<script>window.PRESET_CITY = "{city_id}";</script>'] if city_id else []),
        f"<title>{t}</title>",
        f'<meta name="description" content="{d}">',
        f'<link rel="canonical" href="{u}">',
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="物価トラッカー | Price Tracker">',
        f'<meta property="og:title" content="{t}">',
        f'<meta property="og:description" content="{d}">',
        f'<meta property="og:url" content="{u}">',
        f'<meta property="og:image" content="{SITE}og.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta name="twitter:card" content="summary_large_image">',
        "<!-- head:end -->",
    ])
    new, n = re.subn(r"<!-- head:start.*?<!-- head:end -->", block, page, flags=re.S)
    if n != 1:
        raise SystemExit("docs/index.html needs exactly one <!-- head:start --> ... <!-- head:end --> block")
    return new


def build() -> list[str]:
    template = TEMPLATE.read_text(encoding="utf-8")
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    default = index.get("default", "nagoya")
    TEMPLATE.write_text(apply_head(template, head_tags(None), None), encoding="utf-8")
    urls = [SITE]
    for city in index["cities"]:
        if city["id"] == default:
            continue  # the root page is the default city
        out = DOCS / city["id"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(apply_head(template, head_tags(city), city["id"]), encoding="utf-8")
        urls.append(head_tags(city)["url"])
    today = date.today().isoformat()
    (DOCS / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><changefreq>monthly</changefreq></url>\n" for u in urls)
        + "</urlset>\n", encoding="utf-8")
    return urls


if __name__ == "__main__":
    print(f"Built {len(build()) - 1} city pages and sitemap.xml")
