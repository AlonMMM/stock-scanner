# Worked example — NVDA, 2026-09-19

A full run of the `technical-scan` skill against real IBKR data, kept here as
a reference so the script can be re-run and diffed against known-good output
without needing a live broker session.

- `inputs/` — the raw `get_price_history` payloads (daily/hourly/5-min for
  NVDA, 5-min for the SPY benchmark) and the assembled `nvda_options_oi.json`
  open-interest table for the 2026-09-21 (2 DTE) expiry, exactly as pulled
  from IBKR.
- `out/` — `analyze.py`'s output: the five PNG charts, `summary.json`, and
  the self-contained `report.html`.

Re-run it with:

```bash
python3 ../../../.claude/skills/technical-scan/scripts/analyze.py \
  --ticker NVDA --benchmark SPY \
  --daily inputs/nvda_daily.json --hourly inputs/nvda_hourly.json \
  --intraday inputs/nvda_5min.json --bench-intraday inputs/spy_5min.json \
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
| Relative strength vs SPY (intraday) | +1.6pp, NVDA leading |
