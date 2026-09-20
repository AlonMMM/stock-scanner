---
name: technical-scan
description: >-
  Given one ticker, pull daily/hourly/intraday price and volume from Interactive
  Brokers, work out support and resistance (pivots, swing highs/lows, volume
  profile / VWAP), find the options open-interest "magnets" (call wall, put
  wall, max pain) for the nearest expiry, measure how the stock is moving
  relative to a benchmark (SPY by default, but swapped for whatever actually
  correlates best when a quick beta/correlation check says the official
  sector or the broad market is the wrong fit) both intraday (beta-adjusted
  alpha, a rolling beta that exposes regime shifts) and positionally (an IBD/Minervini
  relative-strength line plus an open reconstruction of a Relative Rotation
  Graph's RS-Ratio/RS-Momentum quadrant), and merge every level found into one
  trade-planning ladder with mechanical risk/reward for a long or short from
  the current price. Produces seven charts and a one-page report with the
  charts embedded, not just numbers. Use this whenever the user asks for a
  technical read on a stock, "רמות טכניות", "תמיכות והתנגדויות", "מגנטים
  באופציות", "איפה ה-Call wall / Put wall", "מה עושה המניה מול השוק היום",
  "האם היא מובילה או נגררת אחרי המדד", "איפה לשים סטופ", "מה יחס הסיכוי-סיכון",
  or names a ticker and asks "מה קורה בו טכנית" / "תן לי ניתוח טכני" / "אני
  שוקל לפתוח פוזיציה, מה אתה רואה". Not for fundamental analysis, news, or
  earnings commentary — this is levels and positioning only, and it never
  names a direction (long/short) on its own initiative.
---

# Technical scan: levels, volume, options magnets, relative strength, trade plan

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

**4. Relative strength vs. a benchmark — beta-adjusted, continuous through the
day, not a single snapshot number.** "NVDA is up 2% today" means something
different if SPY is up 1.8% vs. flat, but a raw spread also conflates two
different things: a high-beta name is *supposed* to move more than the index
in both directions, so out-beta-ing the tape on a strong day isn't
relative strength, it's leverage. This skill fits **beta** from 60 trading
days of daily returns (`beta = cov(r_stock, r_bench) / var(r_bench)`,
reported with its correlation so a weak fit is visible, not hidden) and
computes **alpha(t) = stock's session-cum-% - beta × benchmark's
session-cum-%** at every intraday bar — the excess return net of what beta
alone would predict, evolving through the whole session rather than read
once at the end.

On top of the continuous alpha curve, a **rolling 30-minute scan** flags two
things explicitly rather than leaving them for someone to spot in a
squiggly line: a window where the stock's move had the **opposite sign** of
the benchmark's ("moved against the tape"), and a window where the
benchmark made a real move while the stock stayed inside a flat band ("held
through a real index move"). Both get a shaded band and a label directly on
the chart, with start time and both legs' moves in the summary — this is
the answer to "did it hold up, or even move against the index, during the
day," not just at the open. See `analyze.py`'s `detect_divergence_windows`
for the exact thresholds and why they're set where they are (tight enough
to matter, coarse enough that a single noisy bar can't trigger a flag).

**Noise handling, specifically for when there is no real trading:** bars
with zero volume on either leg (a halt, a stale print, a data hiccup) are
dropped before any of this is computed. Every session is re-based to 0 at
*its own* open — never the whole window's first bar — and plotted on a
positional (bar-index) x-axis with a hard visual break at each session
boundary, so the overnight/weekend gap between sessions is never drawn as a
sloped line implying a real move happened while the market was closed. The
drawn alpha line is a short rolling median (smooths single-bar bid/ask
bounce) and the divergence scan runs on the same rebased series with its
own coarser window — the combination is what keeps the chart to a handful
of real signals a day instead of a dozen-plus flickers.

**5. Positional relative strength: rolling beta, the RS Line, and a rotation
quadrant.** Section 4's alpha is a same-day number — it answers "is the
stock beating the tape right now." It doesn't answer whether that's a
one-day blip or the continuation of a weeks-long trend, and it silently
assumes the 60-day beta is still the right multiplier. Researching how
practitioners actually handle this (see Sources below) turned up three
specific, well-established techniques this skill now runs on top of the
intraday alpha, not instead of it:

  - **A rolling beta, not one static number.** Academic work on intraday
    beta variation (Kellogg/Todorov; arXiv:2310.19992) finds that a stock's
    sensitivity to the market genuinely drifts within and across sessions —
    a single 60-day estimate quietly assumes it hasn't. `rolling_beta_series`
    computes a trailing 20-trading-day beta (a window matched to a
    swing/day trader's decision cadence, per IBKR's own quant-research
    writeup on rolling beta) and **that** recent value, not the 60-day one,
    is what section 4's alpha is actually computed from. The 60-day figure
    is kept alongside it purely as context: when the two disagree by more
    than ~0.3, the report calls it out explicitly as a **beta regime
    shift** — the stock's relationship to the market itself has moved, not
    just its price. On the NVDA run this was not a hypothetical: 20-day
    beta measured 2.81 against a 60-day beta of 1.93.
  - **The classic RS Line (IBD/Minervini-style).** `compute_rs_line` plots
    price(stock)/price(benchmark) × 100 against its own moving average on
    the daily timeframe — a slow, positional read, deliberately separate
    from the intraday alpha above. A fresh high in this *line* is a
    documented relative-strength breakout signal in its own right, and can
    lead a breakout in the stock's own price rather than follow it.
  - **A rotation quadrant (RS-Ratio × RS-Momentum).** Relative Rotation
    Graphs (RRGs, Julius de Kempenaer) plot a security's relative TREND
    (RS-Ratio) against the RATE OF CHANGE of that trend (RS-Momentum), both
    as z-scores centered on 100, landing every security in one of four
    quadrants: **Leading** (outperforming, still gaining), **Weakening**
    (outperforming, losing steam), **Lagging** (underperforming, still
    fading), **Improving** (underperforming, turning up). The exact
    StockCharts/relativerotationgraphs.com formula is proprietary;
    `compute_rs_rotation` reconstructs the publicly documented general
    method (smoothed relative price, z-scored against its own recent
    history for the ratio; the ratio's own rate of change, z-scored the
    same way, for momentum) rather than claiming to replicate the licensed
    indicator — say this plainly if reporting the quadrant. On the NVDA run
    this caught something the intraday chart alone did not: NVDA sat in
    **Weakening** (RS-Ratio 100.6, still nominally ahead of SPY over the
    lookback, but RS-Momentum 99.2 — that lead was losing steam) even on a
    day where the intraday alpha chart showed it clearly leading the tape.
    Both are true at once, at different timeframes; report both rather than
    picking the one that tells a cleaner story.

  *Sources for this section:* [Rolling Beta guide, Interactive Brokers
  Campus](https://www.interactivebrokers.com/campus/ibkr-quant-news/rolling-beta-the-real-world-guide-to-measuring-stock-risk-against-the-market/) ·
  [Recalcitrant Betas: Intraday Variation in the Cross-Sectional Beta, Todorov
  et al. (Kellogg/Northwestern)](https://www.kellogg.northwestern.edu/faculty/todorov/htm/papers/sit.pdf) ·
  [Robust Estimation of Realized Correlation: intraday beta fluctuations,
  arXiv:2310.19992](https://arxiv.org/pdf/2310.19992) ·
  [Relative Rotation Graphs, StockCharts
  ChartSchool](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts) ·
  [RS-Ratio/RS-Momentum construction,
  relativerotationgraphs.com](https://relativerotationgraphs.com/educational/the-building-blocks-for-rrg/) ·
  [RS Ratio and Momentum calculations, RRG-Lite (open
  implementation)](https://github.com/BennyThadikaran/RRG-Lite/wiki/RS-ratio-and-Momentum-calculations) ·
  [Mark Minervini's Trend Template / RS Line,
  Deepvue](https://deepvue.com/screener/minervini-trend-template/).
  No extra IBKR calls are needed for any of this — it's computed entirely
  from the daily bars (`--daily`/`--bench-daily`) already fetched for
  section 1 and the beta fit.

**6. A trade-planning ladder: every level above, merged into one map relative
to spot.** The first five sections each answer a different question in a
different frame (where has volume traded, where do swings cluster, where is
dealer OI, how is the stock doing vs. the tape). None of them on its own
answers what a trader actually opens the tool for: "if I'm putting a
position on right now, where's my stop, where's my target, and does more
than one thing agree on that level?" `build_level_ladder` collects
**every** level the earlier steps produced — both pivots, both volume-profile
bounds, VWAP, the prior week's H/L, both option walls, max pain, and every
swing cluster — tags each with its source, and sorts them by distance from
spot. Levels within 0.6% of each other are merged into one **zone**, so a
level that is simultaneously the daily pivot, the VWAP, the volume-profile
VAH, the POC and the S1 pivot (this happens — see the NVDA example) shows up
as one six-source zone with real weight, not five separate lines a reader
has to notice line up themselves. `trade_scenarios` then does the
arithmetic — nearest support as a long's stop and nearest resistance as its
target (mirrored for a short), plus a second, farther target for what
happens if the first one breaks — entirely mechanically from the current
price. **This never picks a direction.** It always returns both the long
and the short scenario; which one, if either, applies is for the trader to
decide from everything else in the report (trend, relative strength, where
spot sits vs. VWAP and the pivot). Say this explicitly whenever reporting
it — "here's the level map and what the risk/reward looks like from here"
is the deliverable, not "you should go long/short."

## Workflow

### 1. Resolve the ticker and benchmark

```
search_contracts(query=<TICKER>)
```
Pick the row with an **exact symbol match** and `STK` in `sections` (primary
US listing — watch for leveraged/inverse/income ETFs that share the ticker
root, e.g. `NVDL`, `NVDY` are not `NVDA`).

**Pick the benchmark by what actually moves the stock, not by its official
sector classification.** GICS/official sector is a starting guess, not the
answer — a name's real driver is frequently something else entirely (a
commodity, a single dominant customer/theme, a currency). The MSTR case is
the concrete example: its official sector is Software (→ IGV), but a quick
60-day correlation check showed IGV at 0.43 and SPY at 0.39 — both weak —
while IBIT (a spot-Bitcoin ETF, nothing to do with its GICS sector) came in
at 0.82 with a clean ~2x beta, because MSTR's balance sheet is a leveraged
bitcoin position. Default to SPY, but before committing to it (or to the
"obvious" sector ETF) for a name where the fit looks like it might be
loose, spend one cheap daily-bar pull on a plausible alternative — a sector
SPDR, a commodity/crypto ETF, a mega-cap peer it's known to trade with —
and compare correlation and beta the same way (see the benchmark-selection
check below). Use whichever one actually fits; say so either way, including
when SPY turns out to be the right answer. SPY's contract_id is `756733`.
Ask the user if there's no clear candidate to test.

**Quick benchmark-fit check (cheap, do this whenever the "obvious"
benchmark is in doubt):** pull just the daily bars (`ONE_DAY`/`SIX_MONTHS`)
for each candidate — no hourly/intraday/options needed yet — and compare:
```python
r = prices.pct_change().dropna()
r60 = r.tail(60)
beta = r60["stock"].cov(r60["candidate"]) / r60["candidate"].var()
corr = r60["stock"].corr(r60["candidate"])
```
Report both `beta` and `corr` for every candidate tried, not just the
winner — a low-correlation "winner" among weak options is still weak, and
that's worth saying. Once a benchmark is picked this way, run the full
workflow (steps 2-4 below) against it alone; don't fetch hourly/intraday/
options data for every candidate.

### 2. Pull price history — three timeframes, both symbols

```
get_price_history(contract_id, security_type="STK", step="ONE_DAY",  period="SIX_MONTHS", outside_rth=false)
get_price_history(contract_id, security_type="STK", step="ONE_HOUR", period="ONE_MONTH",   outside_rth=false)
get_price_history(contract_id, security_type="STK", step="FIVE_MINS", period="TWO_DAYS",   outside_rth=false)
```
Fetch the same **FIVE_MINS/TWO_DAYS** call for the benchmark, plus the same
**ONE_DAY/SIX_MONTHS** call for the benchmark (needed to fit beta — don't
skip it just because the ticker's own daily bars are already in hand). Use
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
  --bench-daily spy_daily.json \
  --options options_oi.json --outdir out/
```
`--bench-daily` is the benchmark's own `ONE_DAY/SIX_MONTHS` history (fetched
in step 2) — it's what beta is fit from, separate from `--daily` (the
ticker's own daily bars, used for pivots/swing S/R).
This does no network I/O — it only reads the files above. It prints a JSON
summary to stdout and writes to `--outdir`:
- `01_daily.png`, `02_hourly.png`, `03_intraday_volume_profile.png`,
  `04_options_oi.png`, `05_relative_strength.png`, `06_trade_levels.png`,
  `07_rs_rotation.png`
- `summary.json` (the same summary, saved)
- `report.html` — a self-contained page with all seven charts embedded as
  base64 and a Hebrew-language numeric summary, for handing over as a file
  or reading directly.

### 5. Present it with the charts, not just the numbers

The user wants to *see* the levels, not just read strike numbers. Either:
- Publish `report.html` (or a redesigned version of it) as an **Artifact**
  so it renders inline — load the `artifact-design` skill first if building
  a custom page rather than using the script's own `report.html` directly,
  and embed the seven PNGs as base64 `data:` URIs (they total well under
  1.5MB, comfortably inside the 16MB artifact limit).
- Or send the PNGs / `report.html` directly as files if the session isn't
  artifact-capable.

**Before publishing, add a short "bottom line" box at the very top of the
report** — right under the title/price line, before the pivot/OI summary
grid — with Claude's own synthesized read: an immediate-entry take and a
later/follow-through-entry take (each brief, each with some directional
lean), plus the one or two things actually driving the picture (e.g. which
benchmark fits and why, a beta regime shift, an options wall sitting right
at spot). `analyze.py` itself never writes this — the script's numbers stay
neutral by design — so this box is composed by Claude each time and
inserted into the generated `report.html` before publishing (or written
directly if building a custom page). Skipping this is the single most
common complaint this skill gets: a report that is all charts and no
verdict up front reads as "too many graphs, no decision." State the same
verdict in the chat reply too, leading with it, before any supporting
numbers.

Quote the numeric summary in the reply too (pivots, POC/VAH/VAL, call
wall/put wall/max pain, beta, current alpha, the named divergence windows,
and — when the user is thinking about a position — the nearest support and
resistance zones with their sources) — the charts support the numbers, they
don't replace saying them.

**Adapt the trade-plan framing to how the user actually trades.** The
`trade_plan.scenarios` block (`if_long`/`if_short` with entry/stop/target/
rr_ratio) is written in stock-position language — a hard stop price and a
reward:risk ratio. That is the right framing for a stock/CFD trader, but it
is close to meaningless for an options trader, who manages risk through
strike/spread structure and expiry, not a stop-loss order on the
underlying. If the user has said (in this conversation, or is a known
preference) that they trade options, **do not lead with the stop/target
cards** — instead translate the same underlying level ladder into
options-relevant terms: which strikes sit on top of a confluence zone (good
candidates for a spread's short strike), how the nearest expiry's DTE
relates to the walls/max pain (pinning risk matters more the closer to
expiry — see caveats), and where the call wall / put wall bound the range
dealers are likely to defend. This is still descriptive, not a
recommendation to buy a specific contract — same neutrality rule as the
stock scenarios, just expressed in the vocabulary that's actually useful to
the reader. If it isn't clear which the user is, ask once rather than
guessing.

## Data schema reference

`analyze.py --daily/--hourly/--intraday/--bench-intraday/--bench-daily` each
expect the raw `get_price_history` JSON (a dict with `time`, `open`, `high`,
`low`, `close`, `volume` parallel arrays, ISO timestamps). `--options`
expects the `options_oi.json` schema shown above. The script never calls
IBKR itself — all fetching happens in the conversation, by design, so it
stays usable in any environment that has the JSON files, and so a fetch
failure is visible to Claude (and reported to the user) rather than silently
swallowed inside a script.

`summary.json`'s `relative_strength` block: `beta_60d`/`beta_60d_correlation`
(the long-run fit, for context), `beta_recent`/`beta_recent_window_days`
(the rolling beta, default 20 days, actually used in the alpha calc),
`beta_regime_shift` (`beta_recent - beta_60d` — flag it when `abs() > 0.3`),
`alpha_now_pp` (beta-adjusted excess return at the last bar),
`pct_session_alpha_positive`, `divergence_windows` (a list of `{class:
"against"|"held", start_time, end_time, stock_move_pp, bench_move_pp}`),
`rs_line_at_new_high` (bool), `rs_ratio_now`/`rs_momentum_now`, and
`rs_quadrant` (one of `Leading`/`Weakening`/`Lagging`/`Improving`).

`summary.json`'s `trade_plan` block: `resistance_ladder` and
`support_ladder` — each a list of zones (`{level, distance_pct, labels:
[...]}`, nearest first, up to 5 per side) — and `scenarios.if_long` /
`scenarios.if_short`, each `{entry, stop, stop_label, risk, target,
target_label, reward, rr_ratio, target_2, target_2_label, reward_2,
rr_ratio_2}`. `target_2`/`rr_ratio_2` describe the next zone out, for what
the risk/reward looks like if the first target doesn't hold the trade.

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
- **Beta fit over 60 days can have weak correlation for a single volatile
  name** (a low `beta_60d_correlation` in the summary) — say so when it's
  low. A beta fit from a weak linear relationship still produces an alpha
  number, but that alpha is picking up a lot of idiosyncratic noise, not
  just genuine relative strength; don't report the number without the
  caveat.
- **The rolling 20-day beta is noisier than the 60-day one by construction**
  — it's supposed to be, that's what lets it catch a regime shift, but it
  also means a single overlooked earnings gap or one-day short squeeze
  inside the window can swing it. Read `beta_regime_shift` as "worth a
  second look," not as settled fact on its own.
- **The RS-Ratio/RS-Momentum quadrant is an open reconstruction, not the
  licensed RRG indicator** — say this explicitly whenever quoting a
  quadrant. The general method (z-scored relative trend and its rate of
  change) is publicly documented; the exact smoothing constants
  stockcharts.com/relativerotationgraphs.com use are proprietary and this
  script does not claim to match them tick-for-tick. Treat the quadrant
  label as directionally informative, not as a precise reading.
- **Relative strength needs a benchmark that actually applies, and the
  official sector is only a guess at what that is.** SPY is a reasonable
  default; a name that diverges hard from the S&P 500 needs a real
  candidate check (see the benchmark-fit check in the Workflow), not an
  automatic swap to its GICS sector ETF — the sector can fit worse than
  SPY does. MSTR is the worked example: sector ETF (IGV) corr 0.43, SPY
  corr 0.39, both weak, while IBIT (Bitcoin) corr 0.82 — the real driver
  had nothing to do with its sector classification. Report the correlation
  number for whatever benchmark is used either way, so a weak fit is
  visible rather than implied by the choice of benchmark alone.
- **The trade-plan scenarios are arithmetic, not a recommendation.** Both
  the long and the short case are always computed and reported together;
  never present only one of them, and never phrase the output as "you
  should go long/short here" — the level map and the risk/reward numbers
  are the deliverable, the direction is the user's call. A stop placed
  exactly on a level (rather than a little beyond it) will get hit by
  ordinary noise around that level; say so if asked where exactly to place
  one.
- **This is not investment advice**, and the report should say so.
