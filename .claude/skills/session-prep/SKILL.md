---
name: session-prep
description: >-
  Build a pre-session trading prep report from the account holder's live IBKR account —
  net liquidation and buying power, today's rules-based position sizing (computed from
  the real account value, not a stale baseline), open positions with their sizing
  compliance, and a quoted scan across all watchlists. Use this before the trading day or
  week starts — "הכנה ליום מסחר", "הכנה לשבוע מסחר", "prep for tomorrow", "what's my size
  today", "session prep", "morning prep" — or whenever the account holder wants to know
  what they're allowed to size, what's already open, or how the watchlists are moving
  before they start trading. Do not use this for a retrospective on trades already made —
  that is the separate weekly-trades skill.
---

# Trading session prep

The account holder trades short-dated options against a written risk framework
(`docs/risk-rules.md`): position size is a function of days-to-expiration and the
account's own value, not a fixed number. That means the "how much can I put on today"
answer changes every session — this report answers it fresh each time from the real
account state, rather than making him do the arithmetic against a number he memorized
last month.

## The workflow

**1. Pull the account snapshot.** Three calls:

```
get_account_summary        -> account_summary.json
get_account_positions      -> positions.json
```

If either errors or looks disconnected, say so and stop rather than sizing against stale
numbers — this report exists specifically so the sizing table is never stale.

**2. Pull the watchlists.** `get_watchlists` returns every list's id and name;
`get_watchlist` per id returns its instruments. Build `watchlists.json` shaped
`{"List Name": ["TICK", ...], ...}` — drop empty lists, and give same-named lists
(this account has two "Favorites" and two "Watchlist") a distinguishing label since the
plain name collides.

**3. Quote every ticker across the watchlists.** There is no batch quote endpoint —
`get_price_snapshot` takes one `contract_id` at a time, and this account's 23 watchlists
carry on the order of 200 unique tickers combined. Spawn a background agent for this
rather than doing it inline: hand it the ticker→contract_id map (built while flattening
the watchlists in step 2) and have it call `get_price_snapshot` with
`market_data_names: ["last", "change", "prior_close"]` for every one, in parallel batches,
writing the merged result to `quotes.json`. Keep building the rest of the report while it
runs — `build_prep.py` treats `--quotes` as optional and renders "no quote" for whatever
didn't come back rather than failing, so nothing blocks on it finishing first. Skip this
step (and the `--quotes` flag) for a fast partial run when the account holder wants sizing
and positions only, not a full watchlist scan.

**4. Check for events, by hand.** No IBKR tool returns an earnings or economic calendar —
`search_investment_topics` and `get_company_themes` are thematic, not calendar-based. Do a
quick check (WebSearch, or the account holder's own sources) for this week's major macro
prints (FOMC, CPI, PPI, NFP, etc.) and earnings dates for whatever is in the open
positions or came up as a big mover, and write it to a short markdown file — bullets, one
line each. Pass it as `--events`. This is the one part of the report that isn't pulled
from IBKR, and it degrades gracefully to "no events file supplied" if skipped, so don't
block the rest of the report on getting this perfect.

**5. Build the report.**

```bash
python3 <this-skill-dir>/scripts/build_prep.py \
    --account account_summary.json --positions positions.json \
    --watchlists watchlists.json --quotes quotes.json \
    --rules docs/risk-rules.md --events events.md \
    --out prep.html --label "Mon Sep 21, 2026"
```

**6. Hand it over.** This is a same-day artifact, not something that belongs in the
`data/<week>/` history the weekly-trades skill writes — don't commit it to the repo by
default. Publish it as an Artifact (or wherever the account holder reads it) and say so;
only write it into the repo if asked to keep a record.

## What the report computes, and why

**Position sizing is live, not the doc's number.** `docs/risk-rules.md` has a machine
readable YAML block at the bottom (`stop_budget`, `entry_risk_pct`, `account_value` —
`check_rules.py` already reads it the same way) with a `max premium = risk% × account ÷
stop budget` table worked out against one fixed account value. That value goes stale
the moment the account moves, which is exactly always — so this report re-computes the
same table from today's actual `net_liquidation` instead. The account holder reads the
`docs/risk-rules.md` copy for the reasoning behind the numbers; he reads this report for
what they evaluate to today.

**The gap callout is the report's most important line, when it fires.** If today's net
liquidation is more than ~2% away from the YAML block's `account_value`, the report says
so explicitly — a large gap matters because rule 13 (size halves every 5% down from the
account's own high-water mark) depends on knowing where that high-water mark is, and nothing
in this repo tracks it continuously yet. The report cannot compute the actual ladder rung,
so it says exactly that rather than quietly sizing at 1.0× and letting a real drawdown go
unflagged. Read this callout out loud when it appears; do not just quote the base sizing
table underneath it as if it were the final answer.

**Open-position sizing reads each position against today's own bucket.** DTE is parsed
from the contract description (IBKR doesn't return it as a structured field), matched to
its stop-budget bucket, and the cost basis is shown as a percentage of that bucket's max
premium — not the position's percentage of the account, which is a different and less
useful number here. A position originally sized correctly can still show over 100% today
if days have passed and the bucket tightened.

**Watchlist coverage is whatever the quote pass actually returned**, not silently
truncated to what succeeded — the report states "`N` of `M` tickers had no live quote"
up front and lists the misses per list, so a quiet gap in coverage doesn't read as a quiet
market.

## What this does not do

No trade suggestions, no "buy this." It answers three questions — what do I have, what am
I allowed to size, what's moving — and leaves the decision to the account holder. It also
does not touch the ladder rung (see above), does not fetch news or earnings automatically,
and does not persist anything — each run is a fresh snapshot, not a record.
