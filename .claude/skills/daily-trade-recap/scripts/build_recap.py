#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Turn a raw IBKR trade dump into a last-trading-day recap and an all-time curve.

Shares its exit-derivation logic with weekly-trades' build_week.py (fold fills
into exit events, charge worthless expiries their full premium, drop
platform-restart artefacts) but is not week-scoped: it picks the most recent
trading day on its own, and separately turns every exit in the file into a
per-day, per-ticker P&L matrix for a cumulative "progress" chart.

Usage:
    python build_recap.py TRADES_JSON OUTDIR [--tz-offset -4]

Writes OUTDIR/day-recap.json (last trading day only) and
OUTDIR/all-time-curve.json (every exit in the file, for the chart), and
prints the day recap to stdout.
"""
import argparse
import collections
import datetime
import json
import os
import sys


# ---------------------------------------------------------- shared with weekly-trades ---
# These four functions are load-bearing and deliberately identical to the ones in
# weekly-trades/scripts/build_week.py — see that file's docstrings for why the FIFO
# matching and the price-0 handling work the way they do. Duplicated rather than
# imported because a skill's scripts directory is not guaranteed to sit next to its
# siblings once installed (see weekly-trades' own note on this).

def load_trades(path):
    with open(path, encoding="utf-8") as fh:
        blob = json.load(fh)
    trades = blob.get("trades") if isinstance(blob, dict) else blob
    if not isinstance(trades, list):
        sys.exit("could not find a trade list in {}".format(path))
    for t in trades:
        for field in ("symbol", "sec_type", "side", "size", "price", "trade_time"):
            if field not in t:
                sys.exit("trade missing '{}': {}".format(field, t))
    return trades


def session_time(iso, tz_offset):
    utc = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    return utc.replace(tzinfo=datetime.timezone.utc).astimezone(
        datetime.timezone(datetime.timedelta(hours=tz_offset)))


def session_day(dt, expiry=False):
    day = dt.date()
    if expiry:
        return day
    if dt.hour >= 18:
        day += datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day


def holding_times(all_trades, tz):
    """FIFO lot matching — see build_week.py's docstring for the full reasoning."""
    longs = collections.defaultdict(collections.deque)
    shorts = collections.defaultdict(int)
    acc = collections.defaultdict(lambda: [0.0, 0, 0.0, 0.0])
    for t in sorted(all_trades, key=lambda x: x["trade_time"]):
        sym, qty, px = t["symbol"], t["size"], t["price"]
        dt = session_time(t["trade_time"], tz)
        mult = (t.get("net_amount", 0) / (qty * px)) if (qty and px) else 100
        if t["side"] == "BUY":
            left = qty
            if t.get("realized_pnl"):
                take = min(left, shorts[sym])
                shorts[sym] -= take
                left -= take
            if left:
                longs[sym].append([left, dt, px * mult, mult])
            continue
        key, left, book = (sym, dt.strftime("%Y-%m-%d %H:%M"), px), qty, longs[sym]
        while left > 0 and book:
            lot = book[0]
            take = min(left, lot[0])
            acc[key][0] += take * (dt - lot[1]).total_seconds() / 60.0
            acc[key][1] += take
            acc[key][2] += take * lot[2]
            acc[key][3] += take * lot[3]
            lot[0] -= take
            left -= take
            if lot[0] <= 0:
                book.popleft()
        shorts[sym] += left
    return {k: {"hold": v[0] / v[1], "premium": v[2], "qty": v[1],
                "mult": round(v[3] / v[1])}
            for k, v in acc.items() if v[1]}


def build_exits(trades, tz, drop_expiry=None, expiry_day=None, drop_carry=None, carry_day=None):
    """Apply the standing filter chain and fold fills into exit rows.

    Same defaults as weekly-trades: share trades dropped, worthless-expiry rows
    kept and charged their full premium, restart artefacts dropped, only SELL
    legs kept (one row per exit).

    `drop_expiry`/`expiry_day` mirror weekly-trades' flags of the same name: a
    price-0 sell against a lot that was genuinely open looks identical whether an
    option expired worthless or the (paper) account was reset and the position
    just vanished — nothing in the feed tells the two apart, only the account
    holder does. Rows named here are dropped outright rather than charged a loss.

    `drop_carry`/`carry_day` also mirror weekly-trades: a real, nonzero-price exit
    whose cost basis traces back to a lot opened before the window being reported
    on (e.g. a position carried into a reset week from before it) is a real trade,
    but not one this window should take credit or blame for. Named symbols are
    dropped entirely on `carry_day`, the same blunt "drop every exit of SYM that
    day" weekly-trades uses — there's no reliable way to tell which specific fills
    trace to the stale lot without doing that.
    """
    holds = holding_times(trades, tz)
    rows = [t for t in trades if t["sec_type"] != "STK"]

    def closed_something(t):
        dt = session_time(t["trade_time"], tz)
        info = holds.get((t["symbol"], dt.strftime("%Y-%m-%d %H:%M"), t["price"])) or {}
        return info.get("qty", 0) > 0
    rows = [t for t in rows if t["price"] != 0 or closed_something(t)]
    if drop_expiry:
        gone, gday = set(drop_expiry), expiry_day
        rows = [t for t in rows
                if not (t["price"] == 0 and t["symbol"] in gone
                        and session_time(t["trade_time"], tz).date().isoformat() == gday)]
    if drop_carry:
        carry, cday = set(drop_carry), carry_day
        rows = [t for t in rows
                if not (t["symbol"] in carry
                        and session_time(t["trade_time"], tz).date().isoformat() == cday)]
    rows = [t for t in rows if t["side"] == "SELL"]

    merged = collections.defaultdict(
        lambda: {"sz": 0, "amt": 0.0, "pnl": 0.0, "com": 0.0, "st": None})
    for t in rows:
        dt = session_time(t["trade_time"], tz)
        m = merged[(t["symbol"], dt.date(), dt.strftime("%H:%M"), t["price"])]
        m["sz"] += t["size"]
        m["amt"] += t.get("net_amount", 0.0)
        m["pnl"] += t.get("realized_pnl", 0.0)
        m["com"] += t.get("commission", 0.0)
        m["st"] = t["sec_type"]

    exits = []
    for (sym, day, hhmm, px), m in sorted(merged.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0])):
        info = holds.get((sym, "{} {}".format(day, hhmm), px)) or {}
        hold = info.get("hold")
        if px == 0:
            if not info.get("qty"):
                continue
            m["sz"] = info["qty"]
            premium = info["premium"]
            m["pnl"] = -premium
            mult = info.get("mult") or 0
        else:
            mult = round(m["amt"] / (m["sz"] * px)) if m["sz"] and px else 0
            premium = m["amt"] - m["pnl"]
        exits.append(dict(
            date=str(day), time=hhmm, sym=sym, st=m["st"], qty=m["sz"], px=px,
            mult=mult, amt=round(m["amt"], 2), pnl=round(m["pnl"], 2),
            premium=round(premium, 2),
            entry=round(premium / (m["sz"] * mult), 4) if mult else "",
            expired=(px == 0),
            ret=round(m["pnl"] / premium, 6) if premium else "",
            hold=round(hold, 1) if hold is not None else "",
            com=round(m["com"], 2)))
    return exits


# ---------------------------------------------------------------- day recap ---

def day_summary(exits, day, all_trades, tz):
    day_exits = [e for e in exits if e["date"] == day]
    wins = [e for e in day_exits if e["pnl"] > 0]
    losses = [e for e in day_exits if e["pnl"] < 0]
    expired = [e for e in day_exits if e["expired"]]
    net = sum(e["pnl"] for e in day_exits)

    day_trades = [t for t in all_trades
                  if str(session_day(session_time(t["trade_time"], tz),
                                      t["price"] == 0)) == day]
    cash = sum((1 if t["side"] == "SELL" else -1) * t.get("net_amount", 0.0)
               - t.get("commission", 0.0) for t in day_trades if t["sec_type"] != "STK")
    realized = sum(t.get("realized_pnl", 0.0) for t in day_trades if t["sec_type"] != "STK")

    biggest_win = max(day_exits, key=lambda e: e["pnl"], default=None)
    biggest_loss = min(day_exits, key=lambda e: e["pnl"], default=None)

    return {
        "date": day,
        "exits": len(day_exits),
        "net_pnl": round(net, 2),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(day_exits), 4) if day_exits else None,
        "profit_factor": (round(sum(e["pnl"] for e in wins) / -sum(e["pnl"] for e in losses), 3)
                           if losses else None),
        "by_ticker": sorted(
            [[s, round(sum(e["pnl"] for e in day_exits if e["sym"] == s), 2)]
             for s in {e["sym"] for e in day_exits}], key=lambda r: -r[1]),
        "expiries": {
            "count": len(expired),
            "premium_lost": round(-sum(e["pnl"] for e in expired), 2),
            "tickers": sorted({e["sym"] for e in expired}),
        },
        "biggest_win": ([biggest_win["sym"], biggest_win["pnl"]] if biggest_win
                         and biggest_win["pnl"] > 0 else None),
        "biggest_loss": ([biggest_loss["sym"], biggest_loss["pnl"]] if biggest_loss
                          and biggest_loss["pnl"] < 0 else None),
        "commission": round(sum(e["com"] for e in day_exits), 2),
        "cash_check": {"cash_flow": round(cash, 2), "realized": round(realized, 2),
                        "gap": round(cash - realized, 2)},
        "trades": [{"time": e["time"], "sym": e["sym"], "qty": e["qty"], "pnl": e["pnl"],
                     "expired": e["expired"]} for e in day_exits],
    }


# ------------------------------------------------------------- all-time curve ---

def all_time_curve(exits, since=None):
    """One point per exit (trade), in chronological order, since `since` if given.

    Per-day was the first cut of this, but it hides how a session actually unfolded —
    a day's number is really N separate decisions. The client walks this list in order
    and sums the pnl of whichever tickers stay checked, contributing 0 (not skipping the
    point) for an excluded ticker's trade so the x-axis stays stable as tickers toggle.

    `since` exists because trade history and IBKR's own performance tracking do not
    always agree on when the account "started" — a reset, a funding change, a paper
    account wipe. Pass the boundary the account holder confirmed; this function does not
    guess it.
    """
    rows = sorted(exits, key=lambda e: (e["date"], e["time"]))
    if since:
        rows = [e for e in rows if e["date"] >= since]
    tickers = sorted({e["sym"] for e in rows})
    # `pnl` is IBKR's realized_pnl, already net of commission on both legs — `com` is the
    # sell leg's commission, kept alongside so the client can add it back for a
    # before-commission (gross) view. Same convention as weekly-trades: don't subtract
    # `com` again, it's already inside `pnl`.
    trades = [{"date": e["date"], "time": e["time"], "sym": e["sym"], "qty": e["qty"],
               "pnl": e["pnl"], "com": e["com"], "expired": e["expired"]} for e in rows]
    return {"trades": trades, "tickers": tickers,
            "total_pnl": round(sum(e["pnl"] for e in rows), 2),
            "total_commission": round(sum(e["com"] for e in rows), 2),
            "since": since,
            "first_date": rows[0]["date"] if rows else None,
            "last_date": rows[-1]["date"] if rows else None}


# -------------------------------------------------------------------- main ---

def main():
    p = argparse.ArgumentParser()
    p.add_argument("trades_json")
    p.add_argument("outdir")
    p.add_argument("--tz-offset", type=int, default=-4)
    p.add_argument("--since", help="YYYY-MM-DD — only include curve trades on/after this "
                                    "date (e.g. the account's last reset or funding change)")
    p.add_argument("--drop-expiry", type=lambda s: [x.strip().upper() for x in s.split(",") if x.strip()],
                    help="SYM[,SYM] — price-0 rows for these symbols on --expiry-day are a "
                         "reset/vanished position, not a real expiry, and are dropped outright")
    p.add_argument("--expiry-day", help="YYYY-MM-DD, required with --drop-expiry")
    p.add_argument("--drop-carry", type=lambda s: [x.strip().upper() for x in s.split(",") if x.strip()],
                    help="SYM[,SYM] — drop every exit of these symbols on --carry-day; use for a "
                         "real trade whose cost basis traces back to a lot opened before the "
                         "window being reported on (e.g. carried into a reset week from before it)")
    p.add_argument("--carry-day", help="YYYY-MM-DD, required with --drop-carry")
    args = p.parse_args()
    if args.drop_expiry and not args.expiry_day:
        sys.exit("--drop-expiry needs --expiry-day")
    if args.drop_carry and not args.carry_day:
        sys.exit("--drop-carry needs --carry-day")

    trades = load_trades(args.trades_json)
    exits = build_exits(trades, args.tz_offset, drop_expiry=args.drop_expiry, expiry_day=args.expiry_day,
                         drop_carry=args.drop_carry, carry_day=args.carry_day)
    if not exits:
        sys.exit("no exits found in the file — nothing to recap")

    last_day = max(e["date"] for e in exits)
    recap = day_summary(exits, last_day, trades, args.tz_offset)
    curve = all_time_curve(exits, since=args.since)

    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "day-recap.json"), "w", encoding="utf-8") as fh:
        json.dump(recap, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.outdir, "all-time-curve.json"), "w", encoding="utf-8") as fh:
        json.dump(curve, fh, ensure_ascii=False, indent=2)

    print(json.dumps({"day_recap": recap, "curve_summary": {
        "first_date": curve["first_date"], "last_date": curve["last_date"],
        "tickers": curve["tickers"], "total_pnl": curve["total_pnl"]}},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
