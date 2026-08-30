#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lot-level premium burn: every closing slice, where it burned, and whether a stop did it.

Longs and shorts are separate books and the feed says which one a fill touches: IBKR
stamps realized_pnl on whichever leg closed something, so a BUY with a result is a
buy-to-cover and a BUY without one opens a long. A sell with no long to match was
opened before the feed begins — its result is real but its premium is unknowable, so
it yields no slice and is reported as coverage instead.
"""
import collections, datetime, json, sys

TZ = datetime.timezone(datetime.timedelta(hours=-4))
def et(iso):
    return datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc).astimezone(TZ)

def in_session(d):
    return d.weekday() < 5 and (9, 30) <= (d.hour, d.minute) < (16, 0)

def classify(a, b, expired):
    if expired:
        return "פקיעה"
    if a.date() != b.date():
        return "אוברנייט"
    return "תוך יום" if (in_session(a) and in_session(b)) else "מחוץ לשעות"

def run(path):
    trades = json.load(open(path))["trades"]
    opts = [t for t in trades if t["sec_type"] in ("OPT", "FOP")]
    longs = collections.defaultdict(collections.deque)
    shorts = collections.defaultdict(int)
    slices, uncovered = [], collections.defaultdict(lambda: [0.0, 0])
    for t in sorted(opts, key=lambda x: x["trade_time"]):
        sym, qty, px = t["symbol"], t["size"], t["price"]
        dt = et(t["trade_time"])
        mult = (t.get("net_amount", 0) / (qty * px)) if (qty and px) else 100
        pnl = t.get("realized_pnl", 0.0)
        if t["side"] == "BUY":
            left = qty
            if pnl:
                take = min(left, shorts[sym]); shorts[sym] -= take; left -= take
                if take:
                    u = uncovered[sym]; u[0] += pnl; u[1] += 1
            if left:
                longs[sym].append([left, dt, px, mult])
            continue
        left, book, matched = qty, longs[sym], 0
        while left > 0 and book:
            lot = book[0]
            take = min(left, lot[0]); matched += take
            slices.append(dict(
                sym=sym, qty=take, entry_px=lot[2], exit_px=px, mult=lot[3],
                entry_t=lot[1].isoformat(), exit_t=dt.isoformat(),
                prem=round(take * lot[2] * lot[3], 2),
                pnl=round(take * (px - lot[2]) * lot[3], 2),
                hold=round((dt - lot[1]).total_seconds() / 60.0, 1),
                expired=(px == 0), stop=(t.get("order_type") == "STOP"),
                cls=classify(lot[1], dt, px == 0),
                day=dt.strftime("%Y-%m-%d"), time=dt.strftime("%H:%M")))
            lot[0] -= take; left -= take
            if lot[0] <= 0:
                book.popleft()
        if left:
            shorts[sym] += left
            if not matched and pnl:
                u = uncovered[sym]; u[0] += pnl; u[1] += 1
    return slices, dict(uncovered)

if __name__ == "__main__":
    sl, unc = run(sys.argv[1])
    json.dump(sl, open(sys.argv[2], "w"), ensure_ascii=False)
    burn = [x for x in sl if x["pnl"] < 0]
    print("slices {}  losing {}  burn ${:,.0f}".format(len(sl), len(burn), -sum(x["pnl"] for x in burn)))
    by = collections.defaultdict(lambda: [0, 0.0, 0.0, 0])
    for x in burn:
        r = by[x["cls"]]; r[0] += 1; r[1] += x["prem"]; r[2] -= x["pnl"]; r[3] += bool(x["stop"])
    for k, (n, p, b, st) in sorted(by.items(), key=lambda kv: -kv[1][2]):
        print("  {:12s} n={:4d}  prem ${:9,.0f}  burn ${:9,.0f}  {:3.0f}%  stops {}".format(
            k, n, p, b, 100 * b / p if p else 0, st))
    print("\nno cost basis in the feed (position opened before it begins):")
    for s, (v, n) in sorted(unc.items(), key=lambda kv: kv[1][0]):
        print("  {:6s} {:+9,.0f} on {} fills".format(s, v, n))
    print("  total {:+,.0f}".format(sum(v for v, _ in unc.values())))
