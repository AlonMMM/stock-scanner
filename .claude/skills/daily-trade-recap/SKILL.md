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

**1b. Find the reset boundary.** `accounts.account.start` from that same
`get_pa_performance_all_periods` call is also the honest start of "all time" — it is
where IBKR's own performance tracking begins, which is not always the date of the
earliest row in the trade feed (a paper-account reset or a funding change can leave
older rows sitting in the feed that no longer reflect the account's current balance).
Pass that date as `--since` in step 2 rather than defaulting to whatever the trade feed
happens to contain. If the account holder names a different reset date, use that
instead — they know their own account history better than either API does.

**2. Run the script.**

```bash
python3 <this-skill-dir>/scripts/build_recap.py <path-to-trades-json> <output-dir> \
    --since <reset-date-from-step-1b>
```

It writes `day-recap.json` (the most recent trading day only) and
`all-time-curve.json` (one point per exit — a *trade*, not a calendar day — from
`--since` onward, chronologically ordered, ticker and commission included on each) to
`<output-dir>`, and prints both to stdout. Omit `--since` only if there is no known
reset boundary; the script then uses every exit it was given.

Two more filters exist for exactly the cases weekly-trades already named, because the
same account hits the same two problems: `--drop-expiry SYM[,SYM] --expiry-day
YYYY-MM-DD` for a price-0 row that is a reset/vanished position rather than a real
expiry (nothing in the feed tells them apart — only the account holder does), and
`--drop-carry SYM[,SYM] --carry-day YYYY-MM-DD` for a real, nonzero-price exit whose
cost basis traces back to a lot opened *before* the window being reported on (e.g. a
position carried in from before a reset week) — a real trade, but not one that window
should get credit or blame for. Both are opt-in and blunt (they drop every matching
exit on that day), so only apply them on the account holder's say-so, the same way
weekly-trades treats them as a judgement call rather than a default.

**3. Report the day.** Quote from `day-recap.json` rather than re-deriving anything:
net P&L, win rate, profit factor, the per-ticker split, biggest win and biggest loss,
and the expiries block (worthless-expiry premium is real money lost that IBKR's own
`realized_pnl` never books — say it out loud the same way `weekly-trades` does). If the
most recent trading day was not literally yesterday (a weekend, a holiday, or a quiet
day with no fills), say which day it actually is before reporting on it.

**4. Render the report — one command, no HTML to write by hand.**

```bash
python3 <this-skill-dir>/scripts/render_report.py \
    <output-dir>/day-recap.json <output-dir>/all-time-curve.json <output-dir>/trading-progress.html \
    [--notes <output-dir>/notes.json]
```

This is a plain, self-contained script — stdlib only, no MCP tools, no Claude — that
drops the two JSON files from step 2 into `report_template.html` (next to it in the same
directory) and writes the finished page. It always renders: the KPI row and per-ticker
table from `day-recap.json`; a ticker checklist (the "sanitize" control — unchecking a
symbol removes it from both lines below, contributing 0 rather than dropping the point,
so the x-axis stays the same length); and **two lines on one chart, always both
visible** — net of commission and before commission (net + that trade's `com` added
back), same axis, a legend, the gap between them at any point being the cumulative
commission to date — one point per trade in `all-time-curve.json`'s `trades` list, not
one per day, so a busy session reads as a run of points. All of that is mechanical; if
the `dataviz` skill's rules and this file's script ever disagree on a chart detail,
change the template, don't reason around it inline.

The one thing the script does *not* generate is the investigation narrative — a reset
write-off found and dropped, a carried position excluded, that kind of finding belongs
to this specific run's story, not to a template. Write it as a small JSON array (see the
module docstring in `render_report.py` for the shape) and pass it as `--notes`; each
entry renders as a callout above the KPI row, in order. No `--notes` is a fine, valid
call for a clean run with nothing to flag.

Because the whole pipeline from here is `build_recap.py` → `render_report.py`, both
plain Python with no dependency on this skill or on Claude, it can be re-run by hand
any time there's a trades JSON on disk — getting that JSON in the first place is the
one step that still needs the IBKR connector.

**5. Publish it as an Artifact**, not a static file — the whole point of "sanitize a
ticker from the graph" is that the user interacts with it after delivery. If a prior
run's artifact URL is saved (see step 6), read it first and republish to the same URL
so the link stays stable; otherwise publish new and save the URL.

**6. Save it.** If working in the account holder's `stock-scanner` repo, write
`day-recap.json`, `all-time-curve.json` and (if used) `notes.json` to
`data/<YYYY-MM-DD>-day/`, and keep the published artifact's URL in
`data/all-time-progress-artifact-url.txt` (create it on the first run, overwrite nothing
else) so the next run updates the same page instead of publishing a new one. Outside
that repo, hand the files over directly.

## What this deliberately does not do

- No week-start guessing, no `--tickers` filter, no xlsx — this is a smaller, faster
  tool than `weekly-trades` for a narrower question. If the user wants the full weekly
  workbook, hand off to that skill instead of trying to stretch this one.
- The progress chart is built from realized exits the trade feed can see, not from
  account NAV — it will not match `get_pa_performance_all_periods` exactly, since that
  series is time-weighted-return-based and reacts to deposits/withdrawals. Don't present
  the two as the same number; the exits-based curve is "what the trades themselves made,"
  which is what "sanitizing a ticker" is asking to see.
