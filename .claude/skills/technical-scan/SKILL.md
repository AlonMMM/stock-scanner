---
name: technical-scan
description: >-
  Given one ticker, pull daily/hourly/intraday price and volume from Interactive
  Brokers, work out support and resistance (pivots, swing highs/lows, volume
  profile / VWAP), find the options open-interest "magnets" (call wall, put
  wall, max pain) for the nearest expiry, and measure how the stock is moving
  relative to a benchmark (SPY by default) during the session. Produces five
  charts and a one-page report with the charts embedded, not just numbers.
  Use this whenever the user asks for a technical read on a stock, "רמות
  טכניות", "תמיכות והתנגדויות", "מגנטים באופציות", "איפה ה-Call wall / Put
  wall", "מה עושה המניה מול השוק היום", or names a ticker and asks "מה קורה
  בו טכנית" / "תן לי ניתוח טכני". Not for fundamental analysis, news, or
  earnings commentary — this is levels and positioning only.
---

# Technical scan: levels, volume, options magnets, relative strength

## What this actually measures, and why each piece is there

A ticker's chart alone tells you where price has been. Four more things tell
you where it is likely to *react*, and this skill exists because IBKR's MCP
tools carry every one of them as real, queryable data — nothing here is
approximated from a paid data vendor's API or scraped:

**1. Volume across three timeframes, not one.** Daily volume tells you if a
level was defended by real participation or drifted through on thin tape.
Hourly volume shows which part of *this* multi-day range was accepted
(volume clusters) vs. rejected (thin, fast moves). Minute-level volume is
what you need for an intraday **volume profile** — the actual distribution of
traded volume by price, not just by time. The point of control (POC, the
single busiest price) and the value area (VAH/VAL, the band holding 70% of
the session's volume) are the closest thing to hard evidence for "where the
market has been transacting," and they move every day. A price chart without
this is missing the one axis that says *conviction*.

**2. Support/resistance from three independent sources, not eyeballed
trendlines.** This skill computes three kinds and keeps them separate because
they fail differently:
   - **Classic floor pivots** (PP/R1-R3/S1-S3) from the prior day's H/L/C.
     Mechanical, exchange-agnostic, and exactly what a large share of
     intraday desks quote out loud — so the crowd itself often defends them.
   - **Swing highs/lows (fractals) on the daily chart, clustered.** A single
     old high means little; three or four separate touches within ~0.8% of
     each other over months is a real level. Clustering with a strength
     count is what turns "eyeballing the chart" into something reproducible.
   - **Volume profile POC/VAH/VAL from the intraday tape.** This is a
     *volume*-based level, not a *price-touch*-based one — a POC can matter
     even if price only spent one session there, because it says "this is
     where size traded."
   Three sources that agree are a much stronger level than any one of them
   alone; the report shows all three so that agreement (or disagreement) is
   visible rather than asserted.

**3. Options open interest — call wall, put wall, max pain.** Dealers who are
short options near a large open-interest strike have a standing hedging
flow that tends to dampen moves through that strike (for the strike the
dealer is short gamma against) or accelerate them (short gamma the other
way). This skill does **not** try to model dealer gamma exposure (GEX),
because that requires a reliable per-contract IV and sign convention about
who is long/short which side — assumptions that are frequently wrong and
create false precision. Instead it uses only **raw open interest**, which
IBKR returns directly per contract and requires no modeling:
   - **Call wall** = strike with the largest call OI. **Put wall** = strike
     with the largest put OI. These behave like a magnetic ceiling/floor
     more often than not, especially close to expiry.
   - **Max pain** = the strike that minimizes total intrinsic value owed to
     option holders at expiry, computed from the full OI table. It is a
     documented (if debated) pinning tendency, strongest in the last 1-2
     trading days before expiry.
   Use the **nearest expiry** (including 0-2 DTE weeklies) for this,
   deliberately — pinning and wall effects are strongest exactly where dealer
   hedging is most concentrated in time, which is right before expiry, not
   the monthly.

**4. Relative strength vs. a benchmark, intraday, rebased every session.**
"NVDA is up 2% today" means something different if SPY is up 1.8% (broad
tape) vs. flat (stock-specific). This skill normalizes both the ticker and
the benchmark to their own session-open and plots the spread — this is what
separates "the market carried it" from "this name is doing its own thing,"
which matters for anyone reading order flow or gauging whether a level will
hold on a weak vs. strong tape day.

## Workflow

### 1. Resolve the ticker and benchmark

```
search_contracts(query=<TICKER>)
```
Pick the row with an **exact symbol match** and `STK` in `sections` (primary
US listing — watch for leveraged/inverse/income ETFs that share the ticker
root, e.g. `NVDL`, `NVDY` are not `NVDA`). Do the same for the benchmark if
it isn't already known (SPY's contract_id is `756733`; QQQ, IWM, or a sector
SPDR are reasonable substitutes when the ticker doesn't track the broad
market — ask if unsure, don't guess a sector).

### 2. Pull price history — three timeframes, both symbols

```
get_price_history(contract_id, security_type="STK", step="ONE_DAY",  period="SIX_MONTHS", outside_rth=false)
get_price_history(contract_id, security_type="STK", step="ONE_HOUR", period="ONE_MONTH",   outside_rth=false)
get_price_history(contract_id, security_type="STK", step="FIVE_MINS", period="TWO_DAYS",   outside_rth=false)
```
Fetch the same **FIVE_MINS/TWO_DAYS** call for the benchmark. Use
`FIVE_MINS` rather than `ONE_MIN` for the intraday leg — a two-day window at
one-minute resolution is ~780 bars per symbol, which is far more than the
volume-profile/VWAP math or the chart need and just burns context; five
minutes keeps ~150-160 bars per symbol and loses nothing that matters at
this timeframe. If the user specifically wants tick-level intraday detail
for a single session, `ONE_MIN`/`ONE_DAY` is fine — just don't default to it.

Save each response to disk as-is (the tool result IS the schema
`analyze.py` expects — `time`/`open`/`high`/`low`/`close`/`volume` parallel
arrays). Do not retype or reformat it.

### 3. Pull the options chain and open interest for the nearest expiry

```
get_option_parameters(underlying_contract_id)
```
Take the **first non-regular (weekly/daily) expiration** if the goal is
near-term magnets/pinning (most relevant, most volatile), or
`current_expiration` (the front monthly) for a steadier read. Prefer the
near one unless the user asks about a specific date.

```
get_option_data(expiration_id, min_strike=<spot*0.92>, max_strike=<spot*1.08>)
```
Get the spot price first (`get_price_snapshot`) and bound the strike range
around it — roughly 15 strikes on each side is enough to find the walls
without pulling the whole chain. Then, **for every strike in range**, call:

```
get_price_snapshot(contract_id=<call_contract_id>, market_data_names=["option_open_interest"])
get_price_snapshot(contract_id=<put_contract_id>,  market_data_names=["option_open_interest"])
```
There is no batched form of this call — budget roughly 2 calls per strike
(30 calls for 15 strikes each side). This is the expensive part of the
skill; narrowing the strike range is the main lever if it needs to be
cheaper. Assemble the results into:

```json
{
  "ticker": "NVDA", "expiry": "2026-09-21", "dte": 2, "spot": 222.53,
  "strikes": [
    {"strike": 205, "call_oi": 540, "put_oi": 1060},
    ...
  ]
}
```
and save as `options_oi.json`.

### 4. Run the analysis script

```bash
pip install matplotlib numpy pandas mplfinance   # once per environment
python3 <this-skill-dir>/scripts/analyze.py \
  --ticker NVDA --benchmark SPY \
  --daily nvda_daily.json --hourly nvda_hourly.json \
  --intraday nvda_5min.json --bench-intraday spy_5min.json \
  --options options_oi.json --outdir out/
```
This does no network I/O — it only reads the files above. It prints a JSON
summary to stdout and writes to `--outdir`:
- `01_daily.png`, `02_hourly.png`, `03_intraday_volume_profile.png`,
  `04_options_oi.png`, `05_relative_strength.png`
- `summary.json` (the same summary, saved)
- `report.html` — a self-contained page with all five charts embedded as
  base64 and a Hebrew-language numeric summary, for handing over as a file
  or reading directly.

### 5. Present it with the charts, not just the numbers

The user wants to *see* the levels, not just read strike numbers. Either:
- Publish `report.html` (or a redesigned version of it) as an **Artifact**
  so it renders inline — load the `artifact-design` skill first if building
  a custom page rather than using the script's own `report.html` directly,
  and embed the five PNGs as base64 `data:` URIs (they total well under 1MB,
  comfortably inside the 16MB artifact limit).
- Or send the PNGs / `report.html` directly as files if the session isn't
  artifact-capable.

Quote the numeric summary in the reply too (pivots, POC/VAH/VAL, call
wall/put wall/max pain, RS spread) — the charts support the numbers, they
don't replace saying them.

## Data schema reference

`analyze.py --daily/--hourly/--intraday/--bench-intraday` each expect the
raw `get_price_history` JSON (a dict with `time`, `open`, `high`, `low`,
`close`, `volume` parallel arrays, ISO timestamps). `--options` expects the
`options_oi.json` schema shown above. The script never calls IBKR itself —
all fetching happens in the conversation, by design, so it stays usable in
any environment that has the JSON files, and so a fetch failure is visible
to Claude (and reported to the user) rather than silently swallowed inside
a script.

## Caveats to say out loud every time

- **Max pain and OI walls are historical tendencies, not guarantees.** They
  describe dealer hedging pressure, not a price target. Say this plainly
  when reporting them — a caveat inside this file that is not repeated in
  the chat is a caveat nobody reads.
- **No gamma exposure (GEX) model is computed.** `option_midpoint_iv` from
  IBKR is frequently invalid (`isValid: false`) outside market hours or for
  thin strikes, and a GEX sign convention is an assumption, not a fact — this
  skill deliberately stays on raw OI, which needs no such assumption.
- **The options snapshot loop is the token/latency-expensive step.** If
  asked to scan several tickers, say so before doing all of them back to
  back, or narrow the strike range further.
- **Relative strength needs a benchmark that actually applies.** SPY is a
  reasonable default; a single-stock reader in a sector that diverges hard
  from the S&P 500 (e.g. gold miners, biotech) is better served by a sector
  ETF — ask if it isn't obvious.
- **This is not investment advice**, and the report should say so.
