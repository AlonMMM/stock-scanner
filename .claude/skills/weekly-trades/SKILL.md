---
name: weekly-trades
description: >-
  Build the end-of-week trading workbook from the user's Interactive Brokers account —
  pulls the week's executions, folds fills into exit events, derives premium paid, entry
  price and return on premium, and writes a 4-sheet .xlsx plus a .csv. Use this whenever
  the user wants their trading week summarised, exported, or analysed — "סיכום שבוע",
  "סגירת שבוע", "תוציא לי את הטריידים", "weekly trades", "export my trades", "how did I
  do this week" — or asks for trade data, P&L by day, P&L by ticker, win rate, or premium
  burn. Trigger it even when the user does not name a file format or say "workbook"; if
  they are asking what their trading week looked like, this is the skill. Do not use it
  for market commentary or watchlist news, which is the separate Weekly Market Pulse
  routine.
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

`scripts/build_week.py` sits next to this file — invoke it by its path relative to this
skill's directory, which differs depending on whether the skill is installed in an
account or checked into a repo:

```bash
python3 <this-skill-dir>/scripts/build_week.py \
    <path-to-trades-json> <output-dir>
```

It picks the week automatically (the Monday of whichever week holds the most trades),
applies the standing filters, writes `trades-filtered.xlsx` and `trades-filtered.csv`,
and prints a summary JSON.

**3. Read the summary and report it.** The printed JSON has the numbers worth saying out
loud: net P&L, exits, win rate, profit factor, per-day and per-ticker breakdowns, and the
cash-flow check. Quote from it rather than re-deriving anything from the raw feed.

`expiries` is the block to read first — see below. `by_hold` groups the week by how long
each position was held, which is the one cut the
account holder cannot get from the broker. Read it with the guard beside it: every bucket
also reports `largest_contributor` and `pnl_without_largest`, because a single outsized
winner routinely flips a bucket's sign. In the 24-28 August week the overnight bucket
looked like a +59% edge until CRM came out of it, at which point it lost 36% like every
other bucket. Never quote a bucket's return without checking what it looks like without
its largest name.

**3b. Where the premium burned.** `scripts/burn_slices.py` cuts the same week at lot
level and classifies every closing slice by whether the account holder could have acted:
intraday (both ends inside 09:30–16:00 ET on one day), off-hours, overnight, expiry. It
prints the burn per class and, separately, the exits whose cost basis predates the feed —
those have a real result but no reconstructable entry time.

```bash
python3 <this-skill-dir>/scripts/burn_slices.py <path-to-trades-json> <out.json>
```

The account holder's standing question is where the loss was a decision and where it was
the risk he bought. An expiry is the second kind; a 45% average give-back in the middle of
the trading day is the first.

**4. Check the week against the rules.** When `docs/risk-rules.md` is present, run it —
the account holder keeps a written rule set and wants each week measured against it:

```bash
python3 <this-skill-dir>/scripts/check_rules.py <path-to-trades-json> --rules docs/risk-rules.md
```

It reads its thresholds from the YAML block inside that document, so the rules and the
check can never drift apart. Report the FAILs and CHECKs, and pass on the caveats attached
to them rather than presenting a flag as a confirmed breach. It also prints the rules it
*cannot* evaluate and why — most of them need an expiry date the feed does not carry.
Repeat that list; a check that only mentions what it could see reads as a clean bill of
health, which it is not.

**5. Save it.** If the session is working in the account holder's `stock-scanner` repo,
write to `data/<YYYY-MM-DD>-week/` named after the Monday and commit it; past weeks live
there, and `data/2026-08-24-week/README.md` is worth mirroring. Outside that repo, write
somewhere sensible and hand the files over.

## What gets filtered, and why

Three filters run by default. They are not judgement calls about the trading — they are
what makes each row mean one thing:

- **Share trades are dropped.** The account tracks options and futures; equity fills are
  usually assignment or a hedge and would sit in the table as outliers with no premium.
- **Price-0 rows are split in two, and only one kind is dropped.** When a long option
  expires worthless IBKR closes it with a synthetic SELL at price 0 and stamps
  `realized_pnl = 0` on it. Nothing came back and the whole premium is gone, but the feed
  books no loss at all. Those rows are **kept and charged the full premium** — the script
  reads the cost of the lots that died out of the FIFO book, so an expiry reads as the
  −100% it was. In the 24–28 August week that is two events, 160 contracts and $4,660;
  PURR was bought and never sold, so without this it did not appear in the report at all.
  The other kind of price-0 row is a **restart artefact** — a sell against a position that
  was not open, which the platform pairs with a buy-to-cover the next morning. Those are
  dropped, and the audit sheet names them separately.

  There is a third kind, and it is the one to ask about. A **paper-account reset** makes
  open positions vanish, and IBKR writes them off exactly as it writes off an expiry: a
  sell at price 0 against lots that were genuinely open. No field in the feed separates
  them. Only the account holder knows, so ask before reporting a large expiry — in the
  24–28 August week the Wednesday-night write-offs of CRM, NU and NVDA looked like $6,511
  of expiries and were a reset. Name them with `--drop-expiry SYM,SYM --expiry-day DATE`
  and they come off on their own audit line.
- **Only SELL legs are kept**, so one row is one exit carrying its own result. This does
  discard the realised P&L on short closes, which the audit sheet reports — mention the
  figure if it is large.

Everything else is opt-in, because it encodes a judgement the user has to make:

| Flag | Use when |
|---|---|
| `--tickers A,B,C` | Restricting to names from a trading journal |
| `--drop-carry SYM --carry-day YYYY-MM-DD` | Removing positions held overnight |
| `--drop-expiry SYM --expiry-day YYYY-MM-DD` | Price-0 rows that were a reset, not an expiry |
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

**`realized_pnl` does not book losses on options that expire worthless — the workbook
does.** The `expiries` block in the summary is the number to quote: count, contracts,
premium lost, share of the week's gross loss, and a per-ticker split. Say it out loud
every week. It is the largest single line item that the broker's own numbers hide, and a
week's result read straight off `realized_pnl` will be too flattering by exactly that
amount. `cash_check` remains as an independent check on true cash movement; a materially
negative `gap` that the expiries do not account for means something else is missing.

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
