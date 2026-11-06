# Monthly explainer: instructions

These are the instructions for the scheduled Claude session that adds short "possible reasons"
to the month's biggest price changes. The GitHub Action collects the headlines; this step only
**reads them and writes explanations**. It does not browse the web.

## When to run

Run on a schedule a day after the price update (the update runs on the 26th and the 3rd).

1. `git fetch origin main` and start a new branch from `origin/main` named
   `explain-YYYY-MM` (the data month).
2. Open `docs/data/insights.json`.
   - If `explained.month` equals `month`, this month is already done: **stop and do nothing.**
   - If no item has any visible headlines, stop and do nothing.
   - If a pull request for `explain-YYYY-MM` is already open, stop and do nothing.

## What to write

For each item in `items`:

1. **Translate each headline** into natural English and add it as `title_en` (one line, keep it close
   to the original; don't add information).
2. **Hide headlines that are off-topic** by adding `"hide": true`. Off-topic means it doesn't
   discuss this item's price or supply: product promotions, recipes, a company's bankruptcy,
   celebrity comments, other items. Don't delete or reorder headlines; the [n] numbers depend on order.
3. **Write `summary_ja` and `summary_en`** (both, or neither) when the visible headlines support a reason:
   - 1–2 sentences each. Japanese: at most 200 characters. English: at most 400.
   - Only say what the headlines say. Attribute it: 「〜と報じられています」 / "Reports point to…".
     Never state a cause as fact, and don't add causes from your own knowledge.
   - Cite headlines as [1], [2] (the 1-based position in the list; only visible headlines).
   - Mention the direction that matches the data: `mom` is the change since last month,
     `yoy` since a year earlier (percent). If headlines describe the opposite direction or a different
     period, say so briefly rather than forcing a link.
   - If the headlines don't explain the change, leave both summaries `null`. That's a fine outcome.
   - Plain text: no links, Markdown, HTML or line breaks.
4. Don't change any other field.

Then add at the top level:

```json
"explained": {"month": "<same as month>", "by": "monthly explainer", "date": "<today, YYYY-MM-DD>"}
```

## Check, commit, open a pull request

1. Run `python fetch/check_insights.py` and fix anything it reports. Run `python -m unittest discover -s tests`.
2. Commit only `docs/data/insights.json` with the message `Explain <Month YYYY> price changes`.
3. Push the branch and open a pull request to `main` titled
   `Possible reasons for <Month YYYY> price changes / <YYYY年M月>の値動きの理由`.
   In the description, list each item with its change and both summaries, and the hidden headlines with
   a few words on why. End with: "Written from the collected headlines only; please review before merging."
4. Don't merge it. The owner reviews and merges.

## Examples of the tone

- 「8〜9月の長雨による記録的な日照不足で、トマトなど野菜の価格が上がったと報じられています[2][3]。」
- "Reports point to record low sunshine from prolonged rain in August–September, which pushed up
  vegetable prices including tomatoes [2][3]."
