# Trading week 14–18 September 2026 — filtered trade data

Source: Interactive Brokers **paper account**, `get_account_trades` for the 7 days ending
2026-09-19. All times in the data are US Eastern (ET).

## Files

| File | What it is |
|---|---|
| `trades-filtered.xlsx` | 4 sheets — exits, per-ticker, per-day, and the filter audit trail. Derived columns are live formulas. |
| `trades-filtered.csv` | The same 103 exit rows, values only, UTF-8 with BOM. |
| `summary.json` | The numbers the build script printed, including the expiry block and the audit chain. |
| `burn-slices.json` | Per-slice classification of where premium burned: intraday, overnight, off-hours, expiry. |
| `rules.json` | `check_rules.py --json` output — the risk-rules check consumed by the report. |

The matching report is `reports/2026-09-14-week-trades.html`.

Regenerate with:

```bash
# 1. Remove the two account-restart write-offs (see below) from the raw IBKR feed —
#    build_week.py's --drop-expiry only accepts a single date, and these two land on
#    different session days, so a small pre-filter step is needed before the main script.
#    check_rules.py and burn_slices.py don't need this — they take a SYM@DATE list
#    natively (their --vanished / third-argument), so this step is build_week.py-only.
python3 -c "
import json
with open('TRADES.json') as f: data = json.load(f)
drop = {('CL','SELL',13,0,'2026-09-17T02:10:35Z'), ('AAPL','SELL',30,0,'2026-09-19T02:36:08Z')}
data['trades'] = [t for t in data['trades']
                  if (t['symbol'], t['side'], t['size'], t['price'], t['trade_time']) not in drop]
json.dump(data, open('TRADES.resetfiltered.json','w'))
"

python3 .claude/skills/weekly-trades/scripts/build_week.py \
    TRADES.resetfiltered.json data/2026-09-14-week

python3 .claude/skills/weekly-trades/scripts/burn_slices.py \
    TRADES.resetfiltered.json data/2026-09-14-week/burn-slices.json

python3 .claude/skills/weekly-trades/scripts/check_rules.py \
    TRADES.resetfiltered.json --rules docs/risk-rules.md --json > data/2026-09-14-week/rules.json

python3 .claude/skills/weekly-trades/scripts/build_report.py \
    --summary data/2026-09-14-week/summary.json --trades data/2026-09-14-week/trades-filtered.csv \
    --rules data/2026-09-14-week/rules.json --burn data/2026-09-14-week/burn-slices.json \
    --out reports/2026-09-14-week-trades.html --label "Sep 14-18, 2026"
```

## What the filter does

IBKR returned 553 trades for the week. Five steps reduce that to **103 exit events**
worth **−$15,440**:

| Step | Rows | Effect on P&L |
|---|---:|---:|
| Trades fetched from IBKR | 553 | −$19,545 |
| − Trades outside the week window | −1 | +$2,428 |
| − Trades in the shares themselves | −81 | +$1,642 |
| − Positions wiped by the account restart (CL, AAPL) | −2 | $0 |
| − BUY legs (opens, and short closes) | −215 | +$34 |
| **= Filtered set** | **103 exits** | **−$15,440** |

Rationale for the restart line, confirmed by the account owner: the account restarted
about a week before this pull. Two price-0 SELL rows land inside this week's window and
would otherwise be charged as expiries:

| Symbol | Contracts | Session date | order_type |
|---|---:|---|---|
| CL (FOP) | 13 | 2026-09-16 | LIMIT, price 0 |
| AAPL (OPT) | 30 | 2026-09-18 | LIMIT, price 0 |

Both are synthetic `SELL ... 0 Limit` rows against positions that were open, exactly the
shape IBKR uses for a genuine worthless expiry — nothing in the feed distinguishes the
two cases. Left in, the CL row alone would charge $837,000 of premium (95% of the week's
gross loss) against a week where every other line item is in the low thousands, which is
the account-restart signature this skill's docs warn about, not a real trade. Both rows
are dropped entirely (not charged as expiries, not counted as fills) rather than run
through `--drop-expiry`, because the two write-offs fall on different session days and
that flag only accepts one date per run.

## By day

| | |
|---|---:|
| Sun 13.09 | −$978 |
| Mon 14.09 | −$931 |
| Tue 15.09 | −$7,454 |
| Wed 16.09 | −$8,467 |
| Thu 17.09 | −$2,474 |
| Fri 18.09 | +$4,863 |
| **Week** | **−$15,440** |

Win rate 25%, profit factor 0.61, option premium deployed $85,398 for a −14.9% return on
premium. 26 wins against 74 losses.

## By ticker (top and bottom)

| Ticker | P&L |
|---|---:|
| MSTR | +$6,213 |
| HOOD | +$3,197 |
| OKLO | +$2,688 |
| NQ | +$1,923 |
| ... | |
| GOOGL | −$2,468 |
| CL | −$8,488 |

CL remains the week's worst ticker even after the restart write-off is excluded — its
real, tradeable losses (not the reset) are −$8,488.

## By hold time

The one cut the broker doesn't give: grouping exits by how long the position was held.
Every bucket is reported alongside its result with the largest single name removed,
because one outsized name routinely flips a bucket's sign:

| Bucket | Exits | Premium | P&L | Return | Largest name | P&L without it |
|---|---:|---:|---:|---:|---|---:|
| ≤5 min | 8 | $2,559 | −$635 | −20% | CL | −$650 |
| 5–30 min | 34 | $31,994 | −$8,117 | −19% | MSTR | −$9,668 |
| 30–120 min | 27 | $25,439 | +$1,740 | −4% | CL | −$1,306 |
| 2–8 hours | 11 | $7,284 | +$2,545 | +9% | MSTR | −$164 |
| Overnight | 19 | $14,582 | −$9,114 | −26% | HOOD | −$11,460 |

The overnight bucket's loss holds up even without its best name (HOOD) — it goes from
−26% to a worse −79% on the rest, so this bucket was a real source of bleed this week,
not one bad overnight position hiding a break-even book.

## Where the premium burned (`burn-slices.json`)

336 closing slices, 240 losing, $27,853 total burn:

| Class | Slices | Premium | Burn | Burn % | Stops seen |
|---|---:|---:|---:|---:|---:|
| Intraday | 188 | $50,134 | $16,734 | 33% | 54 |
| Overnight | 46 | $16,240 | $9,890 | 61% | 0 |
| Off-hours | 6 | $3,520 | $1,229 | 35% | 0 |

Overnight slices burned at nearly double the intraday rate and carried zero visible
stops. One position (CLV6, −$2,428) has no reconstructable cost basis — it was opened
before this window began.

## Risk-rules check (`docs/risk-rules.md`)

Run against this week (account value $127,258):

- **FAIL — rule 15** (a day down 7% ends the day): 2026-09-15 closed −$9,536. Caveat: this
  checks realised P&L plus written-off premium, not full account value, so it can miss or
  over-flag relative to the actual rule.
- **NOTE — rule 4**: $36,103 of premium entered at or below $0.30 across 13 symbols;
  estimated round-trip commission friction $1,805–$3,971.
- **PASS — rule 12** (total open exposure under 12%): peak open cost $10,500 (8.3%),
  never breached the $15,271 cap.
- **PASS — rule 6** (no unprotected position over 5% overnight): nothing above the cap at
  a session boundary. A 15-lot NQ position on 2026-09-18 initially flagged at ~$7,875
  against the $6,363 cap — but that used a hardcoded 100x equity-option multiplier on an
  NQ future option, which is actually 20x. The real market value was $1,575, well under
  the cap. `check_rules.py` now reads each symbol's multiplier from its own fills instead
  of assuming 100 (fixed 2026-09-19).
- **Not checkable from the trade feed** (10 of 14 rules): most need the option's expiry
  date, an equity curve, or trader intent, none of which the fills carry. See `rules.json`
  for the full list — a clean-looking check here is not a clean bill of health.

## Derived columns

Only five fields come from IBKR: quantity, exit price, proceeds, net P&L, commission.
Everything else is computed, and in the `.xlsx` it is a formula, not a pasted number:

```
multiplier    = proceeds / (quantity × exit price)
premium paid  = proceeds − net P&L
entry price   = premium paid / (quantity × multiplier)
% of premium  = net P&L / premium paid
```

## Two things to know before using these numbers

**Net P&L is already after commissions.** IBKR reports `realized_pnl` net of the
commissions on both legs of a round trip. The commission column is the sell leg only, and
is there for reference — do not subtract it again.

**Two account-restart write-offs were excluded, not two expiries.** Left in, this week's
headline would read −$853,505 net P&L, driven almost entirely by an $837,000 CL "expiry."
That number is the account restart from about a week ago wiping open CL and AAPL
positions, not a trading loss — confirmed by the account owner. The −$15,440 figure in
this report already excludes both.

## Verification

`audit_reconciles: true` in `summary.json` — the audit-sheet cross-check against the
exits sheet agrees with the printed total. `cash_check` shows a $6,705 gap between cash
flow and realised P&L; `worst_gaps` names AMZN, CL, NQ, MSTR and AAPL as the largest
contributors, consistent with normal FIFO cost-basis timing rather than a missing filter.
