# Trading week 24–28 August 2026 — filtered trade data

Source: Interactive Brokers **paper account**, `get_account_trades` for the 7 days ending
2026-08-29. All times in the data are US Eastern (ET).

## Files

| File | What it is |
|---|---|
| `trades-filtered.xlsx` | 4 sheets — exits, per-ticker, per-day, and the filter audit trail. Derived columns are live formulas. |
| `trades-filtered.csv` | The same 104 exit rows, values only, UTF-8 with BOM. |
| `summary.json` | The numbers the build script printed, including the expiry block and the audit chain. |

The matching report is `reports/2026-08-24-week-open.html`.

Regenerate with:

```bash
python3 .claude/skills/weekly-trades/scripts/build_week.py TRADES.json data/2026-08-24-week \
    --tickers ANET,NQ,MU,GC,CL,QQQ,AMZN,CRM,AAOI,SMCI,TSLA,OKLO,NU,NVDA,PLTR,MRNA,NOW,MSFT,INTC,MSTR,PURR,ES \
    --drop-carry ANET,MRNA --carry-day 2026-08-27 \
    --drop-expiry CRM,NU,NVDA --expiry-day 2026-08-26
```

## What the filter does

IBKR returned 716 trades. Seven steps reduce that to **104 exit events** worth
**+$22,486**:

| Step | Rows | Effect on P&L |
|---|---:|---:|
| Trades fetched from IBKR | 716 | +$5,547 |
| − Trades in the shares themselves (MU, CSCO) | −16 | +$2,408 |
| − Positions that vanished in the paper reset (CRM, NU, NVDA) | −5 | $0 |
| − Sells at price 0 with nothing open (restart artefacts) | −3 | $0 |
| = Expiry rows, charged the full premium | 2 | **−$4,660** |
| − BUY legs (opens, and short closes) | −335 | +$5,064 |
| − Tickers absent from the trading journal | −46 | +$11,607 |
| − Positions carried Wednesday→Thursday, except CRM and PLTR | −9 | +$2,520 |
| **= Filtered set** | **104 exits** | **+$22,486** |

Rationale for each step, as specified by the account owner:

1. **Share trades** are not part of what this account tracks.
2. **Restart artefacts.** A platform restart on Wednesday evening sold positions that were
   already flat, and the platform paired each with a buy-to-cover the next morning. MSTR
   (90 contracts) and OKLO (65) are the two. They are not executions and are dropped.
3. **The paper reset.** On Wednesday night CRM (70), NU (340) and NVDA (31) were written
   off at price 0 against lots that were genuinely open. That is not an expiry — the
   account holder reset the paper account and the positions simply vanished. The feed
   writes a reset and an expiry identically and carries no field that separates them, so
   these are named by hand via `--drop-expiry` and dropped.
4. **Expiries are losses.** The remaining price-0 sells did close something: an option
   that expired worthless. IBKR stamps `realized_pnl = 0` on those and books nothing, so
   the premium simply disappears from the report. Here each is charged the cost of the
   lots that died — two events, 160 contracts, **$4,660**, 8% of the week's gross loss:

   | | Contracts | Entry | Premium lost |
   |---|---:|---:|---:|
   | PURR, Fri 28.08 | 100 | $0.25 | $2,500 |
   | MSTR, Fri 28.08 | 60 | $0.36 | $2,160 |

   PURR was bought and never sold at a price, so before this it did not appear in the
   report at all.
5. **BUY legs** are dropped so each row is one exit carrying its own result. Note this
   removes 335 rows that together held −$5,064 of realised P&L from closing short
   positions.
6. **Journal tickers only.** Kept: ANET, NQ, MU, GC, CL, QQQ, AMZN, CRM, AAOI, SMCI,
   TSLA, OKLO, NU, NVDA, PLTR, MRNA, NOW, MSFT, INTC, MSTR, PURR, ES. Everything else
   (IBIT, META, AAPL, CSCO, TLT, BABA, GOOGL) was traded but never written down.
7. **Overnight carries** from Wednesday into Thursday were removed except CRM and PLTR:
   ANET (−$771) and MRNA (−$1,748) are out.

## By day

| | |
|---|---:|
| Mon 24.08 | +$4,904 |
| Tue 25.08 | −$7,017 |
| Wed 26.08 | −$5,522 |
| Thu 27.08 | +$35,445 |
| Fri 28.08 | −$5,323 |
| **Week** | **+$22,486** |

Win rate 30%, profit factor 1.40, option premium deployed $130,362 for a 17.2% return on
premium.

## Derived columns

Only five fields come from IBKR: quantity, exit price, proceeds, net P&L, commission.
Everything else is computed, and in the `.xlsx` it is a formula, not a pasted number:

```
multiplier    = proceeds / (quantity × exit price)
premium paid  = proceeds − net P&L
entry price   = premium paid / (quantity × multiplier)
% of premium  = net P&L / premium paid
```

An expiry row has no exit price to divide by, so its multiplier and premium come from the
FIFO book instead; the rest follows the same way and lands at −100% of premium.

Reconstructed entry prices match the owner's journal to the cent — PLTR $0.667 against
"30 at 0.66", CRM $0.237 against "60 at 0.24", MSTR $0.246 against "100 at 0.22".

## Two things to know before using these numbers

**Net P&L is already after commissions.** IBKR reports `realized_pnl` net of the
commissions on both legs of a round trip. The commission column is the sell leg only, and
is there for reference — do not subtract it again.

**A day's total includes the premium that expired that night.** The Friday figure carries
$4,660 of expiries, which IBKR does not report as a loss at all. Any figure taken straight
from `realized_pnl` will be better than the account by that amount.

## Verification

The workbook's formulas could not be recalculated in the environment that produced it —
LibreOffice would not evaluate even a three-cell test file. Instead every formula was
checked by re-deriving its result in Python and comparing against an independently
generated CSV: 104 rows, zero mismatches, and the audit chain reconciling to $22,486.39.
Excel and Google Sheets recalculate on open.

Both expiries were also read back against the raw fills: MSTR bought 60 at $0.36 on
Thursday 15:21 and written off Friday 22:16; PURR bought 100 at $0.25 on Thursday 11:33
and written off the same Friday minute.
