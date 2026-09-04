---
name: daily-trade-recap
description: >-
  Summarize the user's last trading day from their Interactive Brokers account — net P&L,
  win rate, per-ticker breakdown, expiries, biggest win/loss — and publish an interactive
  all-time progress chart (cumulative P&L since the account's own trade history begins)
  where individual tickers can be unchecked ("sanitized") out of the running total. Use
  this whenever the user wants to know how their last session went — "how did I do
  today", "sum my last trading day", "yesterday's trades", "איך הלך היום", "סיכום יום
  מסחר" — or wants to see their overall progress/equity curve, optionally excluding a
  ticker that's skewing it. Do not use it for a full week's workbook (see weekly-trades)
  or for premarket prep (see day-trade-prep) — this is the after-the-fact single-day
  recap plus the standing progress chart.
---

# Daily trade recap + all-time progress

Two things in one run: what the last trading day actually did, and where the account
stands overall. The day recap and the progress chart share the same exit-derivation
logic as `weekly-trades` (fold fills into exits, charge worthless expiries their full
premium, drop platform-restart artefacts) — see that skill's notes for why those rules
exist. This skill is not week-scoped: it finds the most recent trading day on its own,
and separately turns every exit it can see into a cumulative curve.

## The workflow

**1. Pull the trades.** Call `get_account_trades` with `period: "YEAR_TO_DATE"`. That
covers the account's full history as long as it was opened this calendar year — check
this against `get_pa_performance_all_periods`'s `accounts.account.start` field first
(format `YYYYMMDD`). If `start` falls in an earlier year, YTD will not be "all time";
say so plainly in the report rather than silently presenting a partial curve as
complete. (There is no single call that goes back further — `get_account_trades` tops
out at the four most recent completed quarters plus YTD — so a multi-year account's
true all-time curve would need those quarter calls merged in too, deduped by trade ID.)

**2. Run the script.**

```bash
python3 <this-skill-dir>/scripts/build_recap.py <path-to-trades-json> <output-dir>
```

It writes `day-recap.json` (the most recent trading day only) and
`all-time-curve.json` (every exit in the file, as a per-day, per-ticker P&L matrix —
the client sums whichever tickers stay checked) to `<output-dir>`, and prints both to
stdout.

**3. Report the day.** Quote from `day-recap.json` rather than re-deriving anything:
net P&L, win rate, profit factor, the per-ticker split, biggest win and biggest loss,
and the expiries block (worthless-expiry premium is real money lost that IBKR's own
`realized_pnl` never books — say it out loud the same way `weekly-trades` does). If the
most recent trading day was not literally yesterday (a weekend, a holiday, or a quiet
day with no fills), say which day it actually is before reporting on it.

**4. Build the progress chart.** Read the `dataviz` skill before writing it — this is a
single cumulative-P&L line (not one line per ticker; per-ticker color-coding isn't the
point here, the running total is) with a ticker checklist as the filter row above it,
per `interaction.md`'s "filters in one row above the charts." Unchecking a ticker
removes its contribution from the cumulative sum and the line redraws — all client-side
against the embedded `all-time-curve.json` data, no server round-trip. Default: every
ticker checked. Give the chart a hover tooltip (date, cumulative P&L, and which tickers
are currently excluded if any are). Put the day-recap numbers from step 3 in a small
card above or beside the chart so the page is a complete standing artifact, not just
the chart.

**5. Publish it as an Artifact**, not a static file — the whole point of "sanitize a
ticker from the graph" is that the user interacts with it after delivery. If a prior
run's artifact URL is saved (see step 6), read it first and republish to the same URL
so the link stays stable; otherwise publish new and save the URL.

**6. Save it.** If working in the account holder's `stock-scanner` repo, write
`day-recap.json` and `all-time-curve.json` to `data/<YYYY-MM-DD>-day/`, and keep the
published artifact's URL in `data/all-time-progress-artifact-url.txt` (create it on the
first run, overwrite nothing else) so the next run updates the same page instead of
publishing a new one. Outside that repo, hand the files over directly.

## What this deliberately does not do

- No week-start guessing, no `--tickers`/`--drop-carry` filters, no xlsx — this is a
  smaller, faster tool than `weekly-trades` for a narrower question. If the user wants
  the full weekly workbook, hand off to that skill instead of trying to stretch this one.
- The progress chart is built from realized exits the trade feed can see, not from
  account NAV — it will not match `get_pa_performance_all_periods` exactly, since that
  series is time-weighted-return-based and reacts to deposits/withdrawals. Don't present
  the two as the same number; the exits-based curve is "what the trades themselves made,"
  which is what "sanitizing a ticker" is asking to see.
