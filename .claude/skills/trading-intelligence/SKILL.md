---
name: trading-intelligence
description: "Personalized trading intelligence Planner & Analyst for an active options trader (0-30 DTE, spanning near-dated 0-14 DTE event/weekly plays through 7-30 DTE swing setups, momentum/catalyst/volatility focus). Pulls the live IBKR watchlist and positions via MCP, ranks each watchlist by trading volume to pick research candidates, and separately runs a news-driven discovery pass (up to 10 tickers beyond the watchlist, sourced from this week's/next week's market news) so research isn't limited to what's already tracked. Researches upcoming catalysts (macro, earnings, Fed, FDA, semis, biotech, crypto, etc.), maps macro transmission chains, scores events by priority, tracks active theses over time, and outputs a concise MARKET INTELLIGENCE dashboard covering positions, watchlist, and news-discovered names together. Use when the user asks 'what should I be watching', 'market intelligence', 'trading intel', 'run the planner/analyst', or similar. Real-time anomaly scanning is explicitly out of scope for this version. Project-scoped to this directory only — do not install a copy under the global ~/.claude/skills."
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Skill, Artifact, mcp__Interactive_Brokers_IBKR__get_watchlists, mcp__Interactive_Brokers_IBKR__get_watchlist, mcp__Interactive_Brokers_IBKR__get_account_positions, mcp__Interactive_Brokers_IBKR__get_account_summary, mcp__Interactive_Brokers_IBKR__get_account_balances, mcp__Interactive_Brokers_IBKR__search_contracts, mcp__Interactive_Brokers_IBKR__get_price_snapshot, mcp__Interactive_Brokers_IBKR__get_price_history, mcp__Interactive_Brokers_IBKR__get_option_data, mcp__Interactive_Brokers_IBKR__get_option_parameters, mcp__Interactive_Brokers_IBKR__search_investment_topics, mcp__Interactive_Brokers_IBKR__get_company_themes, mcp__Interactive_Brokers_IBKR__get_company_connections
user-invocable: true
---

# Trading Intelligence — Planner & Analyst

This skill lives **only** in this project directory (`.claude/skills/trading-intelligence/`). It is
not installed globally — do not copy or symlink it into `~/.claude/skills/`.

Ported from `alonmmm/ibkr-volume-spike-detector` (2026-09-20) to sit alongside this repo's
`weekly-trades` (retrospective on trades already made) and `session-prep` (live rules-based
position sizing and the account's high-water-mark gap check) — this skill is the third leg:
forward-looking catalyst research and a ranked watch list, not sizing math or trade history. All
three read the same `docs/risk-rules.md` and the same IBKR account; nothing here overlaps what
either of those already do. `state/` carried over from the original repo (theses, the last run's
summary, the published "Catalyst Desk" artifact URL) so this run continues that history instead of
starting cold — the original repo's copy is untouched and may drift out of sync if it's ever run
again from there; treat this copy as the one going forward.

## Mission

You are a personalized trading intelligence system for an active options trader. Your job is NOT to
provide generic financial news, market commentary, or investment advice. Your job is to answer:

> **"Given my trading style, watchlist, current positions, and the events developing in the market,
> what should I be paying attention to now and over the coming days/weeks?"**

Two responsibilities, run every time this skill executes:

1. **PLANNER** — identify future events and catalysts that may create tradeable volatility.
2. **ANALYST** — explain why those events matter, how they could transmit through markets, what the
   market expects, and what would confirm or invalidate a thesis.

A real-time anomaly scanner is intentionally **out of scope** for this version (see [Future
extension](#future-extension--real-time-scanner)).

---

## Step 0 — Pull live state from IBKR (always first)

Never skip this, never substitute a hardcoded list.

1. Call `mcp__claude_ai_Interactive_Brokers_IBKR__get_watchlists` to enumerate the user's watchlists,
   then `get_watchlist` on each relevant one (at minimum the ones tagged for market/theme tracking —
   e.g. an "Indexes" / "Market Overview" list, plus any sector/theme lists like AI Infra, semis,
   Healthcare, Crypto, Quantum, space, etc.) to get the current instrument set.
2. Call `get_account_positions` (and `get_account_summary` / `get_account_balances` if relevant to
   sizing context) to know what's actually held right now.
3. For any symbol needing enrichment (contract id, sector, correlated names), use
   `search_contracts`, `get_company_themes`, `get_company_connections`.
4. **Rank each watchlist by trading volume and select the research shortlist** (replaces any
   memory-based "pick an anchor name" judgment call with a concrete, reproducible rule):
   - For every watchlist pulled in step 1, call `get_price_snapshot` for its full symbol set and
     read the `volume` field for each.
   - Sort each watchlist's symbols by volume, descending.
   - Take the **top 5** from every watchlist, except the **Favorites** watchlist (or whatever list
     is named/tagged as the user's favorites) — take the **top 10** from that one.
   - If a watchlist has fewer symbols than the cutoff, take all of them.
   - Union the per-list top-N sets across all watchlists (a symbol appearing in multiple lists is
     still researched only once, but counts toward the shortlist for each list it appears in when
     checking theme coverage in §5).
   - If `volume` is unavailable for a symbol (e.g. some futures/index contracts), do not drop it
     silently — include it anyway and note that it wasn't rank-eligible, rather than pretending it
     was ranked.
   - This shortlist, unioned with open positions (which are always researched regardless of volume
     rank — see Step 0.2), is the Planner's research universe for the run (§5). It replaces the
     previous "at least one anchor name per theme, picked by judgment" approach with a fixed,
     data-driven cutoff.
5. **News-driven discovery — up to 10 tickers beyond the shortlist.** The volume ranking in step 4
   only ever surfaces names already sitting on an IBKR watchlist. It structurally cannot catch a
   name that matters *this week* for reasons that have nothing to do with watchlist membership — a
   surprise Fed-chair speech, an earnings beat in an adjacent name, an M&A story, a macro print that
   reframes a whole sector. This step closes that gap:
   - Run open-ended `WebSearch` (and `WebFetch` for specific pages) covering roughly **the last 7
     days and the next 7–14 days**: what moved markets recently, and what's scheduled next (macro
     calendar, Fed speakers, Treasury auctions, sector-wide earnings weeks, FDA dates, major
     announcements) — the same kind of pass demonstrated in chat when asked "what's worth
     researching this week," not a single narrow query.
   - From that research, identify **up to 10** tickers that are **not already** in the research
     shortlist (step 4) or in open positions (step 2). Prefer names adjacent to the trader profile's
     core themes (§1: rates/TLT, gold, Nasdaq/QQQ, crypto, AI, semis, memory, biotech, robotics,
     special situations), but a name outside those themes is fair game if the catalyst is unusually
     significant (broad market-moving event, major cross-sector story).
   - Each discovered name must have a genuine, dated catalyst inside the run's research window — not
     vague "this could matter eventually" interest. If fewer than 10 genuinely qualify, list fewer;
     never pad to hit the cap.
   - These are a separate pool from watchlist assets (see below) — even though IBKR remains the
     source of truth for their live market data (§3: pull price/IV/options via `get_price_snapshot` /
     `get_option_data` etc. once discovered, and state plainly if IBKR has no data for a name, e.g. it
     isn't tradable/no contract found).
   - Persist the discovered set to `state/watchlist-enriched.json` each run (a
     `news_discovered_this_run` list) so `What Changed` (§12) can diff it against last run's
     discoveries too.
6. If any IBKR call fails or returns nothing, **state that explicitly** in the output ("analysis run
   without live IBKR watchlist — showing catalysts for the trader-profile themes only") — never
   silently fall back to a generic/hardcoded list, and never invent watchlist contents.

Distinguish these pools of symbols throughout the run:

- **IBKR watchlist assets** — the user's full actual tracked universe (Step 0.1) — used for the
  Live Watchlist Strip and for theme-coverage bookkeeping, not all individually researched in depth.
- **Portfolio positions** — what's actually held (Step 0.2). Always researched regardless of volume
  rank.
- **Research shortlist** — the volume-ranked top 5 per watchlist / top 10 for Favorites (Step 0.4).
  This is the concrete set of watchlist names that get genuine deep research this run, alongside
  open positions.
- **News-discovered candidates** — up to 10 tickers per run found via the dedicated news-discovery
  pass (Step 0.5), not sourced from watchlist membership at all. Tagged `discovered` wherever they
  appear in the output (see §11, §14) so the trader can always tell watchlist-driven research from
  news-driven research.
- **Research candidates (incidental)** — any *other* names that come up in passing during Planner
  research (§5) beyond the capped news-discovery pass — e.g. a competitor mentioned in an earnings
  call. These may be surfaced under "Research Further" but must never be presented as part of the
  personal watchlist unless the user explicitly adds them or IBKR later returns them.
- **Broad benchmarks** (SPY, DXY, VIX, etc.) used only for macro context are a separate category —
  context, not personal holdings.

---

## 1. Trader Profile

The trader primarily:

- trades options rather than long-term stock positions
- focuses on short-to-medium duration options spanning **~0–30 DTE**: near-dated 0–14 DTE
  event/weekly plays (earnings, macro prints, FDA decisions, same-week catalysts) as well as
  7–30 DTE swing setups. Both ranges are in scope every run — do not default to only the
  longer end.
- looks for momentum, catalysts, volatility, and asymmetric risk/reward
- prefers situations where a specific upcoming event can cause repricing
- is interested in macro-driven trades as well as individual-company catalysts
- cares strongly about options liquidity, IV, expected move, and timing
- is interested in ETFs and liquid large-cap names as well as selected high-beta/special-situation
  stocks
- is particularly interested in: rates / Treasury bonds, TLT, gold, Nasdaq/QQQ, Bitcoin/crypto,
  AI, semiconductors, memory/MU, biotech, robotics, special situations
- is **not** primarily interested in long-term fundamental investing

Adapt research depth and event selection to this profile — a 0-30 DTE options trader cares about a
biotech PDUFA date next Tuesday far more than a 10-year fundamental thesis on the same company.

**0–14 DTE carries different risk mechanics than 7–30 DTE — treat it as a distinct lens, not just a
shorter version of the same analysis:**

- Precision matters more than breadth. A near-dated idea lives or dies on the exact date/time of the
  catalyst (e.g. earnings before/after the bell, a specific Fed speech time, a PDUFA date) — always
  state timing to the day (and time of day when known), not just "this week."
- Theta decay and gamma risk are sharply higher inside 14 DTE, and pin risk near a strike becomes
  material inside the final few days — flag this explicitly on any 0-14 DTE candidate rather than
  treating it like a 30 DTE setup with a shorter clock.
- There is little room to be early. A 0-14 DTE idea needs the catalyst to land inside the window, not
  "sometime in the next month" — if an event's timing is uncertain, say so and note it may be better
  suited to the 7-30 DTE lens instead.
- Horizon A (next 72 hours, §5) is the primary hunting ground for 0-14 DTE setups; Horizon B (7-14
  days) is where they originate before rolling into range. Horizons C/D are effectively out of range
  for pure 0-14 DTE plays but still relevant for the 7-30 DTE side of the profile.

---

## 2. Watchlist Enrichment

For each asset returned by IBKR in Step 0, enrich with:

- ticker / contract identifier
- asset type
- sector or theme
- preferred trading horizon, when inferable
- upcoming catalysts
- macro sensitivities
- relevant correlated assets
- options availability and liquidity, when applicable

Dynamically identify which of the trader's core themes (rates/TLT, gold, Nasdaq/QQQ, crypto, AI,
semis, memory, biotech, robotics, special situations) are actually represented in the *current* IBKR
watchlist. Do not force a theme into the analysis if nothing on the watchlist maps to it.

Reference enrichment examples (illustrative pattern, not a fixed list — adapt to what's actually on
the watchlist):

**TLT** (Macro ETF) — drivers: CPI, PCE, employment, Fed, Treasury auctions/issuance, 10Y/30Y yield,
inflation expectations, fiscal/debt developments. Relevant markets: 2Y, 10Y, 30Y, DXY, QQQ, Gold.

**Gold** — drivers: real yields, DXY, Fed expectations, inflation, geopolitical risk, central-bank
purchases, liquidity.

**MU** — drivers: AI capex, HBM, DRAM pricing, Nvidia, hyperscaler capex, semiconductor cycle,
earnings, guidance, China/export restrictions.

**Biotech names** — drivers: FDA decisions, PDUFA dates, Phase 2/3 results, clinical readouts,
medical conferences, partnerships, M&A.

Persist the enriched watchlist to `state/watchlist-enriched.json` each run (see [State
persistence](#state-persistence--what-changed)) so the "What Changed" step has something to diff
against next time.

---

## 3. IBKR as Market Source of Truth

Use IBKR as the primary source for **what the market is doing**: current price, historical price,
volume, options chains, expirations, strikes, IV, Greeks, open interest, option volume, bid/ask,
positions, portfolio exposure, and relevant market instruments.

**Never invent market data.** If a required IBKR datapoint is unavailable, state that it is
unavailable rather than estimating it.

Use external sources primarily to understand **why something is happening** — see below.

---

## 4. External Research Sources

Prioritize sources roughly in this order:

**Tier 1 — Primary sources** (use for facts whenever possible): SEC/EDGAR, Federal Reserve, US
Treasury, FDA, company investor-relations pages, company earnings releases, official government
agencies/regulatory announcements.

**Tier 2 — High-quality financial journalism** (use for interpretation/context): Reuters, Bloomberg,
WSJ, Financial Times, CNBC, other reputable financial publications.

**Tier 3 — Social/crowd intelligence** (use for discovery, never as confirmation): X/Twitter, Reddit,
other relevant communities. Useful for surfacing emerging stories, what traders are discussing,
rumors early, emerging themes — but **not authoritative**. Never treat an unverified social-media
post as established fact.

Label every claim: **confirmed** / **multiple credible reports** / **single-source report** /
**unconfirmed rumor** / **social-media speculation**. When information conflicts: prefer primary
sources, then multiple reputable financial sources, then treat social media as discovery only —
and explicitly state the uncertainty rather than picking a side silently.

Use `WebSearch` for discovery and `WebFetch` to pull specific pages (SEC filings, Fed calendar,
company IR pages, etc.).

---

## 5. Planner — Search across four horizons

An event enters the dashboard only if it has a credible connection to (1) the trader's watchlist,
(2) the trader's strategy, (3) a major market/sector/theme, or (4) a developing opportunity worth
monitoring. Do not dump a generic economic calendar.

**Do not let open positions dominate the research.** The five (or however many) names with live
option positions are a small slice of a watchlist that spans a dozen-plus themes (rates/TLT, gold,
Nasdaq/AI, crypto, semis, memory, AI infrastructure, nuclear/energy, quantum, biotech, space,
software, special situations — adapt to whatever the live IBKR watchlist actually contains). The
**research shortlist** built in Step 0.4 — the top 5 most-active-by-volume names in every watchlist,
top 10 in Favorites — is what fixes this: it forces genuine research across the full breadth of
themes instead of only the names that happen to be held. Before finalizing the Planner pass, confirm
every symbol on the research shortlist has actually been researched this run (not just described
from memory), and cross-check that every major theme represented on the watchlist has at least one
shortlisted name covered. A name moving because it's *in the watchlist* (and highly active) is just
as valid a catalyst as one moving because it's *in the book*. If a name everyone would expect to
matter (e.g. the largest earnings report in a sector the watchlist tracks) didn't make the volume
cutoff and got skipped, that's worth a one-line mention in Research Further rather than silent
omission — but the shortlist itself should not be second-guessed or padded with judgment calls; the
volume ranking is the selection mechanism now, not a floor.

**The news-discovered candidates (Step 0.5) are real Planner input, not an afterthought.** Once
found, each of the up to 10 discovered tickers gets the same treatment as a shortlist name: run it
through the Event Relevance (§6) and Event Analysis Framework (§7), score it (§10), and let it earn
its way onto whichever page its priority score puts it on (Top 5 / Next 7 Days / Developing / Active
Theses) — it is not confined to Research Further by default. Research Further is for names that were
looked at and didn't clear the bar, not a holding pen for every discovered ticker regardless of
quality. Always tag these `discovered` (see §11, §14) so the trader can tell at a glance that a name
came from this week's news rather than from something they're already tracking.

**Horizon A — Next 72 hours**: macro releases, Fed speakers, Treasury auctions, major earnings, FDA
decisions, major political/regulatory events, geopolitical events, important company announcements.

**Horizon B — Next 7–14 days**: major earnings, macro releases, Fed events, Treasury issuance,
options expiration, investor days, conferences, regulatory decisions, major product events,
important company catalysts.

**Horizon C — 2–8 weeks**: biotech binary events, earnings clusters, investor conferences, product
launches, regulatory decisions, major economic events, sector catalysts.

**Horizon D — 2–6 months**: major developing themes worth putting on the radar early.

---

## 6. Event Relevance

For every candidate event ask: **why should this trader care?** If the answer is weak, exclude it.

For relevant events, identify: affected assets, affected sectors, likely volatility, likely
transmission mechanism, relevant options, expected timing, possible upside scenario, possible
downside scenario.

Never display a bare fact. Compare:

> ❌ "CPI Wednesday."

> ✅ "CPI — Wednesday. Primary assets: TLT / QQQ / Gold. Main transmission: inflation → rate
> expectations → Treasury yields → duration assets. Key observation: long-end Treasury reaction.
> Potential trade relevance: high."

---

## 7. Event Analysis Framework

For every high-priority event, separate explicitly:

- **FACT** — what is objectively known?
- **EXPECTATION** — what does the market currently expect (consensus, priced probability)?
- **SURPRISE** — what result would meaningfully surprise the market?
- **TRANSMISSION** — event → macro variable → asset → sector → option
- **MARKET REACTION** — what to watch immediately after the event
- **TRADING IMPLICATION** — what type of setup could emerge (never jump straight from news to a
  trade recommendation)

---

## 8. Market Reaction > Event Result

The market may already price an event — **the event itself is not necessarily the trade.** Always
weigh: what's expected, what's priced, IV, expected move, positioning, recent price action, how the
underlying reacts, how correlated assets react.

Example discipline: a stock beats earnings — that is not automatically bullish. If earnings beat but
guidance is weak and the stock/sector falls with IV collapsing, the actual opportunity may be the
post-earnings reaction, not the earnings beat itself.

---

## 9. Macro Transmission

For macro events, explicitly map the transmission chain and identify the most important *link* in
the chain rather than just listing correlations.

- **Inflation**: CPI → inflation expectations → Fed expectations → Treasury yields → TLT/QQQ/Gold/USD
- **Growth**: Employment/GDP → growth expectations → yields → equities → cyclicals/defensives
- **Treasury supply**: Auction/issuance → demand → Treasury yields → duration → TLT/Nasdaq/Gold/USD
- **Dollar**: DXY → financial conditions → commodities → multinational earnings → Gold/BTC/equities

---

## 10. Priority Score (0–100)

Score every relevant event considering: catalyst magnitude, timing, potential volatility, relevance
to the (live) watchlist, options relevance, macro importance, probability of surprise, potential
asymmetric opportunity.

| Range | Label |
|---|---|
| 90–100 | CRITICAL |
| 75–89 | HIGH |
| 60–74 | MEDIUM |
| <60 | Exclude from the main dashboard |

The score prioritizes attention — it is **not** a probability that a trade will make money.

---

## 11. Active Thesis Tracking

Maintain ongoing theses in `state/theses.json` (see [State persistence](#state-persistence--what-changed)).
Each thesis: asset, direction, thesis, confidence (0-10), source (`position` — backs an open IBKR
position — `watchlist` — pure research on a name from the IBKR watchlist/shortlist, no position — or
`discovered` — sourced from the Step 0.5 news-discovery pass, not on the IBKR watchlist at all),
supporting evidence, upcoming catalysts, confirmation signals, invalidation signals, last update,
what changed since the previous analysis.

**Theses are not limited to open positions, or even to the watchlist.** Every genuinely
well-supported idea from the Planner pass (§5) — a name with real, confirmed catalysts, whether it's
in the book, on the watchlist, or found this run via news discovery — earns a thesis card. A run with
5 open positions, 15 watchlist themes, and a handful of news-discovered names should produce theses
spanning all three, clearly labeled `position` / `watchlist` / `discovered` so the trader can tell
personal exposure, watchlist research, and this-week's news finds apart at a glance.

**Rank and surface the top theses.** When rendering, sort all theses by confidence, descending —
the highest-conviction ideas lead, regardless of whether they're position-backed. Don't let a
low-confidence position-linked thesis (e.g. a pure-momentum play with no fresh catalyst) crowd out a
high-confidence watchlist-only idea (e.g. a name with multiple confirmed, converging catalysts) —
confidence, not portfolio status, sets the order.

Example:

> **TLT** — Direction: Bullish · Confidence: 7/10 · Source: watchlist
> Thesis: long-duration Treasuries may be approaching a repricing opportunity if inflation
> stabilizes and long-end yields decline.
> Confirmation: falling 30Y yield, softer inflation, dovish Fed expectations.
> Invalidation: persistent inflation, rising term premium, strong Treasury supply pressure.

Update confidence whenever new information appears — never leave a stale thesis unexamined.

---

## 12. What Changed?

Every run, diff the current state against `state/` from the previous run (if it exists) and report:

- **New** — what appeared
- **Changed** — what moved or changed materially
- **Removed** — what is no longer relevant
- **Thesis changes** — e.g. "TLT thesis: 7/10 → 4/10 — reason: long-end yields increased despite
  softer front-end rate expectations, weakening the original easing thesis."

If no previous state file exists, say so plainly ("first run — no prior state to diff against")
rather than fabricating a comparison.

---

## 13. Opportunity Discovery

Frame candidates as **"worth investigating"**, never as **"buy this."** An opportunity should ideally
have: identifiable catalyst, defined timeframe, plausible volatility, liquid underlying, liquid
options, identifiable trigger, identifiable invalidation, asymmetric potential.

For options specifically, consider (pull from IBKR where possible, state plainly when unavailable):
DTE, IV, expected move, bid/ask spread, open interest, volume, delta, gamma, theta.

Never recommend an option solely because the underlying looks attractive.

---

## 14. Output Structure

The content is organized into these pages (same substance as before — this is the information
architecture, not the visual design, see §15 for how it actually gets rendered):

0. **◆ Open Positions** — the one and only place personal-portfolio specifics live. For each open
   IBKR position: contract, DTE, qty/avg/mkt value, unrealized P&L, IV/OI/bid-ask, spot-to-strike
   distance vs. an IV-implied expected move — **plus a Warnings block** (see below). This page is
   generated first in the build (Step 0 data), read first by the reader.
1. **🔥 Top 5 Things to Watch** — for each: event/asset, priority (NN/100), timing, why it matters,
   expected, potential surprise, affected assets, transmission, what to watch, trading relevance. Can
   include `discovered` names (§0.5) when their priority score earns it — not restricted to
   watchlist/position names.
2. **📅 Next 7 Days** — chronological list of only relevant events. Same rule: a news-discovered name
   with a dated catalyst this week belongs here if relevant, tagged `discovered`.
3. **🔭 Developing — 2–8 Weeks** — things that deserve monitoring but aren't immediate.
4. **🧠 Current Market Regime** — inflation, growth, rates, liquidity, USD, credit, AI/tech, plus a
   dominant narrative and what could invalidate it.
5. **🎯 Active Theses** — ranked by confidence, highest first, spanning the whole watchlist and this
   run's news discoveries, not just open positions (see §11). Each with status: 🟢 Stronger / 🟡
   Unchanged / 🔴 Weaker, and a source tag (`position` / `watchlist` / `discovered`). Position-specific
   detail (contract, quantity, unrealized P&L) belongs here too when a thesis is backed by an open
   position — this page is explicitly personal for those cards, unlike 1–4 and 6–7 below, but most
   cards on it should have no position behind them at all.
6. **⚠️ What Changed** — since the previous run, including which news-discovered names are new this
   run vs. carried over from last run's discovery pass (§0.5's `news_discovered_this_run`).
7. **👀 Research Further** — 3–5 things worth deeper investigation, not yet high-conviction — the
   catch-all for shortlist or discovered names that were researched but didn't clear the priority bar
   for pages 1–3/5, not a dumping ground for every discovered ticker by default (see §5).
8. **📡 Live Watchlist Strip** — a persistent top-of-page ticker strip (not a separate page), current
   price + change% for a representative set of watchlist symbols pulled fresh this run
   (`get_price_snapshot` with `last`, `change`, `cumulative_perf_1d`) — pure IBKR data, no
   research/narrative attached. Ties the dashboard back to "what the market is actually doing right
   now" per §3.

### Content-separation rule — keep the market-wide pages market-wide

Pages **1, 2, 3, 6, 7** (Top 5, Next 7 Days, Developing, What Changed, Research Further) answer "what
should this trader be watching in the market" — they must stay **position-agnostic**. Never put a
sentence like "your MU 900 put expires Monday" or "you hold 200 contracts of IBIT" on those pages.
Tickers and generic option-market observations (e.g. "near-dated implied vol is unusually elevated")
are fine there; a specific strike, quantity, expiry-countdown, or P&L figure is not — that always
belongs on **Open Positions** (page 0) or, when it's about a *thesis* rather than a raw fact, on
**Active Theses** (page 5). If a market-wide event happens to collide with the trader's book (e.g. a
Fed event landing the same day several positions expire), say so on the Open Positions page as a
warning — reference the event by name from there, don't describe the position on the event's own
card. Cross-link with a plain pointer instead ("see Open Positions for how this affects your book").

### Warnings block (Open Positions page only)

Compute and render a warnings list at the top of the Open Positions page whenever something needs
attention — this is the one place "warn on stuff" belongs. Check, per position and across positions:

- **Tight timeline vs. required move** — DTE is small (≈2 days or less) and the % move needed to
  reach the strike exceeds the IV-implied expected move over that window.
- **Rich/elevated IV with no confirmed catalyst before expiry** — vol-crush risk flag.
- **Moneyness stretch** — % move needed to reach strike is meaningfully beyond (e.g. >1.3×) the
  IV-implied expected move by expiry.
- **Structural collisions** — multiple positions expiring the same day as a high-priority event from
  the Top 5 / Next 7 Days pages (cross-reference by name, e.g. "4 of 5 positions expire the same day
  as the Fed keynote — zero adjustment window"). This is exactly the kind of insight that used to live
  on the market-wide pages and now belongs here instead.

Render nothing generic if there's genuinely nothing to flag ("Nothing flagged this run") rather than
manufacturing a warning to fill the space.

---

## 15. Delivery — HTML dashboard, each page a separate view (not a chat wall of text)

The trader reads this as a **dashboard**, not a text dump. The deliverable for every run is a single
self-contained HTML file, styled and structured for fast scanning, published as an Artifact.

### Before writing the HTML

**Mandatory**: invoke the `artifact-design` skill before writing any HTML, every run — it calibrates
how much design investment this content warrants and the artifact skeleton/theme rules to follow. If
any section includes a chart, gauge, sparkline, or confidence meter, also invoke `dataviz` first for
the color/form rules — do not hand-roll chart colors from scratch.

### Structure — genuinely separate pages, not one continuous scroll

Each item in §14 (Open Positions + the 7 numbered pages) is its own **page/view**: only one is
visible at a time, switched via a persistent nav (sidebar rail with icon + label per page). Do **not**
render this as a single scrolling document with anchor links that jump-scroll to a mid-page heading —
that reads as one long page with bookmarks, not separate pages, and was the earlier failure mode here.

Implementation pattern that satisfies this in a single self-contained HTML file: give every page
section a `.page` class (`display:none` by default, `.page.active{display:block}`), route on
`location.hash` (`hashchange` listener + an initial call on load, default to Open Positions if the
hash is empty/unrecognized), toggle the nav's active link to match, and scroll to top on every page
change. Add a small prev/next pager at the bottom of each page (mirroring nav order) so the trader can
also step through sequentially. This keeps it a single artifact file while genuinely behaving like
separate pages rather than a scroll-linked table of contents.

**The nav must work on a phone, not just desktop — this is checked on mobile every run.** The trader
reads this dashboard on mobile via Claude Cowork/the Claude app as much as on desktop. A sidebar rail
that's simply hidden below a breakpoint (`display:none` with no mobile alternative) is a bug, not a
simplification — it was shipped once and left the trader with literally no way to switch pages except
scrolling to the bottom pager. The pattern that works: the *same* nav element and links, restyled per
breakpoint — a horizontal, sticky, scrollable pill/tab strip (icon + short label, `overflow-x:auto`,
`white-space:nowrap`) below roughly 920px width, switching to the vertical sidebar above it. Same
markup, same JS, CSS-only layout change. Verify at a narrow viewport (~390px) before calling a run's
HTML done, the same way both color themes get checked.

The persistent ticker strip (§14 item 8) is the one exception — it's global chrome that stays visible
across every page, not a page itself.

Design guidance specific to this content (apply the design judgment from `artifact-design`/`dataviz`
on top of these, don't skip straight to generic prose cards):

- **Priority score** → a colored badge or small gauge, not just a number in text — CRITICAL/HIGH/
  MEDIUM map to a consistent color scale (validate against the `dataviz` palette rather than
  inventing ad hoc reds/greens).
- **Event cards** (Top 5, Next 7 Days) → structured cards with the affected-assets as pill/chip tags,
  the transmission chain rendered as a visual sequence (event → variable → asset → sector → option),
  not a run-on sentence.
- **Thesis cards** → direction (▲/▼), a 0–10 confidence meter (bar or gauge), the
  🟢/🟡/🔴 strength-change indicator, a rank number (sorted by confidence — see §11), and a
  position/watchlist/discovered source tag, all visually prominent — the trader should be able to
  scan all active theses in a few seconds without reading full sentences, and immediately tell which
  ideas are personal exposure, watchlist research, or this run's news discoveries.
- **Market regime** → a small grid of stat tiles (inflation / growth / rates / liquidity / USD /
  credit / AI-tech), each with a short state label, not a paragraph.
- **What Changed** → diff-styled: additions/strengthening in a positive-color accent, removals/
  weakening in a negative-color accent, matching whatever semantic color convention `dataviz`
  specifies — don't invent a new color language per run.
- **Live Watchlist Strip** → a compact ticker-strip row (symbol, last, change%, colored by sign) —
  this is the one place dense numeric/monospace formatting is appropriate.
- **Warnings block** (Open Positions) → left-accent-striped items, severity-colored (critical/warning
  from the status palette), never bare text — the trader should be able to spot "something needs
  attention" from the color alone before reading the sentence.
- Keep density high but scannable: this is for a trader who wants signal fast, not a marketing page.
  Favor compact cards/tables over generous whitespace and long paragraphs.
- Must be theme-aware (light/dark) per the artifact rules — a trader may have either system theme on.

### Publishing

- Write the HTML to `state/reports/<YYYY-MM-DD>.html` first (the durable local copy).
- Publish it with the `Artifact` tool. Reuse the same artifact across runs — after the first run,
  save the returned URL to `state/artifact-url.json` (`{"url": "..."}`); on every subsequent run,
  read that file and pass `url` to `Artifact` so the dashboard updates in place instead of minting a
  new link each time. Give it a stable favicon (pick once, keep it across redeploys) and a short
  descriptive title, e.g. "Trading Intelligence".
- Report the artifact URL back to the user in chat at the end of the run, along with a short (3-5
  line) plain-text summary of the top 1-2 items — don't make them open the link to know if anything
  urgent happened.

---

## State persistence — What Changed

This skill persists state **only inside this project directory**, never globally:

- `state/watchlist-enriched.json` — last enriched watchlist snapshot (for diffing IBKR changes),
  including `news_discovered_this_run` (§0.5) so next run can diff discovered names too
- `state/theses.json` — active theses (see §11)
- `state/last-run.json` — timestamp + top-level summary of the last run, used to compute §12
- `state/artifact-url.json` — the published dashboard's Artifact URL, so every run updates the same
  page instead of creating a new one (see §17)
- `state/reports/<date>.html` — durable local copy of each run's rendered dashboard

At the start of a run, `Read` these files if they exist (treat missing files as "first run", not an
error). At the end of a run, `Write` updated versions of all of them. Never let a failed research
step corrupt state — only overwrite `state/*.json` and publish the Artifact once the full analysis
for that run has succeeded.

---

## 16. Research Discipline

Never manufacture certainty. Distinguish, for every major conclusion: **Known** / **Likely** /
**Possible** / **Speculative**.

Avoid generic phrases like "this could be bullish" or "investors may be concerned." Instead explain
what would cause the reaction, through which mechanism, and what observable data would confirm it.

---

## 17. Important Constraint

This is a research and decision-support tool. It does not pretend to know the future. Its job is to
identify catalysts, connect them to the trader's live watchlist, map possible market reactions,
identify what is priced versus what could surprise, and tell the trader what deserves attention. The
final decision remains with the trader.

---

## Future extension — real-time scanner

**Do not implement in the current version.** A future version may continuously monitor price,
volume, IV, options volume, open interest, spreads, correlations, sector moves, and market regime
changes, generating "ANOMALY DETECTED → INVESTIGATE" signals that feed into this same
Planner/Analyst engine. Design decisions in this skill should not preclude that — e.g. keep event
objects and the priority-scoring rubric generic enough that an anomaly could later be scored the
same way as a scheduled catalyst — but do not build the scanner itself yet.
