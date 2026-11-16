# gh-bounty-radar

Rank open-source bounties by **payout divided by competition**, not payout alone.

A $400 bounty with 20 comments is worth less than a $120 bounty nobody has opened yet. Most bounty lists sort by the dollar figure and hide the part that actually decides whether you get paid.

## The observation this tool is built on

I scanned 210 open `label:bounty` issues over one week. Of a 100-issue sample:

| Comments on the issue | Issues |
|---|---|
| 0 | **0** |
| 1 | 87 |
| 2 | 8 |
| 3 or more | 5 |

Not one was still unclaimed. A $150 bounty posted at 01:13 had its first claim comment at 01:17, and four pull requests within four hours.

So speed is not the edge — you cannot out-run a bot that watches the API. The two things that still decide the outcome are:

1. **Which repos actually merge.** Some projects collect open pull requests like stamps: I found one with 15 open PRs and no merges. A $300 bounty there is worth $0.
2. **Which bounties nobody serious is fighting for.** Low comment count on a repo with a healthy merge ratio is the only reliable signal.

This tool computes both.

## Install

Zero dependencies. Python 3.8+.

```bash
git clone https://github.com/xiaoenduo/gh-bounty-radar.git
cd gh-bounty-radar
export GITHUB_TOKEN=ghp_xxx      # classic token, `repo` scope
python bounty_radar.py --days 7 --merge-ratio
```

Without a token you get 10 search requests per minute and it crawls. With a token: 30/min for search, 5000/hour overall.

## Output

```
| Payout | Comments | Merge | Score | Repo | Issue | Language | Opened |
|---:|---:|---:|---:|---|---|---|---|
| $150 | 1 | 0.81 | 75.0 | [owner/repo](...) | [#20](...) | typescript | 2026-11-16 |
```

- **Score** — payout / (1 + comments). Higher is better.
- **Merge** — share of closed pull requests that were merged. `0.81` means the maintainer pays out; `0.05` means they never do.
- Rows are sorted by `score × merge ratio`.

## Filtering

The `BLOCK` list in `bounty_radar.py` removes bounties that are untakeable for most contributors:

- **Crypto payouts** (`usdc`, `usdt`, `on-chain`) — illegal to receive in some jurisdictions, and worth nothing if you cannot cash out.
- **Hardware gates** (`cuda`, `5090`, `h100`, `vram`) — if the task needs a GPU you do not own, the payout is fiction.
- **Native mobile** (`swiftui`, `kotlin`, `flutter`) — needs a device and a store account to test.
- **Tax and residency forms** (`w-9`, `ssn`, `us resident`).

Edit that list for your own situation. It is the only opinionated part of the code.

## Caveats, honestly

- GitHub's search API only returns the first 1000 results per query, so a broad query silently truncates. Narrow it with `--days`.
- `--merge-ratio` costs two extra API requests per repo; on a busy run this is the slow part.
- Amount extraction is regex over the issue title and body. It reads `$300`, `300 USD`, `USD 300`. It will miss `three hundred dollars` and will occasionally pick up an unrelated dollar figure (cloud credits, a neighboring task). Read the issue before you start coding.
- A high score is a *lead*, not an offer. Someone may have already shipped the fix in a pull request that is not linked to the issue.

## License

MIT. See `LICENSE`.
