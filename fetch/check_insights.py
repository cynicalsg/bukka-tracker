"""Check docs/data/insights.json before committing explanations (used by the monthly explainer).

Rules for each item:
- summary_ja and summary_en are both filled in or both empty
- at most 200 characters (Japanese) / 400 characters (English), plain text: no links, HTML or Markdown
- every [n] citation points at an existing, non-hidden headline, and a filled summary cites at least one
- title_en, when present, is a non-empty single line; hide, when present, is true/false

Usage: python fetch/check_insights.py   (exit code 1 and a list of problems if anything is wrong)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "insights.json"
LIMITS = {"summary_ja": 200, "summary_en": 400}
FORBIDDEN = re.compile(r"https?://|www\.|<[a-zA-Z/]|\]\(|\*\*|`")


def problems(data: dict) -> list[str]:
    out = []
    for item_id, item in data.get("items", {}).items():
        heads = item.get("headlines", [])
        ja, en = item.get("summary_ja"), item.get("summary_en")
        if bool(ja) != bool(en):
            out.append(f"{item_id}: summary_ja and summary_en must both be filled in or both empty")
        for key in LIMITS:
            text = item.get(key)
            if not text:
                continue
            if not isinstance(text, str):
                out.append(f"{item_id}.{key}: must be a string")
                continue
            if len(text) > LIMITS[key]:
                out.append(f"{item_id}.{key}: {len(text)} characters (max {LIMITS[key]})")
            if FORBIDDEN.search(text) or "\n" in text:
                out.append(f"{item_id}.{key}: plain text only (no links, HTML, Markdown or line breaks)")
            cites = [int(n) for n in re.findall(r"\[(\d+)\]", text)]
            if not cites:
                out.append(f"{item_id}.{key}: cite at least one headline as [n]")
            for n in cites:
                if not 1 <= n <= len(heads):
                    out.append(f"{item_id}.{key}: [{n}] doesn't exist ({len(heads)} headlines)")
                elif heads[n - 1].get("hide"):
                    out.append(f"{item_id}.{key}: [{n}] cites a hidden headline")
        for n, h in enumerate(heads, 1):
            if "title_en" in h and (not isinstance(h["title_en"], str) or not h["title_en"].strip() or "\n" in h["title_en"]):
                out.append(f"{item_id} headline [{n}]: title_en must be a non-empty single line")
            if "hide" in h and not isinstance(h["hide"], bool):
                out.append(f"{item_id} headline [{n}]: hide must be true or false")
    return out


def main() -> None:
    found = problems(json.loads(PATH.read_text(encoding="utf-8")))
    for p in found:
        print("PROBLEM:", p)
    if found:
        sys.exit(1)
    print("insights.json OK")


if __name__ == "__main__":
    main()
