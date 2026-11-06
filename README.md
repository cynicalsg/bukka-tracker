# bukka-tracker
Track and visualize changes in essential food prices in Japan over time, starting with Nagoya. 日本の生活必需品の価格推移を追跡・可視化 (名古屋から)

## How it works

- **Data:** the Statistics Bureau's Retail Price Survey (小売物価統計調査), monthly prices by city, via the [e-Stat API](https://www.e-stat.go.jp/api/).
- **Fetch:** `fetch/fetch_prices.py` (Python standard library only) downloads the table and writes `docs/data/prices.json`. The items and cities it tracks are in `fetch/items.json`.
- **Automation:** `.github/workflows/update-data.yml` runs on the 26th of each month (after the survey is published) and again on the 3rd in case publication is late. It commits any new data, and when a new month arrives it posts a bilingual **summary issue** (basket, food CPI, biggest movers, next month's seasonal guide) from `fetch/monthly_summary.py`. GitHub emails new issues to repository watchers. It can also be run by hand from the Actions tab, with an option to post the summary anyway.
- **Site:** `docs/index.html` is a static page (Chart.js) served by GitHub Pages, in Japanese or English. A bar stays at the top of the screen with **Price check** and a **☰ Menu** (jump to any section or category, open the tools, and change chart range, sort order and language). The page shows:
  - **A household basket you can customise:** the monthly cost of the staples you choose, with its change over 1 month, 1 year and 5 years. **Edit basket** sets the number of adults and children (a child counts as 0.6 of an adult), which items are included, and how much of each you buy per month in everyday units (g, kg, L, eggs, packs). Each visitor's basket is saved in their own browser, and **Copy link** shares it (the basket is stored in the link itself). Defaults, per adult, are in `docs/basket.json`.
  - **Comparison with official inflation:** Nagoya's food CPI (消費者物価指数, 食料, which includes eating out) over the same 1-month, 1-year and 5-year windows, plus a dashed line on every chart showing where the price would be had it risen with food CPI. `fetch/fetch_cpi.py` fetches it from the 2025-base CPI table on e-Stat.
  - **Seasonal patterns:** produce and fish with a clear yearly pattern show a 12-month bar strip (usually cheapest and priciest months), and a **seasonal guide** lists what's usually cheap or expensive this month. Patterns come from the last 10 years of Nagoya prices (`seasonal_profile` in `fetch/fetch_prices.py`).
  - **Price check (値段チェック):** enter a shelf price and pack size to see how it compares with Nagoya's current average and 12-month range. Open it directly with `…/bukka-tracker/#check` (handy as a phone home-screen bookmark).
  - **Nagoya vs. the national average:** every item card and chart compares Nagoya with the average of the 47 prefectural capitals (from 2010; the survey has no official monthly national average, so `fetch_prices.py` computes this unweighted mean).
  - **Prices and pay:** Aichi's average scheduled monthly pay (所定内給与額, annual, from the Basic Survey on Wage Structure via `fetch/fetch_wages.py`) against Nagoya's CPI and your basket since 2015, with real pay and the basket's share of a month's pay.
  - **Biggest changes:** the items that rose or fell the most since last month and since last year. Items with related news get a **Why? / なぜ?** toggle with headlines collected by `fetch/fetch_insights.py` (Google News in Japanese around the data month, filtered to headlines that name the item and mention price; settings in `fetch/news.json`), plus the agriculture ministry's vegetable page for vegetables. Headlines are not explanations, and the page says so. A monthly explainer (a scheduled Claude session following `fetch/EXPLAINER.md`) reads those headlines, translates them into English, hides off-topic ones and writes short possible reasons in Japanese and English (`summary_ja` / `summary_en` in `docs/data/insights.json`, checked by `fetch/check_insights.py`), then opens a pull request to review. Explanations are kept when the news is re-collected for the same month.
  - **One chart per item** (48 items in 9 categories, including utilities & fuel and household goods), with the latest price and the change from a year earlier. Items can be grouped by category or sorted by biggest rise or fall.

## Setup

1. Register for a free e-Stat app ID: https://www.e-stat.go.jp/api/ (ユーザ登録 → マイページ → API機能(アプリケーションID発行)). For the URL field use `https://cynicalsg.github.io/bukka-tracker/` (e-Stat rejects localhost and private IPs).
2. In this repo on GitHub: **Settings → Secrets and variables → Actions → New repository secret**, name `ESTAT_APP_ID`, value = your app ID.
3. **Settings → Pages:** Source "Deploy from a branch", branch `main`, folder `/docs`.
4. **Actions → Update price data → Run workflow** to fetch the first batch of data.

## Local development

```sh
python -m unittest discover -s tests          # tests use a sample fixture, no network needed
ESTAT_APP_ID=your-id python fetch/fetch_prices.py
python -m http.server -d docs 8000            # then open http://localhost:8000
```

**Unit changes:** the survey sometimes changes an item's pricing unit or product definition (e.g. tofu went from per 100 g to per 1 kg in 2014). In `fetch/items.json`, `rescale` converts older prices to the current unit and `since` starts a series after a definition change, so the charts don't show false jumps. Units are not in the e-Stat table; they are set in `items.json` from the survey's standard quantities and checked against price levels.

If an item is missing or matched the wrong product, the fetch log prints which e-Stat item each one matched. Pin the right one by adding `"code": "..."` to that item in `fetch/items.json`.
