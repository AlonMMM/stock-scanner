# Options risk rules

Fifteen rules. The stop budget comes from the three-zone chart; position size is derived
from it; everything scales with the distance between the account and its own high-water
mark.

Hebrew edition (the original, with the chart rendered):
<https://claude.ai/code/artifact/935bd6c2-90ee-4e7d-8179-8d9951db46d2>

---

## The three zones

Every premium splits into three regions. **Zone 1 plus zone 2 is the stop budget** — how
far the premium can fall before the thesis is broken. It is an understanding of where the
risk lives, not an order resting at the broker. Zone 3 is what is left over, and the
narrower it gets, the more exposed a single position is to the surprise that erases it.

Buying out-of-the-money, delta 10–25:

| Time to expiration | Zone 1 · immediate | Zone 2 · counter-move | Zone 3 · unlikely near-term | **Stop budget** |
|---|---:|---:|---:|---:|
| One month | 15% | 35% | 50% | **50%** |
| One week | 25% | 45% | 30% | **70%** |
| 5 days | 35% | 40% | 25% | **75%** |
| 4 days | 40% | 40% | 20% | **80%** |
| 3 days | 45% | 40% | 15% | **85%** |
| 2 days | 60% | 30% | 10% | **90%** |
| 4 hours | 75% | 25% | — | **100%** |
| 1 hour | 85% | 15% | — | **100%** |
| 15 minutes | 100% | — | — | **100%** |

The closer to expiration, the more zone 1 swallows the rest. Two days out, 90% of the
premium already sits inside the stop; four hours out, all of it does.

---

## Entry — rules 1 to 4

```
maximum premium  =  risk you are willing to absorb  ÷  stop budget
```

Fewer days left means a larger stop budget, which means a smaller premium is allowed. At
2% risk on a $127,258 account:

| Time to expiration | Stop budget | Max premium |
|---|---:|---:|
| 0–2 days | 100% | $2,545 |
| 3 days | 85% | $2,994 |
| 4 days | 80% | $3,181 |
| 5 days | 75% | $3,394 |
| One week | 70% | $3,636 |
| One month | 50% | $5,090 |

### 1 — Three days or more: 2% of the account

Up to $2,545 of risk. Premium follows from the stop budget: $2,994 at three days, $3,636
at a week, $5,090 at a month.

*Zone 3 exists here, so part of the premium is not genuinely at risk in the near term.*

### 2 — Zero to two days: 1% of the account

Up to $1,273. In this range almost the whole premium is the stop, so the premium itself is
the risk.

*There is no time to recover. A move against you in the first hour is the end of the
story, not the beginning.*

### 3 — Zero to two days, A-game setup: 2% of the account, always

An A setup enters at $2,545 — not "up to", but the size. There is no discretion about how
much, only about whether it really is an A. The condition attached to the doubled size is
management: the position stays in front of you, you exit at the first sign the thesis is
not working rather than at the full budget, and it never enters an unprotected window.

*A fixed size removes the "how much" question from the moment it is hardest to answer
well. What remains is only whether the setup clears the bar — and that can be decided
before entry, not during.*

### 4 — Below $0.30: check the commission first

A full round trip costs 5%–11% of premium, and the larger part is the spread. On a $0.10
option the friction alone is 11%.

*A cheap option looks like small risk. Friction turns it into a trade that has to win big
just to break even.*

**These four percentages are the base size.** They are multiplied by the ladder factor in
rule 13 — A-game included. On the 0.5× rung an A trade enters at one percent, not two. No
category of trade sits outside the ladder; otherwise there is no ladder.

---

## Holding — rules 5 to 8

### 5 — A position that has risen is not cut for having risen

After entry the risk is locked at what was paid. An option that has gone up fivefold has
not increased it by a cent, and no rule forces a realisation.

*A rule that cuts winners and holds losers is risk management in reverse.*

### 6 — Above 5% of the account: only while you can react [hard]

A position may grow without a ceiling as long as you are at the screen or a live stop is
on it. Before the close, overnight, or over a weekend, no position exceeds **$6,363** in
market value.

*This is the only rule that forces action, and even it applies only when you lose the
ability to look after the position yourself.*

### 7 — A position in a significant move gets a stop

The stop is what converts a paper gain into a locked one. It is also what lets rule 5
stand: without it, every large gain is an open bet.

*MU exited at $8.10 after entering at $0.51. That stop did not protect against a loss; it
locked sixteen-fold.*

### 8 — No ceiling on the number of positions

Several ideas may run at once. Positions that move together, however, count as one for the
purposes of rule 6.

*Four call options on tech names on the same day are not four ideas. They are one idea in
four instruments.*

---

## Exit — rules 9 to 11

### 9 — A loss does not exceed the stop budget [hard]

A week to expiration, 70% of premium. Two days, 90%. Past that there is no thesis, only
hope.

*Twenty-one exits that gave back 50%–80% of premium cost $22,323 in a single week. The
five positions that were left to expire cost another $11,171 — the whole premium, and the
only exits where the stop budget was never consulted at all.*

### 10 — Zone 3 does not count toward the stop

What remains after zones 1 and 2 is not a cushion — it is what gets erased every few
months by a surprise. That is why it is never too wide, and why it is never counted as
security.

*The assumption that nothing will happen in the near term is right almost every time.
"Almost" is what wipes out accounts.*

### 11 — No profit target

When to exit a winner is not decided in advance. The exit follows what the underlying is
doing, protected by a stop under rule 7.

*A fixed target would have cut CRM at 100% instead of 1,461%.*

---

## The ceiling — rule 12

### 12 — Total open exposure stays under 12% of the account [hard]

The cost of all open positions together, at any moment, up to **$15,271**. This is the
ceiling on how many ideas run in parallel — not on any one of them.

*Rules 1–3 keep each position small, but seven disciplined 2% positions are still 14% of
the account. One bad day that closes all of them together is what this ceiling prevents.*

Measured by the **cost** of open positions, not their market value. A position that has
appreciated occupies only what was paid for it, so a winner never blocks a new idea. The
other side of that is covered by rule 6.

---

## Scale — rules 13 to 15

Size is not fixed. It follows **the distance between the account today and the highest
value the account has ever reached** — not a weekly return, and not a feeling.

| Distance from high | Account value | Factor | Risk per trade | In dollars | Exposure cap |
|---|---:|---:|---:|---:|---:|
| New high | $127,258 | **1.25×** | 2.50% | $3,181 | 15% |
| 0 to −5% | $120,895 | **1.00×** | 2.00% | $2,545 | 12% |
| −5% to −10% | $114,532 | **0.50×** | 1.00% | $1,273 | 6% |
| −10% to −15% | $108,169 | **0.25×** | 0.50% | $636 | 3% |
| Below −15% | $101,806 | **halt** | — | — | — |

### 13 — Size halves at every rung

A 5% fall from the high halves both the per-trade risk and the exposure cap. Another 5%
halves it again. The contraction is automatic and not subject to judgement in the moment.

*In a losing streak, deciding to shrink is exactly the decision that is hardest to make.
That is why it has to be settled in advance.*

### 14 — Expansion is slower than contraction

Down in halves, up in quarters. Above 1.0× you move only on a new account high — not on a
partial recovery, and not after one good week.

*Deliberate asymmetry. An error in the direction of shrinking costs time; an error in the
direction of expanding costs the account.*

### 15 — A day down 7% ends the day [hard]

A fall of **$8,908** or more in account value against yesterday's close: close what can be
closed, open nothing new, the day is over. The next two sessions run at 0.5× and at most
two concurrent positions, regardless of the rung on the ladder.

*A day like that is almost always a sequence of decisions rather than a single event. The
breaker does not protect the money already lost; it protects against the attempt to win it
straight back.*

The ladder costs time. After a 10% fall you need 11.1% to get back to the high, and at
half size that takes roughly twice as long. That is intentional — the recovery is meant to
be earned, not leveraged.

---

## Fixed numbers

| | |
|---|---:|
| 0–2 days, standard (rule 2) | $1,273 |
| 3+ days, and A-game (rules 1, 3) | $2,545 |
| Unprotected ceiling (rule 6) | $6,363 |
| Total open exposure (rule 12) | $15,271 |
| Day breaker (rule 15) | −$8,908 |

Recompute these if the account moves by more than 10%.

---

## What is missing before compliance can be measured

- **Expiration date at entry.** The IBKR trade feed returns neither strike nor expiry, so a
  trade cannot be assigned to its tier after the fact — which means rules 1–3 and 9 cannot
  be checked automatically.
- **The stop level, when one is placed.** The feed shows that an order executed as STOP but
  not where it was set; the field comes back empty. A stop that never triggered does not
  appear at all, so a protected position looks exposed.
- **An exit reason, in one word.** Target, stop, time, thesis changed. It constrains no
  decision and makes it possible, a month from now, to compare returns by reason.

An expiry needs none of that to be measured. IBKR reports it as a sell at price 0 with
`realized_pnl = 0`, so the loss is invisible in the broker's own numbers; the weekly
workbook charges it the cost of the lots that died and reports it separately. It is the
one breach of rule 9 that can be counted exactly.

---

## Parameters

Machine-readable form of everything above, for checking trades against the rules.

```yaml
account_value: 127258
base_risk_pct: 0.02
stop_budget:          # time to expiration -> fraction of premium inside the stop
  0: 1.00
  1: 1.00
  2: 0.90
  3: 0.85
  4: 0.80
  5: 0.75
  7: 0.70
  31: 0.50
entry_risk_pct:
  dte_0_2_standard: 0.01
  dte_0_2_agame: 0.02
  dte_3_plus: 0.02
cheap_option_threshold: 0.30
unprotected_position_cap_pct: 0.05
total_open_exposure_cap_pct: 0.12
day_breaker_pct: 0.07
day_breaker_factor: 0.5
day_breaker_sessions: 2
day_breaker_max_positions: 2
ladder:               # drawdown from high-water mark -> factor, exposure cap
  - {drawdown_to: 0.00, factor: 1.25, exposure_cap_pct: 0.15}
  - {drawdown_to: 0.05, factor: 1.00, exposure_cap_pct: 0.12}
  - {drawdown_to: 0.10, factor: 0.50, exposure_cap_pct: 0.06}
  - {drawdown_to: 0.15, factor: 0.25, exposure_cap_pct: 0.03}
  - {drawdown_to: 1.00, factor: 0.00, exposure_cap_pct: 0.00}
round_trip_friction_pct: [0.05, 0.11]
```

The framework and the chart are Alon's. The stop budget is an understanding of the risk
zone, not an order placed at the broker. Nothing here is investment advice.
