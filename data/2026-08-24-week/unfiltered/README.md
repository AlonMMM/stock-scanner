# Trading week 24–28 August 2026 — the whole account, no optional filters

The sibling directory holds the cut the account holder asked for on 29 August: journal
tickers only, and the Wednesday→Thursday carries in ANET and MRNA removed. This directory
holds the same week with **only the standing filters** — shares dropped, restart artefacts
dropped, BUY legs dropped, expiries charged the full premium. Nothing else.

Regenerate with:

```bash
python3 .claude/skills/weekly-trades/scripts/build_week.py TRADES.json \
    data/2026-08-24-week/unfiltered \
    --drop-expiry CRM,NU,NVDA --expiry-day 2026-08-26
```

| | Filtered (`../`) | Whole account (here) |
|---|---:|---:|
| Exits | 104 | 121 |
| Net | +$22,486 | +$8,360 |
| Win rate | 30% | 26% |
| Profit factor | 1.40 | 1.12 |
| Option premium | $130,362 | $162,248 |
| Return on premium | 17.2% | 4.9% |

The difference is entirely the seventeen exits in names that never reached the journal —
IBIT −$4,171, META −$3,357, AAPL −$1,313, CSCO −$877, TLT −$773, BABA −$586, GOOGL −$529 —
plus the ANET and MRNA carries at −$2,520. **Every one of them lost money.** The journal
whitelist is not a neutral filter on this week; it removes $14,127 of losses, and the
gap between the two columns is the cost of trading the names that were never written down.

Both figures are after commissions, and both charge the two Friday-night expiries
(MSTR $2,160, PURR $2,500) the full premium that IBKR reports as a zero result.
