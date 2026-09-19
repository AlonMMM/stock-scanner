#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the weekly trade summary as a single self-contained HTML report.

Consumes the outputs the other three scripts already produce — it does not touch
the raw IBKR feed or re-derive anything:

    python3 build_report.py --summary summary.json --trades trades-filtered.csv \
        [--rules rules.json] [--burn burn-slices.json] \
        --out report.html [--label "Sep 14-18, 2026"] [--account 127258]

`--rules` wants check_rules.py's `--json` output. `--burn` wants burn_slices.py's
raw per-slice JSON array (its second positional argument).

What this deliberately does NOT show: the filter chain, the audit-reconciliation
table, or any "what got dropped and why" narrative. That belongs in the
data/<week>/README.md this skill also writes — the account holder reads this
report for the result, not the plumbing that produced it.

What it always shows:
  - a scatter of every individual exit (point = one trade), not just aggregates
  - a commission section that states plainly that net P&L already nets
    commission on both legs, and gives the reported (sell-leg) total, the
    average per exit, and the rate against premium deployed
  - whatever check_rules.py found, verbatim — including its caveats
"""
import argparse
import collections
import csv
import datetime
import json
import math
import sys


# ---------------------------------------------------------------- data in --

def load_summary(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_trades(path):
    with open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k in ("qty", "exit_price", "multiplier", "proceeds_usd", "net_pnl_usd",
                   "premium_paid_usd", "entry_price", "pct_of_premium",
                   "hold_minutes", "commission_usd"):
            if k in r and r[k] != "":
                r[k] = float(r[k])
    return rows


def load_json_or_none(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------- formatting --

def money(v, sign=False):
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return "{}${:,.0f}".format(s, abs(v))


def pct(v, digits=1):
    return "{:+.{}f}%".format(v * 100, digits)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def hold_label(minutes):
    """Some cost bases predate the feed window and carry no reconstructable hold time."""
    if minutes is None or minutes == "":
        return "unknown hold"
    return "{}m hold".format(int(round(minutes)))


def hold_hours_label(minutes):
    if minutes is None or minutes == "":
        return "unknown hold"
    h = minutes / 60.0
    return "{:.1f}h".format(h) if h >= 1 else "{}m".format(int(round(minutes)))


def price(v):
    """A per-contract/per-share price, not a dollar total — money() rounds to
    whole dollars, which erases everything about a $0.05-$1.30 option quote."""
    return "${:.3f}".format(v) if abs(v) < 1 else "${:.2f}".format(v)


# -------------------------------------------------------------- daily bars --

def render_daily(by_day):
    W, H = 640, 300
    padL, padR, padT, padB = 10, 10, 22, 34
    plotW, plotH = W - padL - padR, H - padT - padB
    n = len(by_day)
    gap = 14
    barW = (plotW - gap * (n - 1)) / n
    vals = [v for _, v in by_day]
    vmax = max(0, max(vals))
    vmin = min(0, min(vals))
    vrange = (vmax - vmin) or 1
    zero_y = padT + plotH * (vmax - 0) / vrange

    bars, labels, vlabels = [], [], []
    for i, (d, v) in enumerate(by_day):
        x = padL + i * (barW + gap)
        y_top = padT + plotH * (vmax - max(v, 0)) / vrange
        y_bot = padT + plotH * (vmax - min(v, 0)) / vrange
        h = max(y_bot - y_top, 1)
        cx = x + barW / 2
        color = "var(--pos)" if v >= 0 else "var(--neg)"
        bars.append('<rect class="bar" x="{:.1f}" y="{:.1f}" width="{:.1f}" '
                    'height="{:.1f}" fill="{}" rx="2"><title>{} {}</title></rect>'
                    .format(x, y_top, barW, h, color, d, money(v, sign=True)))
        lab_y = max(y_top - 6, 12) if v >= 0 else min(y_bot + 14, H - padB - 4)
        vlabels.append('<text class="val-lab" x="{:.1f}" y="{:.1f}" text-anchor="middle">{}</text>'
                       .format(cx, lab_y, money(v, sign=True)))
        try:
            wd = datetime.date.fromisoformat(d).strftime("%a")
        except ValueError:
            wd = ""
        labels.append('<text class="tick" x="{:.1f}" y="{}" text-anchor="middle">{} {}</text>'
                      .format(cx, H - 4, wd, d[5:]))

    return """
    <svg viewBox="0 0 {W} {H}" role="img" aria-label="Daily realised P&amp;L">
      <line class="grid-line" x1="{pl}" y1="{zy:.1f}" x2="{rx}" y2="{zy:.1f}"></line>
      <text class="tick" x="{rxlab}" y="{zylab:.1f}">$0</text>
      {bars}
      {vlabels}
      <line class="axis-line" x1="{pl}" y1="{ax}" x2="{rx}" y2="{ax}"></line>
      {labels}
    </svg>
    """.format(W=W, H=H, pl=padL, rx=W - padR, rxlab=W - padR + 4,
               zy=zero_y, zylab=zero_y + 3.5, ax=H - padB,
               bars="\n      ".join(bars), vlabels="\n      ".join(vlabels),
               labels="\n      ".join(labels))


# ------------------------------------------------------------- ticker bars --

def render_tickers(by_ticker, top_n=6):
    winners = [t for t in by_ticker if t[1] >= 0][:top_n]
    losers = sorted([t for t in by_ticker if t[1] < 0], key=lambda x: x[1])[:top_n]
    shown = winners + list(reversed(losers))
    if not shown:
        return "", ""

    W = 640
    padL, padR, padT, padB = 130, 70, 10, 10
    plotW = W - padL - padR
    rowH, gap = 26, 8
    n = len(shown)
    H = padT + n * rowH + (n - 1) * gap + padB

    vmax = max(0, max(v for _, v in shown))
    vmin = min(0, min(v for _, v in shown))
    scale = plotW / ((vmax - vmin) or 1)
    zero_x = padL + (0 - vmin) * scale

    rows = ['<line class="axis-line" x1="{:.1f}" y1="4" x2="{:.1f}" y2="{}" '
            'stroke="var(--rule-2)"></line>'.format(zero_x, zero_x, H - 6)]
    for i, (t, v) in enumerate(shown):
        y = padT + i * (rowH + gap)
        color = "var(--pos)" if v >= 0 else "var(--neg)"
        w = abs(v) * scale
        x = zero_x if v >= 0 else zero_x - w
        text_x = x + w + 8 if v >= 0 else x - 8
        anchor = "start" if v >= 0 else "end"
        # keep the label inside the bar (in surface color) when the bar itself
        # would otherwise force the label past the plot edge
        rows.append(
            '<rect class="bar" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{rh}" '
            'fill="{c}" rx="2"><title>{t} {v}</title></rect>'
            '<text class="row-lab" x="{lx}" y="{ly:.1f}">{t}</text>'
            '<text class="val-lab" x="{tx:.1f}" y="{ly:.1f}" text-anchor="{a}">{vs}</text>'
            .format(x=x, y=y, w=max(w, 1), rh=rowH - 2, c=color, t=esc(t),
                    v=money(v, sign=True), lx=padL, ly=y + rowH / 2 + 4,
                    tx=text_x, a=anchor, vs=money(v, sign=True)))
    svg = '<svg viewBox="0 0 {} {}" role="img" aria-label="Top movers by ticker">{}</svg>'.format(
        W, H, "\n      ".join(rows))

    table_rows = "\n".join(
        '<tr><td class="tkr">{}</td><td class="num {}">{}</td></tr>'.format(
            esc(t), "pos" if v >= 0 else "neg", money(v, sign=True))
        for t, v in by_ticker)
    return svg, table_rows


# -------------------------------------------------------- per-trade scatter

def trade_dt(t):
    return datetime.datetime.strptime("{} {}".format(t["date"], t["time_session"]),
                                       "%Y-%m-%d %H:%M")


def render_scatter(trades, starting_capital=None):
    """The week's account balance over time, filterable by ticker.

    Rendering moves to client-side JS here (see PNL_JS below) because the filter
    needs to redraw the whole curve, not just dim points: picking a subset of
    tickers recomputes the running total using only their trades — other trades
    still advance the clock (so a gap where they happened is visible as a flat
    stretch) but don't move the line. That can't be precomputed once in Python
    for every possible ticker combination, so the geometry (x_of/y_of, nice_step,
    the polyline/fill/gridlines) is duplicated in JS and driven by an embedded
    JSON array of {t, ticker, date, time, pnl} per exit, chronological.

    Returns (svg_shell, filter_chips, script, tickers) — the caller assembles them
    into the section; the JS renders into #pnlSvg on load and on every checkbox
    change, so the very first paint already shows real data (all tickers)."""
    ordered = sorted(trades, key=trade_dt)
    tickers = sorted(set(t["ticker"] for t in ordered))
    cap = starting_capital if starting_capital else 0

    records = [{"t": trade_dt(t).isoformat(), "ticker": t["ticker"], "date": t["date"],
                "time": t.get("time_session", ""), "pnl": round(t["net_pnl_usd"], 2),
                "sec": t.get("sec_type", ""), "prem": round(t.get("premium_paid_usd", 0.0), 2),
                "comm": round(t.get("commission_usd", 0.0), 2)}
               for t in ordered]
    data_json = json.dumps({"trades": records, "cap": cap, "tickers": tickers},
                           ensure_ascii=False).replace("</", "<\\/")

    chips = ['<label class="chip"><input type="checkbox" id="pnlAll" checked> All</label>']
    for tkr in tickers:
        chips.append('<label class="chip"><input type="checkbox" class="pnlTickerChk" '
                     'value="{t}" checked> {t}</label>'.format(t=esc(tkr)))

    svg_shell = '<svg id="pnlSvg" viewBox="0 0 700 340" role="img" aria-label="Account balance over the week"></svg>'

    script = """
    <script>
    (function() {{
      var DATA = {data_json};
      function fmtMoney(v, sign) {{
        var s = v < 0 ? '-' : (sign && v > 0 ? '+' : '');
        return s + '$' + Math.round(Math.abs(v)).toLocaleString('en-US');
      }}
      function esc(s) {{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
      function fmtPct(v, digits) {{
        digits = digits === undefined ? 1 : digits;
        return (v >= 0 ? '+' : '-') + Math.abs(v * 100).toFixed(digits) + '%';
      }}
      function niceStep(vmax, n) {{
        n = n || 4;
        if (vmax <= 0) return 1;
        var raw = vmax / n, magnitude = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
        var mults = [1, 2, 2.5, 5, 10];
        for (var i = 0; i < mults.length; i++) {{ if (raw <= mults[i] * magnitude) return mults[i] * magnitude; }}
        return 10 * magnitude;
      }}

      function render(selected) {{
        var W = 700, H = 340, padL = 66, padR = 16, padT = 14, padB = 36;
        var plotW = W - padL - padR, plotH = H - padT - padB;
        var trades = DATA.trades, n = trades.length, cap = DATA.cap;
        if (!n) return;
        var tmin = new Date(trades[0].t).getTime(), tmax = new Date(trades[n - 1].t).getTime();
        var trange = Math.max(1, (tmax - tmin) / 1000);
        function xOf(ms) {{ return padL + plotW * ((ms - tmin) / 1000) / trange; }}

        var cum = 0, balances = [];
        for (var i = 0; i < n; i++) {{
          if (selected.has(trades[i].ticker)) cum += trades[i].pnl;
          balances.push(cap + cum);
        }}
        var vmax = Math.max(cap, Math.max.apply(null, balances));
        var vmin = Math.min(0, Math.min.apply(null, balances));
        var vrange = (vmax - vmin) || 1;
        function yOf(v) {{ return padT + plotH * (vmax - v) / vrange; }}
        var startY = yOf(cap);

        var pts = trades.map(function(tr, i) {{ return [xOf(new Date(tr.t).getTime()), yOf(balances[i])]; }});
        var linePts = [[pts[0][0], startY]].concat(pts);
        var poly = linePts.map(function(p) {{ return p[0].toFixed(1) + ',' + p[1].toFixed(1); }}).join(' ');
        var fill = linePts[0][0].toFixed(1) + ',' + startY.toFixed(1) + ' ' + poly + ' ' +
          linePts[linePts.length - 1][0].toFixed(1) + ',' + startY.toFixed(1);

        var circles = [];
        for (i = 0; i < n; i++) {{
          var tr = trades[i];
          if (!selected.has(tr.ticker)) continue;
          var p = pts[i], color = tr.pnl >= 0 ? 'var(--pos)' : 'var(--neg)';
          circles.push('<circle class="bar" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) +
            '" r="3.2" fill="' + color + '" fill-opacity="0.9"><title>' + esc(tr.ticker) + ' ' + tr.date +
            ' ' + esc(tr.time) + ' — ' + fmtMoney(tr.pnl, true) + ' this trade, ' +
            fmtMoney(balances[i]) + ' balance</title></circle>');
        }}

        var last = n - 1, endColor = balances[last] >= cap ? 'var(--pos)' : 'var(--neg)';
        var endLabel = '<circle cx="' + pts[last][0].toFixed(1) + '" cy="' + pts[last][1].toFixed(1) +
          '" r="4.5" fill="' + endColor + '"></circle><text class="end-lab" x="' +
          (pts[last][0] - 6).toFixed(1) + '" y="' + (pts[last][1] - 8).toFixed(1) +
          '" text-anchor="end">' + fmtMoney(balances[last]) + '</text>';

        var seen = {{}}, dayLines = [], dayLabels = [];
        for (i = 0; i < n; i++) {{
          var d = trades[i];
          if (seen[d.date]) continue;
          seen[d.date] = true;
          var gx = xOf(new Date(d.t).getTime());
          dayLines.push('<line class="grid-line" x1="' + gx.toFixed(1) + '" y1="' + padT + '" x2="' +
            gx.toFixed(1) + '" y2="' + (H - padB) + '"></line>');
          var wd = new Date(d.t).toLocaleDateString('en-US', {{ weekday: 'short' }});
          dayLabels.push('<text class="tick" x="' + Math.max(gx, padL).toFixed(1) + '" y="' + (H - 6) +
            '" text-anchor="start">' + wd + ' ' + d.date.slice(5) + '</text>');
        }}

        var step = niceStep(vmax), hgrid = [];
        for (var v = 0; v <= vmax + step * 0.01; v += step) {{
          var y = yOf(v);
          hgrid.push('<line class="grid-line" x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' +
            (W - padR) + '" y2="' + y.toFixed(1) + '"></line>');
          hgrid.push('<text class="tick" x="' + (padL - 6) + '" y="' + (y + 3.5).toFixed(1) +
            '" text-anchor="end">' + fmtMoney(v) + '</text>');
        }}

        var startLine = '';
        if (cap && Math.abs(cap % step) > step * 0.02) {{
          startLine = '<line x1="' + padL + '" y1="' + startY.toFixed(1) + '" x2="' + (W - padR) +
            '" y2="' + startY.toFixed(1) + '" stroke="var(--ink-3)" stroke-width="1" stroke-dasharray="3,3">' +
            '</line><text class="tick" x="' + padL + '" y="' + (startY - 4).toFixed(1) +
            '" text-anchor="start">starting capital ' + fmtMoney(cap) + '</text>';
        }}

        document.getElementById('pnlSvg').innerHTML =
          '<defs><clipPath id="cuPos"><rect x="0" y="0" width="' + W + '" height="' + startY.toFixed(1) +
          '"></rect></clipPath><clipPath id="cuNeg"><rect x="0" y="' + startY.toFixed(1) + '" width="' + W +
          '" height="' + H + '"></rect></clipPath></defs>' + hgrid.join('') + startLine + dayLines.join('') +
          '<polygon points="' + fill + '" fill="var(--pos)" fill-opacity="0.12" clip-path="url(#cuPos)"></polygon>' +
          '<polygon points="' + fill + '" fill="var(--neg)" fill-opacity="0.12" clip-path="url(#cuNeg)"></polygon>' +
          '<polyline fill="none" stroke="var(--accent)" stroke-width="1.6" stroke-linejoin="round" ' +
          'stroke-linecap="round" points="' + poly + '"></polyline>' + circles.join('') + endLabel +
          '<line class="axis-line" x1="' + padL + '" y1="' + (H - padB) + '" x2="' + (W - padR) + '" y2="' +
          (H - padB) + '"></line>' + dayLabels.join('');

        var status = document.getElementById('pnlStatus');
        if (status) {{
          var included = trades.filter(function(tr) {{ return selected.has(tr.ticker); }}).length;
          status.textContent = selected.size >= DATA.tickers.length ?
            'Showing all tickers, ' + n + ' exits.' :
            'Showing ' + selected.size + ' of ' + DATA.tickers.length + ' tickers (' + included + ' of ' + n + ' exits).';
        }}
      }}

      function updateKpis(selected) {{
        var trades = DATA.trades.filter(function(tr) {{ return selected.has(tr.ticker); }});
        var n = trades.length;
        var net = trades.reduce(function(s, t) {{ return s + t.pnl; }}, 0);
        var wins = trades.filter(function(t) {{ return t.pnl > 0; }});
        var losses = trades.filter(function(t) {{ return t.pnl < 0; }});
        var winRate = n ? wins.length / n : 0;
        var grossWin = wins.reduce(function(s, t) {{ return s + t.pnl; }}, 0);
        var grossLoss = -losses.reduce(function(s, t) {{ return s + t.pnl; }}, 0);
        var pf = losses.length ? grossWin / grossLoss : null;
        var opt = trades.filter(function(t) {{ return t.sec !== 'FUT'; }});
        var optPrem = opt.reduce(function(s, t) {{ return s + t.prem; }}, 0);
        var optNet = opt.reduce(function(s, t) {{ return s + t.pnl; }}, 0);
        var ret = optPrem ? optNet / optPrem : null;
        var totalComm = trades.reduce(function(s, t) {{ return s + t.comm; }}, 0);
        var optComm = opt.reduce(function(s, t) {{ return s + t.comm; }}, 0);
        var commRate = optPrem ? optComm / optPrem : null;

        document.getElementById('kpiNet').textContent = fmtMoney(net, true);
        document.getElementById('kpiNet').className = 'val ' + (net >= 0 ? 'pos' : 'neg');
        document.getElementById('kpiNetSub').textContent = 'after commissions · ' + n + ' exits';
        document.getElementById('kpiWinRate').textContent = (winRate * 100).toFixed(0) + '%';
        document.getElementById('kpiWinSub').textContent = wins.length + ' wins · ' + losses.length + ' losses';
        document.getElementById('kpiPF').textContent = pf === null ? '—' : pf.toFixed(3);
        document.getElementById('kpiRet').textContent = ret === null ? '—' : fmtPct(ret);
        document.getElementById('kpiRet').className = 'val ' + (ret !== null && ret < 0 ? 'neg' : 'pos');
        document.getElementById('kpiRetSub').textContent = fmtMoney(optPrem) + ' option premium deployed';
        document.getElementById('kpiComm').textContent = fmtMoney(totalComm);
        document.getElementById('kpiCommSub').textContent = (commRate === null ? '—' : fmtPct(commRate, 2)) + ' on option premium';

        var note = document.getElementById('kpiFilterNote');
        if (note) note.style.display = (selected.size >= DATA.tickers.length) ? 'none' : 'block';
      }}

      function update() {{
        var selected = new Set();
        document.querySelectorAll('.pnlTickerChk').forEach(function(cb) {{ if (cb.checked) selected.add(cb.value); }});
        render(selected);
        updateKpis(selected);
      }}
      var allBox = document.getElementById('pnlAll');
      allBox.addEventListener('change', function(e) {{
        document.querySelectorAll('.pnlTickerChk').forEach(function(cb) {{ cb.checked = e.target.checked; }});
        update();
      }});
      document.querySelectorAll('.pnlTickerChk').forEach(function(cb) {{
        cb.addEventListener('change', function() {{
          var boxes = document.querySelectorAll('.pnlTickerChk');
          allBox.checked = Array.prototype.every.call(boxes, function(b) {{ return b.checked; }});
          update();
        }});
      }});
      update();
    }})();
    </script>
    """.format(data_json=data_json)

    return svg_shell, "\n".join(chips), script, tickers


# -------------------------------------------------------------- hold tiles --

def render_hold_buckets(by_hold):
    tiles = []
    for b in by_hold:
        cls = "pos" if b["pnl"] >= 0 else "neg"
        tiles.append("""
      <div class="bucket">
        <div class="b-lab">{bucket}</div>
        <div class="b-val {cls} mono">{pnl}</div>
        <div class="b-sub">{exits} exits &middot; {prem} premium &middot; {wins} wins &middot; {ret} on premium</div>
        <div class="b-guard">Without <b>{largest}</b> (largest): <span class="mono {cls2}">{without}</span></div>
      </div>""".format(
            bucket=esc(b["bucket"]), cls=cls, pnl=money(b["pnl"], sign=True),
            exits=b["exits"], prem=money(b["premium"]), wins=b["wins"],
            ret=pct(b["return_on_premium"]), largest=esc(b["largest_contributor"]),
            without=money(b["pnl_without_largest"], sign=True),
            cls2="pos" if b["pnl_without_largest"] >= 0 else "neg"))
    return "\n".join(tiles)


# -------------------------------------------------------------- burn rows --

def render_burn(slices):
    if not slices:
        return None
    losing = [s for s in slices if s["pnl"] < 0]
    total_burn = -sum(s["pnl"] for s in losing)
    by_cls = collections.OrderedDict()
    for s in losing:
        r = by_cls.setdefault(s["cls"], {"n": 0, "prem": 0.0, "burn": 0.0, "stops": 0})
        r["n"] += 1
        r["prem"] += s["prem"]
        r["burn"] += -s["pnl"]
        r["stops"] += bool(s.get("stop"))
    rows = []
    for cls, r in sorted(by_cls.items(), key=lambda kv: -kv[1]["burn"]):
        rate = 100 * r["burn"] / r["prem"] if r["prem"] else 0
        rows.append("""
        <div class="burnrow">
          <div class="b-name">{cls}<span>{n} slices &middot; {prem} prem</span></div>
          <div class="track"><div class="fill" style="width:{rate:.0f}%"></div></div>
          <div class="pct">{rate:.0f}% &middot; {burn}</div>
        </div>""".format(cls=esc(cls), n=r["n"], prem=money(r["prem"]),
                          rate=rate, burn=money(r["burn"])))
    return {
        "rows": "\n".join(rows),
        "n_slices": len(slices),
        "n_losing": len(losing),
        "total_burn": total_burn,
    }


# ---------------------------------------------------------- biggest losses --

CLS_LABEL = {"תוך יום": "Intraday", "אוברנייט": "Overnight",
             "מחוץ לשעות": "Off-hours", "פקיעה": "Expiry", "unknown": "Unclassified"}


def _burn_index(burn_slices):
    idx = collections.defaultdict(list)
    for s in burn_slices or []:
        idx[(s["sym"], s["day"], s["time"])].append(s)
    return idx


def _classify_opt(t, idx):
    """cls/stop/expired come from the matching burn-slice when one exists (exact
    mechanics: intraday/overnight/off-hours/expiry, whether a STOP order fired).
    Without burn data (or no match — a multi-lot exit can miss the key), fall back
    to a hold-time heuristic; stop/expired are then simply unknown, not False."""
    matches = idx.get((t["ticker"], t["date"], t["time_session"]))
    if matches:
        cls = matches[0]["cls"]
        return cls, any(m.get("stop") for m in matches), any(m.get("expired") for m in matches)
    hold = t.get("hold_minutes")
    if hold in (None, ""):
        return "unknown", None, None
    return ("אוברנייט" if hold >= 300 else "תוך יום"), None, None


def _price_arc(all_trades, ticker, sec_type):
    """The ticker's own first-entry-to-last-exit price move across the whole week,
    from every fill (not just the losses) — what a repeated directional bet was
    actually fighting, or riding."""
    rows = sorted([t for t in all_trades if t["ticker"] == ticker and t["sec_type"] == sec_type],
                  key=trade_dt)
    if not rows:
        return None
    first, last = rows[0]["entry_price"], rows[-1]["exit_price"]
    if not first:
        return None
    return first, last, 100 * (last - first) / first


def render_big_losses(all_trades, burn_slices, threshold=750):
    big = sorted([t for t in all_trades if t["net_pnl_usd"] < -threshold],
                 key=lambda t: t["net_pnl_usd"])
    if not big:
        return None
    total_loss = sum(t["net_pnl_usd"] for t in all_trades if t["net_pnl_usd"] < 0)
    total_big = sum(t["net_pnl_usd"] for t in big)
    share = (total_big / total_loss) if total_loss else 0

    sections = []

    # -- outright futures: a point-move loss, not option premium decay --
    futs = [t for t in big if t["sec_type"] == "FUT"]
    if futs:
        rows = []
        n_long = n_short = 0
        for t in futs:
            side = "long" if t["exit_price"] < t["entry_price"] else "short"
            n_long += side == "long"
            n_short += side == "short"
            rows.append(
                '<tr><td class="tkr">{t}</td><td>{d} {tm}</td><td>{side}</td>'
                '<td class="num">{en}&rarr;{ex}</td><td class="num neg">{pnl}</td>'
                '<td class="num">{hold}</td></tr>'.format(
                    t=esc(t["ticker"]), d=t["date"], tm=t["time_session"], side=side,
                    en=price(t["entry_price"]), ex=price(t["exit_price"]),
                    pnl=money(t["net_pnl_usd"], sign=True), hold=hold_hours_label(t.get("hold_minutes"))))
        arcs = []
        for tkr in sorted(set(t["ticker"] for t in futs)):
            arc = _price_arc(all_trades, tkr, "FUT")
            if arc:
                arcs.append("{} moved {} &rarr; {} ({:+.1f}%) across the week".format(
                    esc(tkr), price(arc[0]), price(arc[1]), arc[2]))
        majority = "long" if n_long >= n_short else "short"
        sections.append("""
    <div class="loss-group">
      <h3>Outright futures &mdash; {n} losses, {total}</h3>
      <p class="cap">Point losses on the futures contract itself, not option premium decay.
        {maj} of these {n} were {majdir} positions. {arcs}</p>
      <div class="tbl-wrap"><table><thead><tr><th>Ticker</th><th>Exit</th><th>Side</th>
        <th style="text-align:right">Entry&rarr;Exit</th><th style="text-align:right">Loss</th>
        <th style="text-align:right">Held</th></tr></thead><tbody>{rows}</tbody></table></div>
    </div>""".format(n=len(futs), total=money(total_big_sub(futs), sign=True),
                      maj=(n_long if majority == "long" else n_short), majdir=majority,
                      arcs=" ".join(arcs), rows="\n".join(rows)))

    # -- options: bucketed by what the closing slice actually was --
    opts = [t for t in big if t["sec_type"] in ("OPT", "FOP")]
    if opts:
        idx = _burn_index(burn_slices)
        buckets = collections.OrderedDict()
        for t in opts:
            cls, stop, expired = _classify_opt(t, idx)
            buckets.setdefault(cls, []).append((t, stop, expired))
        for cls, items in buckets.items():
            rows = []
            for t, stop, expired in items:
                stop_lab = ("stop order" if stop else ("expired" if expired else
                            ("no stop tag" if stop is False else "unclassified")))
                rows.append(
                    '<tr><td class="tkr">{t}</td><td>{d} {tm}</td>'
                    '<td class="num">{en}&rarr;{ex}</td><td class="num neg">{pnl}</td>'
                    '<td class="num">{pct}</td><td class="num">{hold}</td><td>{stopl}</td></tr>'
                    .format(t=esc(t["ticker"]), d=t["date"], tm=t["time_session"],
                            en=price(t["entry_price"]), ex=price(t["exit_price"]),
                            pnl=money(t["net_pnl_usd"], sign=True),
                            pct=pct(t["pct_of_premium"]) if t.get("pct_of_premium") not in (None, "") else "&mdash;",
                            hold=hold_hours_label(t.get("hold_minutes")), stopl=stop_lab))
            grp_total = sum(t["net_pnl_usd"] for t, _, _ in items)
            n_stopped = sum(1 for _, s, _ in items if s)
            avg_pct = (sum(t["pct_of_premium"] for t, _, _ in items
                       if t.get("pct_of_premium") not in (None, "")) / len(items)) if items else 0
            stop_note = (" {} of these fired an actual stop order.".format(n_stopped)
                        if n_stopped else "")
            sections.append("""
    <div class="loss-group">
      <h3>{label} options &mdash; {n} losses, {total}</h3>
      <p class="cap">Average {avgpct} of premium lost.{stopnote}</p>
      <div class="tbl-wrap"><table><thead><tr><th>Ticker</th><th>Exit</th>
        <th style="text-align:right">Entry&rarr;Exit</th><th style="text-align:right">Loss</th>
        <th style="text-align:right">% premium</th><th style="text-align:right">Held</th><th>Exit type</th></tr></thead>
        <tbody>{rows}</tbody></table></div>
    </div>""".format(label=CLS_LABEL.get(cls, cls), n=len(items), total=money(grp_total, sign=True),
                      avgpct=pct(avg_pct), stopnote=stop_note, rows="\n".join(rows)))

    return {
        "html": "\n".join(sections),
        "n": len(big),
        "total": total_big,
        "share": share,
        "threshold": threshold,
    }


def total_big_sub(rows):
    return sum(t["net_pnl_usd"] for t in rows)


# --------------------------------------------------------------- commission

def render_commission(trades, summary):
    """Rate is computed against option premium only (`summary["option_premium"]`,
    the same denominator the headline return-on-premium KPI uses) — an outright
    futures exit's premium_paid_usd is its full notional, not premium at risk, and
    folding that in makes the rate read as a rounding error instead of ~1%."""
    total_comm = sum(t.get("commission_usd", 0.0) for t in trades)
    opt_trades = [t for t in trades if t.get("sec_type") in ("OPT", "FOP")]
    opt_comm = sum(t.get("commission_usd", 0.0) for t in opt_trades)
    n = len(trades) or 1
    option_premium = summary.get("option_premium") or 0
    rate = (opt_comm / option_premium) if option_premium else 0

    by_ticker = collections.OrderedDict()
    for t in trades:
        r = by_ticker.setdefault(t["ticker"], {"n": 0, "comm": 0.0})
        r["n"] += 1
        r["comm"] += t.get("commission_usd", 0.0)
    rows = sorted(by_ticker.items(), key=lambda kv: -kv[1]["comm"])

    def _row(tkr, r):
        return ('<tr><td class="tkr">{t}</td><td class="num">{n}</td><td class="num">{comm}</td>'
               '<td class="num">{avg}</td><td class="num">{share}</td></tr>').format(
            t=esc(tkr), n=r["n"], comm=money(r["comm"]), avg=money(r["comm"] / r["n"]),
            share="{:.0f}%".format(100 * r["comm"] / total_comm) if total_comm else "&mdash;")

    TOP_N = 8
    top_rows = "\n".join(_row(t, r) for t, r in rows[:TOP_N])
    rest_rows = "\n".join(_row(t, r) for t, r in rows[TOP_N:])

    return {
        "total": total_comm,
        "avg": total_comm / n,
        "rate": rate,
        "n": n,
        "n_opt": len(opt_trades),
        "opt_comm": opt_comm,
        "top_rows": top_rows,
        "rest_rows": rest_rows,
        "n_rest": len(rows) - TOP_N,
        "n_tickers": len(by_ticker),
        "top_ticker": rows[0][0] if rows else "",
        "top_ticker_comm": rows[0][1]["comm"] if rows else 0,
    }


# ----------------------------------------------------------------- rules --

STATUS_CLASS = {"FAIL": "fail", "CHECK": "check", "NOTE": "note", "PASS": "pass"}


def render_rules(rules_json):
    if not rules_json:
        return None
    order = {"FAIL": 0, "CHECK": 1, "NOTE": 2, "PASS": 3}
    findings = sorted(rules_json["findings"], key=lambda f: order.get(f["status"], 9))
    rows = []
    for f in findings:
        cls = STATUS_CLASS.get(f["status"], "note")
        extra = ""
        if f.get("worst"):
            extra += "<div>worst at {}</div>".format(esc(f["worst"]))
        if f.get("caveat"):
            extra += '<div class="r-c">Caveat: {}</div>'.format(esc(f["caveat"]))
        rows.append("""
      <div class="rule-row {cls}">
        <span class="pill">{status}</span>
        <div class="rule-body">
          <div class="r-t">Rule {rule} &middot; {name}</div>
          <div>{detail}</div>
          {extra}
        </div>
      </div>""".format(cls=cls, status=f["status"], rule=f["rule"], name=esc(f["name"]),
                        detail=esc(f["detail"]), extra=extra))
    unchecked = "\n".join(
        '<li><strong>Rule {}</strong> &mdash; {}: {}.</li>'.format(u["rule"], esc(u["name"]), esc(u["why"]))
        for u in rules_json.get("unchecked", []))
    return {"rows": "\n".join(rows), "unchecked": unchecked,
            "n_checked": len(findings), "n_unchecked": len(rules_json.get("unchecked", []))}


# ------------------------------------------------------------------- page --

TEMPLATE = r"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>
  :root {{
    color-scheme: light;
    --bg:        #f5f6f8; --surface: #ffffff; --surface-2: #eef0f4;
    --ink:       #12151b; --ink-2: #4b5563; --ink-3: #7c8698;
    --rule:      #e2e5eb; --rule-2: #c9cedb;
    --pos:       #059669; --neg: #dc2626;
    --accent:    #b8790a; --accent-ink: #7a5006;
    --warnbg:    #fdf3df; --warnrule: #e8c583; --warnink: #6b4a08;
    --failbg:    #fdecec; --failrule: #f3b9b9; --failink: #8a1f1f;
    --passbg:    #e9f7f0; --passrule: #a9dfc4; --passink: #0f5132;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --bg:        #0a0c10; --surface: #12151b; --surface-2: #1a1e26;
      --ink:       #eef1f5; --ink-2: #a6afc0; --ink-3: #707a8c;
      --rule:      #232833; --rule-2: #333b4a;
      --pos:       #34d399; --neg: #f87171;
      --accent:    #f0b342; --accent-ink: #f0b342;
      --warnbg:    #241b0e; --warnrule: #5c431a; --warnink: #f0c674;
      --failbg:    #2a1616; --failrule: #6b2a2a; --failink: #f5a3a3;
      --passbg:    #10261c; --passrule: #2c5941; --passink: #7fd6ab;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --bg:        #0a0c10; --surface: #12151b; --surface-2: #1a1e26;
    --ink:       #eef1f5; --ink-2: #a6afc0; --ink-3: #707a8c;
    --rule:      #232833; --rule-2: #333b4a;
    --pos:       #34d399; --neg: #f87171;
    --accent:    #f0b342; --accent-ink: #f0b342;
    --warnbg:    #241b0e; --warnrule: #5c431a; --warnink: #f0c674;
    --failbg:    #2a1616; --failrule: #6b2a2a; --failink: #f5a3a3;
    --passbg:    #10261c; --passrule: #2c5941; --passink: #7fd6ab;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); }}
  .page {{ background: var(--bg); color: var(--ink); font-family: "Public Sans", system-ui, sans-serif;
    font-size: 16px; line-height: 1.6; max-width: 1040px; margin: 0 auto; padding: 32px 20px 80px;
    display: flex; flex-direction: column; gap: 40px; }}
  .mono {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
  .masthead {{ display: flex; flex-direction: column; gap: 12px; border-bottom: 2px solid var(--ink); padding-bottom: 22px; }}
  .masthead .kicker {{ font-family: "IBM Plex Mono", monospace; font-size: 0.74rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--accent-ink); font-weight: 600; }}
  .masthead h1 {{ font-family: "Fraunces", Georgia, serif; font-size: clamp(2rem, 5.2vw, 2.9rem);
    line-height: 1.08; margin: 0; font-weight: 600; text-wrap: balance; }}
  .masthead .dek {{ color: var(--ink-2); font-size: 1.02rem; max-width: 66ch; }}
  .stamp {{ display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 0.82rem; color: var(--ink-3); }}
  .stamp b {{ color: var(--ink-2); font-weight: 600; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1px;
    background: var(--rule); border: 1px solid var(--rule); border-radius: 4px; overflow: hidden; }}
  .kpi {{ background: var(--surface); padding: 18px 20px 16px; display: flex; flex-direction: column; gap: 4px; }}
  .kpi .lab {{ font-size: 0.76rem; color: var(--ink-3); font-weight: 600; }}
  .kpi .val {{ font-family: "IBM Plex Mono", monospace; font-size: 1.9rem; font-weight: 600; line-height: 1.1; letter-spacing: -0.02em; }}
  .kpi .sub {{ font-size: 0.82rem; color: var(--ink-2); }}
  .pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }}
  section {{ display: flex; flex-direction: column; gap: 16px; }}
  .sec-head {{ display: flex; align-items: baseline; gap: 12px; border-bottom: 1px solid var(--rule-2); padding-bottom: 9px; }}
  .sec-head h2 {{ font-family: "Fraunces", Georgia, serif; font-weight: 600; font-size: 1.4rem; margin: 0; }}
  .sec-head .tag {{ font-family: "IBM Plex Mono", monospace; font-size: 0.72rem; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--ink-3); font-weight: 600; margin-inline-start: auto; white-space: nowrap; }}
  section > p {{ margin: 0; max-width: 70ch; color: var(--ink-2); }}
  section > p strong {{ color: var(--ink); font-weight: 700; }}
  .figure {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 18px 18px 14px;
    display: flex; flex-direction: column; gap: 10px; }}
  .figure .cap {{ font-size: 0.85rem; color: var(--ink-2); }}
  .figure .cap b {{ color: var(--ink); font-weight: 700; }}
  .chart-scroll {{ overflow-x: auto; }}
  .chart-scroll svg {{ display: block; min-width: 480px; width: 100%; height: auto; }}
  .grid-line {{ stroke: var(--rule); stroke-width: 1; }}
  .axis-line {{ stroke: var(--rule-2); stroke-width: 1; }}
  .tick {{ font-family: "IBM Plex Mono", monospace; font-size: 10px; fill: var(--ink-3); }}
  .val-lab {{ font-family: "IBM Plex Mono", monospace; font-size: 10.5px; fill: var(--ink); font-weight: 600; }}
  .end-lab {{ font-family: "IBM Plex Mono", monospace; font-size: 11.5px; fill: var(--ink); font-weight: 700; }}
  .row-lab {{ font-family: "IBM Plex Mono", monospace; font-size: 12px; font-weight: 600; fill: var(--ink); }}
  .bar {{ transition: opacity .12s ease; }} .bar:hover {{ opacity: .72; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 0.83rem; color: var(--ink-2); }}
  .legend span {{ display: inline-flex; align-items: center; gap: 7px; }}
  .swatch {{ width: 13px; height: 3px; border-radius: 2px; display: inline-block; }}
  .dotswatch {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}
  .tickerfilter {{ display: flex; flex-wrap: wrap; gap: 6px 8px; }}
  .chip {{ display: inline-flex; align-items: center; gap: 5px; font-family: "IBM Plex Mono", monospace;
    font-size: 0.78rem; font-weight: 600; color: var(--ink-2); background: var(--surface); border: 1px solid var(--rule);
    border-radius: 20px; padding: 3px 10px 3px 8px; cursor: pointer; user-select: none; }}
  .chip:has(input:checked) {{ color: var(--ink); border-color: var(--rule-2); background: var(--surface-2); }}
  .chip input {{ accent-color: var(--accent); margin: 0; cursor: pointer; }}
  #pnlStatus {{ color: var(--ink); font-weight: 600; }}
  .tbl-wrap {{ overflow-x: auto; border: 1px solid var(--rule); border-radius: 4px; background: var(--surface); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.87rem; }}
  th, td {{ padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--rule); }}
  thead th {{ background: var(--surface-2); font-size: 0.72rem; letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--ink-3); font-weight: 700; white-space: nowrap; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  td.num {{ font-family: "IBM Plex Mono", monospace; text-align: right; white-space: nowrap; }}
  td.tkr {{ font-family: "IBM Plex Mono", monospace; font-weight: 700; }}
  details.tabledisc summary {{ cursor: pointer; font-size: 0.85rem; color: var(--ink-2); padding: 4px 0; font-weight: 600; }}
  details.tabledisc[open] summary {{ margin-bottom: 10px; }}
  .buckets {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }}
  .bucket {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 15px 16px;
    display: flex; flex-direction: column; gap: 5px; }}
  .bucket .b-lab {{ font-size: 0.78rem; color: var(--ink-3); font-weight: 600; }}
  .bucket .b-val {{ font-family: "IBM Plex Mono", monospace; font-size: 1.35rem; font-weight: 600; }}
  .bucket .b-sub {{ font-size: 0.79rem; color: var(--ink-2); }}
  .bucket .b-guard {{ font-size: 0.76rem; color: var(--ink-3); border-top: 1px dashed var(--rule-2); padding-top: 7px; margin-top: 2px; }}
  .bucket .b-guard b {{ color: var(--ink-2); }}
  .burnrows {{ display: flex; flex-direction: column; gap: 14px; }}
  .burnrow {{ display: grid; grid-template-columns: 96px 1fr 96px; align-items: center; gap: 14px; }}
  .burnrow .b-name {{ font-size: 0.86rem; font-weight: 600; color: var(--ink); }}
  .burnrow .b-name span {{ display: block; font-size: 0.74rem; color: var(--ink-3); font-weight: 400; }}
  .burnrow .track {{ position: relative; height: 20px; background: var(--surface-2); border-radius: 3px; overflow: hidden; }}
  .burnrow .fill {{ position: absolute; inset-block: 0; left: 0; background: var(--neg); opacity: 0.8; border-radius: 3px 0 0 3px; }}
  .burnrow .pct {{ font-family: "IBM Plex Mono", monospace; font-size: 0.86rem; font-weight: 700; text-align: right; }}
  .loss-group {{ display: flex; flex-direction: column; gap: 8px; }}
  .loss-group h3 {{ font-family: "Fraunces", Georgia, serif; font-weight: 600; font-size: 1.05rem; margin: 0; }}
  .loss-group .cap {{ font-size: 0.85rem; color: var(--ink-2); margin: 0; max-width: 74ch; }}
  .rules {{ display: flex; flex-direction: column; gap: 10px; }}
  .rule-row {{ display: flex; gap: 12px; align-items: flex-start; background: var(--surface); border: 1px solid var(--rule);
    border-radius: 4px; padding: 12px 16px; }}
  .rule-row.fail {{ background: var(--failbg); border-color: var(--failrule); }}
  .rule-row.check {{ background: var(--warnbg); border-color: var(--warnrule); }}
  .rule-row.pass {{ background: var(--passbg); border-color: var(--passrule); }}
  .rule-row.note {{ background: var(--surface-2); }}
  .pill {{ font-family: "IBM Plex Mono", monospace; font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
    padding: 3px 8px; border-radius: 20px; flex: 0 0 auto; white-space: nowrap; margin-top: 2px; }}
  .rule-row.fail .pill {{ background: var(--failrule); color: var(--failink); }}
  .rule-row.check .pill {{ background: var(--warnrule); color: var(--warnink); }}
  .rule-row.pass .pill {{ background: var(--passrule); color: var(--passink); }}
  .rule-row.note .pill {{ background: var(--rule-2); color: var(--ink-2); }}
  .rule-body {{ display: flex; flex-direction: column; gap: 3px; font-size: 0.88rem; }}
  .rule-row.fail .rule-body {{ color: var(--failink); }}
  .rule-row.check .rule-body {{ color: var(--warnink); }}
  .rule-row.pass .rule-body {{ color: var(--passink); }}
  .rule-row.note .rule-body {{ color: var(--ink-2); }}
  .rule-body .r-t {{ font-weight: 700; }}
  .rule-body .r-c {{ font-size: 0.82rem; opacity: 0.85; }}
  ul.notes {{ margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }}
  ul.notes li {{ padding-inline-start: 14px; border-inline-start: 2px solid var(--rule-2); color: var(--ink-2);
    max-width: 72ch; font-size: 0.88rem; }}
  footer.foot {{ border-top: 1px solid var(--rule); padding-top: 18px; font-size: 0.82rem; color: var(--ink-3);
    display: flex; flex-direction: column; gap: 8px; max-width: 74ch; }}
  footer.foot code {{ font-family: "IBM Plex Mono", monospace; background: var(--surface-2); padding: 1px 5px; border-radius: 3px; font-size: 0.8em; }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>

<div class="page">
  <header class="masthead">
    <div class="kicker">Weekly Options Ledger</div>
    <h1>{h1}</h1>
    <p class="dek">{dek}</p>
    <div class="stamp">
      <span>Trading week <b>{label}</b></span>
      <span>Source <b>Interactive Brokers</b></span>
      <span><b>{n_exits}</b> exits &middot; <b>{n_tickers}</b> tickers</span>
    </div>
  </header>

  <div class="kpis" id="topKpis">
    <div class="kpi"><div class="lab">Net P&amp;L</div><div class="val {net_cls}" id="kpiNet">{net}</div><div class="sub" id="kpiNetSub">after commissions &middot; {n_exits} exits</div></div>
    <div class="kpi"><div class="lab">Win rate</div><div class="val" id="kpiWinRate">{win_rate}</div><div class="sub" id="kpiWinSub">{wins} wins &middot; {losses} losses</div></div>
    <div class="kpi"><div class="lab">Profit factor</div><div class="val" id="kpiPF">{pf}</div><div class="sub">gross win &divide; gross loss</div></div>
    <div class="kpi"><div class="lab">Return on premium</div><div class="val {ret_cls}" id="kpiRet">{ret}</div><div class="sub" id="kpiRetSub">{prem} option premium deployed</div></div>
    <div class="kpi"><div class="lab">Commission</div><div class="val" id="kpiComm">{comm_total}</div><div class="sub" id="kpiCommSub">{comm_rate} on option premium</div></div>
  </div>
  <p class="cap" id="kpiFilterNote" style="display:none;max-width:70ch;margin:-24px 0 0">
    KPIs above reflect the ticker filter in "Account balance over time" below.</p>

  <section>
    <div class="sec-head"><h2>Account balance over time</h2><span class="tag">{n_exits} exits</span></div>
    <p>Starting capital plus the running total, plotted on real time — not evenly spaced within a day, so
      a burst of trades minutes apart moves the line in a cluster and a quiet stretch is flat. Scaled
      against the full account (from $0), not auto-fit tight to the week's swing, so the drawdown reads
      at its real size. Every exit is still its own point on the line, colored by whether that individual
      trade won or lost.</p>
    <div class="tickerfilter">{pnl_chips}</div>
    <div class="figure">
      <div class="chart-scroll">{scatter_svg}</div>
      <div class="legend">
        <span><i class="dotswatch" style="background:var(--pos)"></i> Winning trade</span>
        <span><i class="dotswatch" style="background:var(--neg)"></i> Losing trade</span>
        <span>Line &middot; account balance</span>
        <span>X-axis &middot; actual time</span>
      </div>
      <div class="cap"><b>Account balance, starting capital {starting_capital}.</b>
        <span id="pnlStatus">Showing all tickers, {n_exits} exits.</span>
        Untick a ticker to see the balance path with only the rest; hover a point for that trade's
        own result and the balance right after it.</div>
    </div>
    {pnl_script}
  </section>

  <section>
    <div class="sec-head"><h2>By day</h2><span class="tag">{n_days} sessions</span></div>
    <div class="figure">
      <div class="chart-scroll">{daily_svg}</div>
      <div class="cap"><b>Realised P&amp;L per session.</b> Already net of commissions on both legs.</div>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>By ticker</h2><span class="tag">{n_tickers} names traded</span></div>
    <p>Top winners and losers, ranked by size.</p>
    <div class="figure">
      <div class="chart-scroll">{ticker_svg}</div>
      <div class="legend"><span><i class="swatch" style="background:var(--pos)"></i> Winners</span><span><i class="swatch" style="background:var(--neg)"></i> Losers</span></div>
      <div class="cap"><b>Top movers.</b> Full breakdown below.</div>
    </div>
    <details class="tabledisc">
      <summary>Show all {n_tickers} tickers</summary>
      <div class="tbl-wrap"><table><thead><tr><th>Ticker</th><th style="text-align:right">Net P&amp;L</th></tr></thead>
      <tbody>{ticker_table}</tbody></table></div>
    </details>
  </section>

  <section>
    <div class="sec-head"><h2>By hold time</h2><span class="tag">the cut IBKR can't give you</span></div>
    <p>Every bucket shown with its largest name pulled back out &mdash; one outsized position routinely flips a bucket's apparent edge.</p>
    <div class="buckets">{hold_tiles}</div>
  </section>

  {burn_section}

  {big_losses_section}

  <section>
    <div class="sec-head"><h2>Commissions</h2><span class="tag">{n_exits} exits</span></div>
    <p><strong>Net P&amp;L above already has commission subtracted</strong> &mdash; IBKR nets the commission on both the
      opening and closing leg directly into <code class="mono">realized_pnl</code> before this report ever sees it. The
      figures below are the reported sell-leg commission only, shown so the cost of trading this book is visible on
      its own, not because anything still needs to be deducted.</p>
    <div class="kpis">
      <div class="kpi"><div class="lab">Commission (sell leg, reported)</div><div class="val">{comm_total}</div><div class="sub">across {comm_n} exits, options and futures</div></div>
      <div class="kpi"><div class="lab">Average per exit</div><div class="val">{comm_avg}</div></div>
      <div class="kpi"><div class="lab">Rate on option premium</div><div class="val">{comm_rate}</div><div class="sub">{opt_comm} option commission &divide; {opt_prem} option premium</div></div>
    </div>
    {cheap_note}
    <p class="cap" style="max-width:70ch"><b>{top_ticker}</b> was the single largest source of commission this week
      at {top_ticker_comm}, out of {comm_n_tickers} tickers traded.</p>
    <div class="tbl-wrap">
      <table><thead><tr><th>Ticker</th><th style="text-align:right">Exits</th>
        <th style="text-align:right">Commission</th><th style="text-align:right">Avg/exit</th>
        <th style="text-align:right">% of total</th></tr></thead>
      <tbody>{comm_top_rows}</tbody></table>
    </div>
    {comm_rest_block}
  </section>

  <section>
    <div class="sec-head"><h2>Risk rules check</h2><span class="tag">account {account}</span></div>
    <p>Checked against <code class="mono">docs/risk-rules.md</code>. {n_checked} of {n_rules} rules are checkable from the trade feed.</p>
    <div class="rules">{rules_rows}</div>
    <details class="tabledisc">
      <summary>{n_unchecked} rules not checkable from the trade feed</summary>
      <ul class="notes">{rules_unchecked}</ul>
    </details>
  </section>

  <footer class="foot">
    <p>Full detail and the raw exit list live alongside this report in the same week's data folder.</p>
  </footer>
</div>
"""

NO_RULES = """
  <section>
    <div class="sec-head"><h2>Risk rules check</h2></div>
    <p>No rules file was supplied for this run — pass <code class="mono">--rules rules.json</code> (from
       <code class="mono">check_rules.py --json</code>) to include it.</p>
  </section>
"""


def build(args):
    summary = load_summary(args.summary)
    trades = load_trades(args.trades)
    rules_json = load_json_or_none(args.rules)
    burn_slices = load_json_or_none(args.burn)

    daily_svg = render_daily(summary["by_day"])
    ticker_svg, ticker_table = render_tickers(summary["by_ticker"])
    pnl_svg, pnl_chips, pnl_script, pnl_tickers = render_scatter(
        trades, starting_capital=args.starting_capital)
    hold_tiles = render_hold_buckets(summary.get("by_hold", []))
    comm = render_commission(trades, summary)
    comm_rest_block = ""
    if comm["n_rest"] > 0:
        comm_rest_block = """
    <details class="tabledisc">
      <summary>Show all {n} tickers</summary>
      <div class="tbl-wrap">
        <table><thead><tr><th>Ticker</th><th style="text-align:right">Exits</th>
          <th style="text-align:right">Commission</th><th style="text-align:right">Avg/exit</th>
          <th style="text-align:right">% of total</th></tr></thead>
        <tbody>{rows}</tbody></table>
      </div>
    </details>""".format(n=comm["n_tickers"], rows=comm["top_rows"] + "\n" + comm["rest_rows"])
    rules = render_rules(rules_json)

    net = summary["net_pnl"]
    ret = summary["return_on_option_premium"]

    burn = render_burn(burn_slices) if burn_slices else None
    if burn:
        burn_section = """
  <section>
    <div class="sec-head"><h2>Where the premium burned</h2><span class="tag">{n_slices} closing slices</span></div>
    <p>Every closing slice classified by whether it was a decision or the risk already bought: intraday, overnight,
      off-hours. {money} burned across {n_losing} losing slices.</p>
    <div class="figure"><div class="burnrows">{rows}</div></div>
  </section>""".format(n_slices=burn["n_slices"], n_losing=burn["n_losing"],
                        money=money(burn["total_burn"]), rows=burn["rows"])
    else:
        burn_section = ""

    big = render_big_losses(trades, burn_slices, threshold=args.loss_threshold)
    if big:
        big_losses_section = """
  <section>
    <div class="sec-head"><h2>Biggest losses explained</h2><span class="tag">over {thresh}</span></div>
    <p>{n} exits lost more than {thresh} each, {total} total &mdash; {share} of the week's gross loss.
      Grouped by what actually happened to the position, not just by size.</p>
    <div style="display:flex;flex-direction:column;gap:24px">{rows}</div>
  </section>""".format(thresh=money(big["threshold"]), n=big["n"], total=money(big["total"], sign=True),
                        share="{:.0f}%".format(abs(big["share"]) * 100), rows=big["html"])
    else:
        big_losses_section = ""

    cheap_note = ""
    if rules_json:
        r4 = next((f for f in rules_json["findings"] if f["rule"] == 4), None)
        if r4 and r4["status"] == "NOTE":
            cheap_note = '<p class="cap" style="max-width:70ch">{}</p>'.format(esc(r4["detail"]))

    label = args.label or summary.get("week_start", "")
    n_days = len(summary["by_day"])

    html = TEMPLATE.format(
        title=args.title,
        h1="{} week, net {}".format(label, money(net, sign=True)),
        dek="{} filtered exits across {} tickers, {} win rate, {} return on premium deployed.".format(
            len(trades), len(summary["by_ticker"]), pct_int(summary["win_rate"]), pct(ret)),
        label=esc(label),
        n_exits=summary["exits"], n_tickers=len(summary["by_ticker"]),
        net=money(net, sign=True), net_cls="pos" if net >= 0 else "neg",
        win_rate=pct_int(summary["win_rate"]), wins=summary["wins"], losses=summary["losses"],
        pf=summary["profit_factor"],
        ret=pct(ret), ret_cls="pos" if ret >= 0 else "neg", prem=money(summary["option_premium"]),
        scatter_svg=pnl_svg, pnl_chips=pnl_chips, pnl_script=pnl_script,
        n_pnl_tickers=len(pnl_tickers), starting_capital=money(args.starting_capital),
        daily_svg=daily_svg, n_days=n_days,
        ticker_svg=ticker_svg, ticker_table=ticker_table,
        hold_tiles=hold_tiles,
        burn_section=burn_section,
        big_losses_section=big_losses_section,
        comm_total=money(comm["total"]), comm_n=comm["n"], comm_avg=money(comm["avg"]),
        comm_rate=pct(comm["rate"], digits=2),
        opt_comm=money(comm["opt_comm"]), opt_prem=money(summary["option_premium"]),
        cheap_note=cheap_note,
        top_ticker=esc(comm["top_ticker"]), top_ticker_comm=money(comm["top_ticker_comm"]),
        comm_n_tickers=comm["n_tickers"], comm_top_rows=comm["top_rows"],
        comm_rest_block=comm_rest_block,
        rules_rows=(rules["rows"] if rules else ""),
        rules_unchecked=(rules["unchecked"] if rules else ""),
        n_checked=(rules["n_checked"] if rules else 0),
        n_rules=((rules["n_checked"] + rules["n_unchecked"]) if rules else 0),
        n_unchecked=(rules["n_unchecked"] if rules else 0),
        account=(money(rules_json["account"]) if rules_json else ""),
    )
    if not rules:
        # swap the rules section out for the "no rules supplied" note
        start = html.index('<section>\n    <div class="sec-head"><h2>Risk rules check</h2>')
        end = html.index("</section>", start) + len("</section>")
        html = html[:start] + NO_RULES.strip() + html[end:]
    return html


def pct_int(v):
    return "{:.0f}%".format(v * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=True)
    ap.add_argument("--trades", required=True)
    ap.add_argument("--rules")
    ap.add_argument("--burn")
    ap.add_argument("--loss-threshold", type=float, default=750,
                    help="flag exits that lost more than this in the 'Biggest losses' section")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", help="e.g. 'Sep 14-18, 2026' — defaults to the summary's week_start")
    ap.add_argument("--starting-capital", type=float, default=100000,
                    help="scales the P&L-over-time chart's y-axis against the full account "
                         "(0 to at least this) instead of auto-fitting to the week's swing")
    ap.add_argument("--title", default="Trade Week Ledger")
    args = ap.parse_args()

    html = build(args)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
