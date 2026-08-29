---
name: weekly-trades
description: Build the end-of-week trading workbook from the user's Interactive Brokers account — pulls the week's executions, folds fills into exit events, derives premium paid / entry price / return on premium, and writes a 4-sheet .xlsx plus a .csv into data/<week>/ in this repo. Use this whenever the user wants their trading week summarised, exported, or analysed: "סיכום שבוע", "סגירת שבוע", "תוציא לי את הטריידים", "weekly trades", "export my trades", "how did I do this week", or a request for trade data, P&L by day, P&L by ticker, win rate, or premium burn. Trigger it even when the user does not name a file format or say "workbook" — if they are asking what their trading week looked like, this is the skill. Do not use it for market commentary or watchlist news; that is the separate Weekly Market Pulse routine.
---

# Weekly trade workbook

The account holder trades short-dated options in size — a typical week is ~700 fills
across ~60 real decisions. IBKR's trade feed is close to what he needs but not it: the
fills are fragmented, the opening legs carry no result, and the two numbers he actually
reasons about — what he paid for the position and what fraction of that came back — are
not in the feed at all. This skill closes that gap the same way every week so the
numbers stay comparable across weeks.

## The workflow

**1. Pull the week from IBKR.** Call `get_account_trades` with `period: "DAYS_7"`. The
response is large and the harness will spill it to a file; note that path — the script
reads it directly, so there is no need to page through the JSON yourself. If IBKR is
disconnected or the call errors, say so and stop rather than working from stale data.

**2. Run the script.**

```bash
python3 .claude/skills/weekly-trades/scripts/build_week.py \
    <path-to-trades-json> data/<YYYY-MM-DD>-week
```

It picks the week automatically (the Monday of whichever week holds the most trades),
applies the standing filters, writes `trades-filtered.xlsx` and `trades-filtered.csv`,
and prints a summary JSON. Name the output directory after that Monday.

**3. Read the summary and report it.** The printed JSON has the numbers worth saying out
loud: net P&L, exits, win rate, profit factor, per-day and per-ticker breakdowns, and the
cash-flow check. Quote from it rather than re-deriving anything from the raw feed.

**4. Save it.** Commit the output directory to the repo. Past weeks live in
`data/2026-08-24-week/`, which also carries a README worth mirroring.

## What gets filtered, and why

Three filters run by default. They are not judgement calls about the trading — they are
what makes each row mean one thing:

- **Share trades are dropped.** The account tracks options and futures; equity fills are
  usually assignment or a hedge and would sit in the table as outliers with no premium.
- **Price-0 rows are dropped.** These are expiry bookkeeping, not executions.
- **Only SELL legs are kept**, so one row is one exit carrying its own result. This does
  discard the realised P&L on short closes, which the audit sheet reports — mention the
  figure if it is large.

Everything else is opt-in, because it encodes a judgement the user has to make:

| Flag | Use when |
|---|---|
| `--tickers A,B,C` | Restricting to names from a trading journal |
| `--drop-carry SYM --carry-day YYYY-MM-DD` | Removing positions held overnight |
| `--keep-stock`, `--keep-buys` | Auditing the raw feed instead of the exits |
| `--week-start YYYY-MM-DD` | The auto-detected week is not the one wanted |
| `--tz-offset -5` | Winter — the default -4 is US Eastern in daylight time |

Do not apply the optional filters unless asked. The 24–28 August 2026 week used a journal
whitelist and an overnight-carry rule; that was specific to that week, not a standing rule.

## Two things to tell the user every time

These are easy to get wrong and both make the week look better than it was:

**Net P&L is already after commissions.** IBKR nets `realized_pnl` against the commissions
on both legs. The workbook's commission column is the sell leg only, shown for reference —
subtracting it again double-counts.

**`realized_pnl` does not book losses on options that expire worthless.** The summary's
`cash_check` compares true cash movement against the reported figures and names the
symbols with the widest gaps. In the 24–28 August week the account was $4,844 below what
the realised numbers implied. If `cash_check.gap` is materially negative, say so — the
workbook is a record of exits taken, not a complete economic P&L.

## How the derived fields work

Only quantity, exit price, proceeds, net P&L and commission come from IBKR. The rest is
arithmetic, and ships as live formulas so the sheet still adds up if a cell is corrected:

```
multiplier   = proceeds / (quantity × exit price)      # 100 for equity options
premium paid = proceeds − net P&L
entry price  = premium paid / (quantity × multiplier)
% of premium = net P&L / premium paid
```

The multiplier is derived rather than assumed because futures options vary — CL is 1000,
NQ is 20, ES is 50. A good sanity check is to read a few reconstructed entry prices back
to the user against what they remember paying; on the 24–28 August week they matched the
journal to the cent.

Return on premium is meaningless for outright futures, where the cost basis is notional
rather than premium. The per-ticker sheet carries that caveat; keep it out of any headline
percentage.

## The workbook

Four sheets, right-to-left, Arial:

- **עסקאות** — one row per exit, with an autofilter and a totals row.
- **לפי טיקר** — `SUMIF`/`COUNTIFS` against the exits sheet, sorted by P&L.
- **לפי יום** — daily result and a running cumulative.
- **סינון** — the filter chain, row counts and P&L effect per step, ending in a
  cross-check against the exits sheet. If that cross-check disagrees with the total,
  something is wrong; `audit_reconciles` in the summary flags it.

`openpyxl` is required (`pip install openpyxl` if the import fails). LibreOffice cannot
recalculate in some sandboxes, so do not block on `recalc.py` — Excel and Sheets compute
the formulas on open. If verification is wanted, re-derive the four formula columns in
Python and compare against the CSV, which is written independently.
