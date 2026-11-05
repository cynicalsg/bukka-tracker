# bukka-tracker
Track and visualize changes in essential food prices in Japan over time, starting with Nagoya. 日本の生活必需品の価格推移を追跡・可視化 (名古屋から)

## How it works

- **Data:** the Statistics Bureau's Retail Price Survey (小売物価統計調査), monthly prices by city, via the [e-Stat API](https://www.e-stat.go.jp/api/).
- **Fetch:** `fetch/fetch_prices.py` (Python standard library only) downloads the table and writes `docs/data/prices.json`. The items and cities it tracks are in `fetch/items.json`.
- **Automation:** `.github/workflows/update-data.yml` runs the fetch on the 26th of each month (after the survey is published) and commits any new data. It can also be started by hand from the Actions tab.
- **Site:** `docs/index.html` is a static page (Chart.js) served by GitHub Pages, in Japanese or English. It shows:
  - **A household basket:** the monthly cost of the staples for a two-person household, with its change over 1 month, 1 year and 5 years. The quantities are estimates in `docs/basket.json`. Edit them to match your own shopping, and the page recalculates.
  - **Biggest changes:** the items that rose or fell the most since last month and since last year.
  - **One chart per item,** with the latest price and the change from a year earlier.

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

If an item is missing or matched the wrong product, the fetch log prints which e-Stat item each one matched. Pin the right one by adding `"code": "..."` to that item in `fetch/items.json`.
