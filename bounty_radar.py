#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bounty_radar.py — find open-source bounties that are actually worth taking.

The point of this tool is one idea: payout alone is a useless ranking.
A $400 bounty with 20 competing comments is worth less than a $120 bounty
nobody has opened yet. So every bounty is scored as:

    score = payout / (1 + comments)

and then filtered against the things that make a bounty untakeable for most
people: crypto-only payouts, GPU hardware requirements, native mobile
platforms, languages you may not ship in.

Zero dependencies. Python 3.8+.

    export GITHUB_TOKEN=ghp_xxx      # classic token, `repo` scope, 5000 req/h
    python bounty_radar.py
    python bounty_radar.py --days 7  # only bounties opened in the last 7 days

MIT licensed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.github.com"
UA = "gh-bounty-radar/1.0"

# Payout methods and platforms that rule a bounty out for most contributors.
# Tune this list to your own situation; it is the only opinionated part.
BLOCK = [
    # payouts that are illegal or impractical in some jurisdictions
    "usdc", "usdt", "crypto", "bitcoin", "solana", "on-chain payout",
    # hardware you probably do not have
    "cuda", "rtx ", "rtx-", "3090", "4090", "5090", "a100", "h100",
    "gpu cluster", "vram",
    # platforms that need a device or store account
    "solidity", "smart contract", "swiftui", "android app", "kotlin",
    "flutter", "unity", "unreal",
    # identity / tax requirements
    "w-9", "w9 form", "us resident", "ssn",
    # not a real bounty
    "bounty hunter game", "bounty hunter rpg",
]

LANGS = ["python", "javascript", "typescript", "node", "php", "html", "css", "sql", "bash", "go "]

MONEY_PATTERNS = [
    re.compile(r"(?:US)?\$\s?([0-9][0-9,]{1,6}(?:\.[0-9]{1,2})?)"),
    re.compile(r"(?:USD|usd)\s?([0-9][0-9,]{1,6})"),
    re.compile(r"([0-9][0-9,]{1,6})\s?(?:USD|usd)"),
]


def _request(url, token):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    return urllib.request.Request(url, headers=headers)


def api_get(url, token, retries=3):
    """GET with rate-limit handling. Returns (json, headers)."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(_request(url, token), timeout=30) as r:
                return json.loads(r.read().decode("utf-8")), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                reset = e.headers.get("x-ratelimit-reset")
                wait = 10
                if reset:
                    try:
                        wait = max(5, min(60, int(reset) - int(time.time()) + 2))
                    except ValueError:
                        pass
                print(f"  rate limited, sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 404:
                return None, {}
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  network error: {e}", file=sys.stderr)
            time.sleep(3)
    return None, {}


def parse_payout(text):
    """Largest dollar amount mentioned, or 0."""
    values = []
    for pattern in MONEY_PATTERNS:
        for match in pattern.finditer(text or ""):
            try:
                value = float(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if 10 <= value <= 20000:
                values.append(value)
    return max(values) if values else 0.0


def repo_of(issue):
    match = re.search(r"/repos/(.+)$", issue.get("repository_url") or "")
    return match.group(1) if match else "?"


def blocked_by(issue):
    blob = ((issue.get("title") or "") + " " + (issue.get("body") or "")).lower()
    for word in BLOCK:
        if word in blob:
            return word
    return None


def languages_in(issue):
    blob = ((issue.get("title") or "") + " " + (issue.get("body") or "")).lower()
    return [lang.strip() for lang in LANGS if lang in blob]


def merge_ratio(repo, token):
    """Share of closed PRs that were actually merged — the number that tells you
    whether a maintainer pays out or just collects open PRs forever."""
    merged, _ = api_get(f"{API}/search/issues?q=" + urllib.parse.urlencode(
        {"q": f"repo:{repo} is:pr is:merged", "per_page": 1}), token)
    closed, _ = api_get(f"{API}/search/issues?q=" + urllib.parse.urlencode(
        {"q": f"repo:{repo} is:pr is:closed", "per_page": 1}), token)
    m = (merged or {}).get("total_count", 0)
    c = (closed or {}).get("total_count", 0)
    if c == 0:
        return None
    return round(m / c, 2)


def search(query, token, per_page=100):
    url = f"{API}/search/issues?" + urllib.parse.urlencode(
        {"q": query, "sort": "created", "order": "desc", "per_page": per_page})
    data, _ = api_get(url, token)
    if not data:
        return []
    print(f"  {query!r} -> {data.get('total_count')} total", file=sys.stderr)
    return data.get("items") or []


def collect(days, token):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    queries = [
        f"is:issue is:open label:bounty created:>{since}",
        f"is:issue is:open bounty in:title created:>{since}",
    ]
    seen = {}
    for query in queries:
        for item in search(query, token):
            seen.setdefault(str(item.get("id")), item)
        time.sleep(2)  # search API allows 30 requests/minute
    return list(seen.values())


def rank(issues, token, check_ratio=False):
    rows = []
    for issue in issues:
        title = issue.get("title") or ""
        body = issue.get("body") or ""
        payout = parse_payout(title) or parse_payout(body[:3000])
        if payout < 30:
            continue
        if blocked_by(issue):
            continue
        comments = int(issue.get("comments") or 0)
        repo = repo_of(issue)
        row = {
            "score": round(payout / (1 + comments), 1),
            "payout": payout,
            "comments": comments,
            "repo": repo,
            "number": issue.get("number"),
            "title": title[:110],
            "langs": ",".join(languages_in(issue)) or "-",
            "opened": (issue.get("created_at") or "")[:10],
            "url": issue.get("html_url"),
            "merge_ratio": None,
        }
        if check_ratio:
            row["merge_ratio"] = merge_ratio(repo, token)
            time.sleep(1)
        rows.append(row)
    # repos that never merge are worth less than the number suggests
    rows.sort(key=lambda r: (r["merge_ratio"] if r["merge_ratio"] is not None else 0.5)
              * r["score"], reverse=True)
    return rows


def render(rows, days):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# Bounty radar — last {days} days (generated {stamp})", ""]
    out.append("Score = payout / (1 + comments). Merge = share of closed PRs that were merged.")
    out.append("")
    out.append("| Payout | Comments | Merge | Score | Repo | Issue | Language | Opened |")
    out.append("|---:|---:|---:|---:|---|---|---|---|")
    for row in rows[:40]:
        ratio = "-" if row["merge_ratio"] is None else f"{row['merge_ratio']:.2f}"
        title = row["title"].replace("|", "/")
        out.append(
            f"| ${int(row['payout'])} | {row['comments']} | {ratio} | {row['score']} "
            f"| [{row['repo']}](https://github.com/{row['repo']}) | "
            f"[#{row['number']}]({row['url']}) | {row['langs']} | {row['opened']} |"
        )
    out.append("")
    out.append(f"{len(rows)} candidate(s) after filtering.")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Rank open-source bounties by payout and competition.")
    parser.add_argument("--days", type=int, default=7, help="how far back to look (default 7)")
    parser.add_argument("--merge-ratio", action="store_true",
                        help="also check each repo's PR merge ratio (slower, 2 extra requests per repo)")
    parser.add_argument("--out", default=None, help="write the markdown table to this file")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("warning: no GITHUB_TOKEN set — you get 10 search requests/minute", file=sys.stderr)

    issues = collect(args.days, token)
    print(f"  {len(issues)} unique issue(s) collected", file=sys.stderr)
    rows = rank(issues, token, args.merge_ratio)
    table = render(rows, args.days)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(table)
        print(f"written to {args.out}", file=sys.stderr)
    else:
        print(table)


if __name__ == "__main__":
    main()
