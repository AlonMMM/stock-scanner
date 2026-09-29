# Worked example — NVDA, 2026-09-19

A full run of the `technical-scan` skill against real IBKR data, kept here as
a reference so the script can be re-run and diffed against known-good output
without needing a live broker session.

- `inputs/` — the raw `get_price_history` payloads (daily/hourly/5-min for
  NVDA, 5-min and daily for the SPY benchmark) and the assembled
  `nvda_options_oi.json` open-interest table for the 2026-09-21 (2 DTE)
  expiry, exactly as pulled from IBKR. `spy_daily.json` is what beta is fit
  from.
- `out/` — `analyze.py`'s output: the seven PNG charts, `summary.json`, and
  the self-contained `report.html`.

Re-run it with:

```bash
python3 ../../../.claude/skills/technical-scan/scripts/analyze.py \
  --ticker NVDA --benchmark SPY \
  --daily inputs/nvda_daily.json --hourly inputs/nvda_hourly.json \
  --intraday inputs/nvda_5min.json --bench-intraday inputs/spy_5min.json \
  --bench-daily inputs/spy_daily.json \
  --options inputs/nvda_options_oi.json --outdir out/
```

Headline numbers from this run (spot 222.53, 2026-09-19 close):

| | |
|---|---|
| Daily pivot (PP / R1 / S1) | 221.01 / 223.99 / 219.29 |
| Prior week range | 217.20 - 234.76 |
| Volume-profile POC / VAH / VAL | 219.55 / 219.94 / 218.69 |
| Call wall / Put wall (21-Sep exp.) | 240 / 210 |
| Max pain (21-Sep exp.) | 215 |
| Beta vs SPY: 60-day (context) / 20-day rolling (used for alpha) | 1.93 / **2.81** |
| Beta regime shift | +0.88 — flagged, a real change in market sensitivity |
| Beta-adjusted alpha, end of window | +1.10pp |
| Named divergence windows | 09-17 15:05 held flat through a SPY rally; 09-18 13:30 opened against a falling tape (+0.94pp vs SPY -0.24pp); 09-18 18:15 held flat through another SPY move up |
| RS Line (IBD/Minervini) at a new 3-month high? | No |
| RS-Ratio / RS-Momentum (open RRG reconstruction) | 100.6 / 99.2 |
| Rotation quadrant | **Weakening** — still ahead of SPY over the lookback, but losing steam, even on a day it led the tape intraday |
| Nearest support zone (6 sources: PP/VWAP/VAH/POC/S1/VAL) | 219.75 (-1.2%) |
| Nearest resistance (R1) | 223.99 (+0.7%) |
| If long from 222.53: stop 219.75 / target 223.99 | R:R 0.53 (1.14 to the R2 extension) |
| If short from 222.53: stop 223.99 / target 219.75 | R:R 1.90 (3.96 to the prior-week-low/S2 extension) |

The trade-plan numbers are arithmetic from the level ladder, not a
directional call — both the long and short case are always computed
together; see `SKILL.md`'s caveats section before quoting either on its own.
The RS-Ratio/RS-Momentum quadrant is an open, non-proprietary reconstruction
of the general Relative Rotation Graph method, not the licensed
StockCharts/relativerotationgraphs.com indicator — see `SKILL.md` section 5
for sources and the exact caveat to repeat when quoting a quadrant.
