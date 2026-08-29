# Trading week 24–28 August 2026 — filtered trade data

Source: Interactive Brokers **paper account**, `get_account_trades` for the 7 days ending
2026-08-29. All times in the data are US Eastern (ET).

## Files

| File | What it is |
|---|---|
| `trades-filtered.xlsx` | 4 sheets — exits, per-ticker, per-day, and the filter audit trail. Derived columns are live formulas. |
| `trades-filtered.csv` | The same 102 exit rows, values only, UTF-8 with BOM. |

The matching report is `reports/2026-08-24-week-open.html`.

## What the filter does

IBKR returned 716 trades. Five steps reduce that to **102 exit events** worth
**+$27,146**:

| Step | Rows | Effect on P&L |
|---|---:|---:|
| Trades fetched from IBKR | 716 | +$5,547 |
| − Trades in the shares themselves (MU, CSCO) | −16 | +$2,408 |
| − Technical expiry rows (price 0) | −10 | $0 |
| − BUY legs (opens, and short closes) | −335 | +$5,064 |
| − Tickers absent from the trading journal | −48 | +$11,607 |
| − Positions carried Wednesday→Thursday, except CRM and PLTR | −7 | +$2,519 |
| **= Filtered set** | **300 fills → 102 exits** | **+$27,146** |

Rationale for each step, as specified by the account owner:

1. **Share trades** are not part of what this account tracks.
2. **Price-0 rows** are an artifact of a platform restart, not executions.
3. **BUY legs** are dropped so each row is one exit carrying its own result. Note this
   removes 335 rows that together held −$5,064 of realised P&L from closing short
   positions.
4. **Journal tickers only.** Kept: ANET, NQ, MU, GC, CL, QQQ, AMZN, CRM, AAOI, SMCI,
   TSLA, OKLO, NU, NVDA, PLTR, MRNA, NOW, MSFT, INTC, MSTR, PURR, ES. Everything else
   (IBIT, META, AAPL, CSCO, TLT, BABA, GOOGL) was traded but never written down.
5. **Overnight carries** from Wednesday into Thursday were removed except CRM and PLTR:
   ANET (−$771) and MRNA (−$1,748) are out.

## Derived columns

Only five fields come from IBKR: quantity, exit price, proceeds, net P&L, commission.
Everything else is computed, and in the `.xlsx` it is a formula, not a pasted number:

```
multiplier    = proceeds / (quantity × exit price)
premium paid  = proceeds − net P&L
entry price   = premium paid / (quantity × multiplier)
% of premium  = net P&L / premium paid
```

Reconstructed entry prices match the owner's journal to the cent — PLTR $0.667 against
"30 at 0.66", CRM $0.237 against "60 at 0.24", MSTR $0.246 against "100 at 0.22".

## Two things to know before using these numbers

**Net P&L is already after commissions.** IBKR reports `realized_pnl` net of the
commissions on both legs of a round trip. The commission column is the sell leg only, and
is there for reference — do not subtract it again.

**`realized_pnl` does not book losses on options that expired worthless.** Ten such rows
appear in the raw week. On a pure cash-flow basis the whole account is roughly $4,800
below what the realised figures suggest; MSTR alone is −$8,722 in cash against −$4,990
here. The filtered set is a record of exits actually taken, not a complete economic P&L.

## Verification

The workbook's formulas could not be recalculated in the environment that produced it —
LibreOffice would not evaluate even a three-cell test file. Instead every formula was
checked by re-deriving its result in Python and comparing against an independently
generated CSV: 102 rows, zero formula-text mismatches, zero numeric mismatches, and the
audit chain reconciling to $27,146.42. Excel and Google Sheets recalculate on open.
