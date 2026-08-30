#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check a week of IBKR trades against the rules in docs/risk-rules.md.

Reads the parameters from the YAML block at the end of that file, so the rules and
the checker can never drift apart — edit the document and this follows.

Some rules cannot be checked from the trade feed at all, and saying so is part of
the output. The feed carries no strike and no expiry, so a trade cannot be assigned
to its tier; rules 1-3 and 9 all depend on that. Those are reported as unchecked
rather than silently passed, because a checker that only reports what it can see
reads as a clean bill of health.

Usage:
    python check_rules.py TRADES_JSON [--rules docs/risk-rules.md]
                          [--account 127258] [--tz-offset -4]
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys


def load_params(path):
    """Pull the yaml block out of the rules document."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"```yaml\n(.*?)```", text, re.S)
    if not m:
        sys.exit("no ```yaml parameter block found in {}".format(path))
    try:
        import yaml
    except ImportError:
        sys.exit("pyyaml is needed to read the rules block: pip install pyyaml")
    return yaml.safe_load(m.group(1))


def session_time(iso, tz):
    utc = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return utc.replace(tzinfo=datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=tz)))


def session_day(dt):
    day = dt.date()
    if dt.hour >= 18:
        day += datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day


def walk_book(trades, tz):
    """Replay the week, carrying an open book so exposure can be read at any point.

    Which side a fill touches comes from the feed, not from a running position: IBKR
    stamps realized_pnl on whichever leg closed something, so a BUY carrying a result
    is a buy-to-cover and a BUY carrying none opens a long. Inside a seven-day window
    a position opened last week looks short from its first sell onward, and reading
    its later buys as covers would erase real exposure; reading the restart artefacts'
    covers as fresh longs would invent 155 contracts of MSTR and OKLO that were never
    held, against the ceiling in rule 12.

    Returns, alongside the timeline, the premium written off by expiry: a sell at
    price 0 closing real lots, which IBKR reports as a zero result.
    """
    longs = collections.defaultdict(collections.deque)   # [qty, cost/contract]
    shorts = collections.defaultdict(int)
    last_px = {}
    timeline = []
    expiry_loss = collections.defaultdict(float)
    for t in sorted(trades, key=lambda x: x["trade_time"]):
        sym, qty, px = t["symbol"], t["size"], t["price"]
        if px:
            last_px[sym] = px
        mult = (t.get("net_amount", 0) / (qty * px)) if (qty and px) else 100
        if t["side"] == "BUY":
            left = qty
            if t.get("realized_pnl"):
                take = min(left, shorts[sym])
                shorts[sym] -= take
                left -= take
            if left:
                longs[sym].append([left, px * mult])
        else:
            left, closed, book = qty, 0.0, longs[sym]
            while left > 0 and book:
                lot = book[0]
                take = min(left, lot[0])
                closed += take * lot[1]
                lot[0] -= take
                left -= take
                if lot[0] <= 0:
                    book.popleft()
            shorts[sym] += left
            if px == 0 and closed:
                expiry_loss[session_time(t["trade_time"], tz).date()] -= closed
        dt = session_time(t["trade_time"], tz)
        open_cost = sum(l[0] * l[1] for dq in longs.values() for l in dq)
        open_qty = {s: q for s, q in
                    ((s, sum(l[0] for l in dq)) for s, dq in longs.items()) if q}
        timeline.append((dt, open_cost, open_qty, dict(last_px)))
    return timeline, dict(expiry_loss)


def check(trades, p, acct, tz):
    findings = []
    opts = [t for t in trades if t["sec_type"] in ("OPT", "FOP")]
    timeline, expiry_loss = walk_book(opts, tz)

    # ---- rule 12: total open exposure, measured at cost
    cap12 = p["total_open_exposure_cap_pct"] * acct
    peak = max(timeline, key=lambda r: r[1]) if timeline else None
    if peak:
        breached = [r for r in timeline if r[1] > cap12]
        findings.append({
            "rule": 12, "name": "total open exposure under 12%",
            "status": "FAIL" if breached else "PASS",
            "detail": "peak open cost ${:,.0f} ({:.1f}% of account), cap ${:,.0f}; "
                      "above the cap at {} of {} points in the week".format(
                          peak[1], 100 * peak[1] / acct, cap12, len(breached), len(timeline)),
            "worst": peak[0].strftime("%a %d.%m %H:%M"),
        })

    # ---- rule 6: nothing unprotected over 5% at a session boundary
    cap6 = p["unprotected_position_cap_pct"] * acct
    by_day = collections.OrderedDict()
    for dt, cost, oq, lp in timeline:
        by_day[session_day(dt)] = (oq, lp)
    overnight = []
    for day, (oq, lp) in by_day.items():
        for sym, q in oq.items():
            if sym not in lp:
                continue
            mv = q * lp[sym] * 100          # equity-option multiplier; see caveat below
            if mv > cap6:
                overnight.append((day, sym, q, mv))
    findings.append({
        "rule": 6, "name": "no unprotected position over 5% overnight",
        "status": "CHECK" if overnight else "PASS",
        "detail": ("{} position-nights valued over ${:,.0f}: ".format(len(overnight), cap6)
                   + "; ".join("{} {} x{} ~${:,.0f}".format(d, s, q, v) for d, s, q, v in overnight[:6])
                   if overnight else "nothing above the cap at a session boundary"),
        "caveat": "Market value is approximated from the last traded price of that symbol, "
                  "and the feed cannot separate strikes, so a position spanning several "
                  "strikes is marked at one price. Treat flagged nights as candidates to "
                  "review, not as confirmed breaches. A live stop also satisfies the rule "
                  "and is invisible here.",
    })

    # ---- rule 4: cheap entries carry disproportionate friction
    thresh = p["cheap_option_threshold"]
    cheap = collections.defaultdict(lambda: [0, 0.0])
    for t in opts:
        if t["side"] == "BUY" and 0 < t["price"] <= thresh:
            cheap[t["symbol"]][0] += t["size"]
            cheap[t["symbol"]][1] += t.get("net_amount", 0)
    lo, hi = p["round_trip_friction_pct"]
    total = sum(v[1] for v in cheap.values())
    findings.append({
        "rule": 4, "name": "check the commission below ${:.2f}".format(thresh),
        "status": "NOTE" if cheap else "PASS",
        "detail": ("${:,.0f} of premium entered at or below ${:.2f} across {} symbols; "
                   "round-trip friction on that is roughly ${:,.0f}-${:,.0f}".format(
                       total, thresh, len(cheap), total * lo, total * hi)
                   if cheap else "no entries below the threshold"),
    })

    # ---- rule 15: the day breaker
    lim = p["day_breaker_pct"] * acct
    daily = collections.defaultdict(float)
    for t in opts:
        daily[session_day(session_time(t["trade_time"], tz))] += t.get("realized_pnl", 0)
    # An option that expired worthless comes back as realized_pnl 0. The premium is
    # gone, so it belongs in the day that lost it — dated to the calendar day, not
    # rolled forward by session_day: IBKR stamps the write-off after 22:00.
    for d, v in expiry_loss.items():
        daily[d] += v
    bad = [(d, v) for d, v in sorted(daily.items()) if v < -lim]
    findings.append({
        "rule": 15, "name": "a day down 7% ends the day",
        "status": "FAIL" if bad else "PASS",
        "detail": ("; ".join("{} {:+,.0f}".format(d, v) for d, v in bad)
                   if bad else "no day lost more than ${:,.0f} in realised terms".format(lim)),
        "caveat": "Realised P&L plus premium written off at expiry. The rule is written "
                  "against account value, which also moves with open positions, so a day "
                  "can breach it without showing here.",
    })

    return findings


UNCHECKABLE = [
    (1, "3+ days at 2%", "needs the expiry date to know the tier and the stop budget"),
    (2, "0-2 days at 1%", "needs the expiry date"),
    (3, "0-2 days A-game at 2%", "needs the expiry date and an A-game marker in the journal"),
    (5, "a risen position is not cut for having risen", "intent, not visible in fills"),
    (7, "a position in a move gets a stop", "stop levels come back empty; an untriggered stop leaves no trace"),
    (8, "correlated positions count as one", "needs a correlation call, not in the data"),
    (9, "a loss does not exceed the stop budget", "the budget depends on the expiry date"),
    (10, "zone 3 is not counted as security", "intent"),
    (11, "no profit target", "intent"),
    (13, "size halves at every rung", "needs the account equity curve, not the trade feed"),
    (14, "expansion only on a new high", "needs the account equity curve"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trades_json")
    ap.add_argument("--rules", default="docs/risk-rules.md")
    ap.add_argument("--account", type=float)
    ap.add_argument("--tz-offset", type=int, default=-4)
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    a = ap.parse_args()

    if not os.path.exists(a.rules):
        sys.exit("rules file not found: {} (pass --rules)".format(a.rules))
    p = load_params(a.rules)
    acct = a.account or p["account_value"]

    with open(a.trades_json, encoding="utf-8") as fh:
        blob = json.load(fh)
    trades = blob.get("trades") if isinstance(blob, dict) else blob

    findings = check(trades, p, acct, a.tz_offset)

    if a.json:
        print(json.dumps({"account": acct, "findings": findings,
                          "unchecked": [{"rule": r, "name": n, "why": w} for r, n, w in UNCHECKABLE]},
                         ensure_ascii=False, indent=2))
        return

    print("Rules check — account ${:,.0f}\n".format(acct))
    order = {"FAIL": 0, "CHECK": 1, "NOTE": 2, "PASS": 3}
    for f in sorted(findings, key=lambda x: order.get(x["status"], 9)):
        print("  [{}] rule {} — {}".format(f["status"], f["rule"], f["name"]))
        print("        {}".format(f["detail"]))
        if f.get("worst"):
            print("        worst at {}".format(f["worst"]))
        if f.get("caveat"):
            print("        caveat: {}".format(f["caveat"]))
        print()
    print("  Not checkable from the trade feed:")
    for r, n, w in UNCHECKABLE:
        print("    rule {:<3d} {:<44s} {}".format(r, n, w))


if __name__ == "__main__":
    main()
