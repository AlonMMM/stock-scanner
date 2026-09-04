---
name: day-trade-prep
description: >-
  Build a premarket "day trade prep" briefing — everything that happened overnight and
  during the after-hours/premarket session, which watchlist names are trading on unusual
  volume, which non-watchlist names are moving big enough to matter, what the catalyst and
  sentiment is behind each mover, and what's scheduled for the day ahead (earnings, Fed
  speakers, economic data, options expiries). Use this whenever the user wants to get ready
  for the trading day — "prep me for today", "what happened overnight", "day trade prep",
  "מה קרה בלילה", "תכין אותי ליום המסחר", morning volume/news scans, or any request to
  check the watchlist for unusual activity before the open. Do not use it for end-of-week
  trade summaries (see weekly-trades) or the Monday sector recap (Weekly Market Pulse
  routine) — this is the daily, premarket-focused briefing.
---

# Day trade prep

The account holder trades short-dated options intraday, mostly in semis, software, AI
infrastructure and other high-beta momentum names (see the Weekly Market Pulse routine for
the standing sector focus). Before the US open he needs to know three things: what changed
overnight, which names on his radar are already moving on volume, and what's on the
calendar today that could move them further. This skill builds that briefing every trading
morning.

## The workflow

**1. Pull the watchlist and the book.** Call `get_watchlists`, then `get_watchlist` on every
list returned — don't guess which ones matter, scan all of them. Also call
`get_account_positions` so open positions get checked for overnight news even if they've
rolled off a watchlist. If IBKR errors or is disconnected, say so plainly and fall back to
researching the account holder's usual sectors (semis, software, AI infra, momentum/quantum
names) from public sources instead of blocking.

**2. Screen the watchlist for unusual volume.** For each ticker, call `get_price_snapshot`
with `market_data_names: [last, change, volume, prior_close, avg_90d_usd_volume,
cumulative_perf_1d]`. There's no direct "relative volume" field, so derive one: today's
dollar volume ≈ `volume × last`, compare it against `avg_90d_usd_volume`. A ratio
meaningfully above 1 (as a rule of thumb, ~1.5–2x or more) before or shortly after the open
is the flag — note it's an estimate, not IBKR's own relative-volume figure, since the
comparison mixes a full prior day's average against a partial or fresh session. Rank the
flagged names by the ratio, not by raw price move; a big percentage move on light volume is
a different story than a small move on heavy volume, and both are worth separating out in
the report.

**3. Find movers that are *not* on the watchlist.** The watchlist is where he's already
looking; the point of this section is what he isn't. Use WebSearch/WebFetch against
premarket most-active / top-gainers-losers sources (e.g. Finviz premarket screener,
MarketWatch, Benzinga premarket movers) filtered to his usual universe — semis, software,
AI infrastructure, neoclouds, quantum, other momentum/speculative names — plus anything
index-moving regardless of sector. List names showing outsized premarket volume or gaps
that aren't already covered in step 2, so the two lists don't just repeat each other.

**4. Gather overnight and premarket news.**
- **Macro first:** index futures direction, overnight Asia/Europe session, VIX level,
  overnight Fed commentary, any major geopolitical or macro headline since yesterday's
  close.
- **Per-name:** for every ticker flagged in steps 2 and 3, and every open position, search
  for what actually happened — earnings/guidance, an upgrade or downgrade, an FDA or
  regulatory event, M&A, a guidance cut, a contract win/loss, an insider filing, a sector
  read-through from a peer's earnings, or a pure macro/index-driven move with nothing
  company-specific behind it. Collect the source URL for each.

**5. Classify catalyst and sentiment per name.** For every flagged name give: catalyst type
(earnings / guidance / rating change / M&A / regulatory / macro-sector / insider / other),
a one-line sentiment read (bullish / bearish / mixed) with the reasoning, and the source.
Where premarket volume is high but no news explains it, say that explicitly — an unexplained
volume spike is itself a useful flag, not a gap in the research.

**6. Build today's calendar.** Cover, for the current trading day: scheduled economic
releases (CPI/PPI/jobs/retail sales/Fed speakers/FOMC — whatever's on today specifically),
premarket and after-market earnings for anything on the watchlist or in the book, and
whether today is a standard or monthly options expiry. Flag any position whose underlying
reports earnings today — that changes the risk on an already-open short-dated trade.

**7. Build the report.** One self-contained HTML page, same production standard as other
dashboard deliverables in this account — load the `dataviz` skill before building any chart
in it (e.g. a ranked bar of volume ratios). Section order: KPI row (futures/index levels,
VIX, overnight headline) → watchlist high-volume movers (ranked table with catalyst +
sentiment) → off-watchlist movers worth knowing about → your book (open positions, flagging
any with news or earnings today) → today's calendar → sources. Keep the accompanying chat
message to one or two sentences; the report carries the detail.

**8. Deliver it.** Use `SendUserFile` with the HTML report. This runs every trading morning,
so keep the structure stable week to week — the account holder should be able to scan it
the same way each day.

## Notes

- This is a premarket briefing, not a trade log — it doesn't touch IBKR executions or P&L.
  For that, see the `weekly-trades` skill.
- The volume-ratio heuristic in step 2 is deliberately conservative about its own precision;
  say "estimated" when quoting it rather than presenting it as an exact relative-volume
  number.
- If run well before the open, note that premarket volume is thin by nature and a smaller
  dollar-volume ratio can still be meaningful — read the ratio next to the news, not alone.
