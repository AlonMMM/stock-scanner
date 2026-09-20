#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the trading-day/week prep report from IBKR account snapshots.

Consumes JSON files the orchestrating session pulls from IBKR MCP tools before
calling this (this script never touches IBKR itself — same split as the
weekly-trades skill's build_week.py):

    python3 build_prep.py \
        --account account_summary.json --positions positions.json \
        --watchlists watchlists.json [--quotes quotes.json] \
        --rules docs/risk-rules.md [--events events.md] \
        --out prep.html

account_summary.json  : get_account_summary output, verbatim.
positions.json         : get_account_positions output, verbatim.
watchlists.json        : {"List Name": ["TICK", ...], ...} - built by calling
                          get_watchlists then get_watchlist per id.
quotes.json (optional)  : {"TICK": {"last": .., "change": .., "change_pct": ..,
                          "prior_close": ..}, ...}. Missing tickers show as
                          "no quote" rather than being dropped silently.
events.md (optional)    : free-text/markdown the session wrote after a quick
                          check for this week's macro calendar and earnings
                          near open positions - there is no IBKR calendar
                          endpoint, so this is not fetched automatically.

The position-sizing table is computed from TODAY's actual net_liquidation,
not the account_value baked into risk-rules.md - that figure goes stale the
moment the account moves, and a sizing table built from a stale balance is
wrong in the specific way that matters most (position size).
"""
import argparse
import collections
import datetime
import json
import re
import sys


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_rules_params(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"```yaml\n(.*?)```", text, re.S)
    if not m:
        sys.exit("no ```yaml parameter block found in {}".format(path))
    import yaml
    return yaml.safe_load(m.group(1))


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def money(v, sign=False):
    s = "-" if v < 0 else ("+" if sign and v > 0 else "")
    return "{}${:,.0f}".format(s, abs(v))


def money2(v):
    return "${:,.2f}".format(v)


def pct(v, digits=1):
    return "{:+.{}f}%".format(v * 100, digits)


MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

OPT_RE = re.compile(r"^(\S+)\s+(?:FOP\s+)?([A-Za-z]{3})(\d{1,2})'(\d{2})\s+([\d.]+)\s+(CALL|PUT)")
FUT_RE = re.compile(r"^(\S+)\s+([A-Za-z]{3})'(\d{2})")


def parse_position(desc, asset_class, today):
    """Pulls ticker/expiry/strike/right out of IBKR's free-text contract
    description - the feed carries no structured fields for this."""
    if asset_class in ("OPT", "FOP"):
        m = OPT_RE.match(desc)
        if m:
            ticker, mon, day, yy, strike, right = m.groups()
            if mon not in MONTHS:
                return None
            expiry = datetime.date(2000 + int(yy), MONTHS[mon], int(day))
            return {"ticker": ticker, "expiry": expiry, "dte": (expiry - today).days,
                    "strike": float(strike), "right": right}
    elif asset_class == "FUT":
        m = FUT_RE.match(desc)
        if m:
            ticker, mon, yy = m.groups()
            if mon in MONTHS:
                return {"ticker": ticker, "expiry": None, "dte": None,
                        "strike": None, "right": "FUT"}
    return None


def stop_budget_for(dte, table):
    keys = sorted(table.keys())
    for k in keys:
        if dte <= k:
            return k, table[k]
    return keys[-1], table[keys[-1]]


def bucket_label(k):
    return {0: "0 days", 1: "1 day", 2: "2 days", 3: "3 days", 4: "4 days",
            5: "5 days", 7: "1 week", 31: "1 month"}.get(k, "{} days".format(k))


# ---------------------------------------------------------- account/sizing --

def render_account(acct, params, rules_path):
    net_liq = acct.get("net_liquidation", 0)
    configured = params.get("account_value")
    gap_note = ""
    if configured and abs(net_liq - configured) / configured > 0.02:
        drop = configured - net_liq
        gap_note = """
    <div class="callout">
      <div class="ctitle">&#9888; Net liquidation is {gapdir} {gap} ({gappct}) from the {acctval} baked into risk-rules.md</div>
      <p>The position-sizing table below is computed from today's real net liquidation, not that baseline, so
        it is not stale in itself. But rule 13's ladder (size halves every 5% down from the account's own
        high-water mark) depends on tracking that high-water mark continuously, which nothing here does yet
        &mdash; this tool cannot tell you which rung you are actually on. If {acctval} was a genuine prior high,
        a {gappct} drawdown is well past one halving under rule 13; check by hand before sizing at the base
        (1.0&times;) numbers below.</p>
    </div>""".format(gapdir="down" if net_liq < configured else "up",
                      gap=money(abs(drop)), gappct="{:.1f}%".format(abs(drop) / configured * 100),
                      acctval=money(configured))

    return """
    <div class="kpis">
      <div class="kpi"><div class="lab">Net liquidation</div><div class="val">{netliq}</div><div class="sub">{cur}</div></div>
      <div class="kpi"><div class="lab">Buying power</div><div class="val">{bp}</div></div>
      <div class="kpi"><div class="lab">Cash</div><div class="val">{cash}</div></div>
      <div class="kpi"><div class="lab">Margin used</div><div class="val">{marg}</div><div class="sub">of {excess} excess liquidity</div></div>
    </div>
    {gap_note}
    """.format(netliq=money(net_liq), cur=acct.get("currency", "USD"),
               bp=money(acct.get("buying_power", 0)), cash=money(acct.get("total_cash_value", 0)),
               marg=money(acct.get("initial_margin", 0)), excess=money(acct.get("excess_liquidity", 0)),
               gap_note=gap_note)


def render_sizing_table(net_liq, params):
    stop_budget = params["stop_budget"]
    risk = params["entry_risk_pct"]
    buckets = sorted(stop_budget.keys())
    rows = []
    for k in buckets:
        sb = stop_budget[k]
        std_pct = risk["dte_0_2_standard"] if k <= 2 else risk["dte_3_plus"]
        std_prem = std_pct * net_liq / sb
        row = "<tr><td>{lab}</td><td class=\"num\">{sb:.0f}%</td><td class=\"num\">{stdpct:.0f}%</td><td class=\"num\">{stdprem}</td>".format(
            lab=bucket_label(k), sb=sb * 100, stdpct=std_pct * 100, stdprem=money(std_prem))
        if k <= 2:
            agame_prem = risk["dte_0_2_agame"] * net_liq / sb
            row += "<td class=\"num\">{}</td>".format(money(agame_prem))
        else:
            row += "<td class=\"num\">&mdash;</td>"
        row += "</tr>"
        rows.append(row)
    return "\n".join(rows)


# ------------------------------------------------------------- positions --

def render_positions(positions, params, net_liq, today):
    open_pos = [p for p in positions if p.get("position")]
    if not open_pos:
        return None, 0
    stop_budget = params["stop_budget"]
    risk = params["entry_risk_pct"]
    rows = []
    for p in open_pos:
        info = parse_position(p["contract_description"], p.get("asset_class", ""), today)
        qty = p["position"]
        cost = p.get("average_price", 0) * abs(qty) * (100 if p.get("asset_class") == "OPT" else 1)
        # NQ/other FOP multiplier isn't in this feed; show cost basis via market_value's
        # implied multiplier instead of assuming 100, same fix as check_rules.py rule 6.
        mult = None
        if p.get("market_price") and p.get("market_value") and qty:
            denom = p["market_price"] * qty
            if denom:
                mult = p["market_value"] / denom
        if mult:
            cost = p.get("average_price", 0) * abs(qty) * mult
        upnl = p.get("unrealized_pnl", 0)
        if info and info["dte"] is not None:
            k, sb = stop_budget_for(max(info["dte"], 0), stop_budget)
            std_pct = risk["dte_0_2_standard"] if info["dte"] <= 2 else risk["dte_3_plus"]
            max_prem = std_pct * net_liq / sb
            over = cost > max_prem * 1.05
            sizing = '<span class="{cls}">{pctofmax:.0f}% of today\'s {lab} max</span>'.format(
                cls="neg" if over else "ink2", pctofmax=100 * cost / max_prem if max_prem else 0,
                lab=bucket_label(k))
            dte_lab = "{}d".format(info["dte"])
            ticker = info["ticker"]
            detail = "{:.0f}{} {}".format(info["strike"], info["right"][0], info["expiry"].strftime("%b %d"))
        else:
            dte_lab = "&mdash;"
            sizing = "&mdash;"
            ticker = p["contract_description"].split()[0]
            detail = p["contract_description"]
        rows.append(
            '<tr><td class="tkr">{t}</td><td>{d}</td><td class="num">{dte}</td>'
            '<td class="num">{qty}</td><td class="num">{costb}</td>'
            '<td class="num {upcls}">{upnl}</td><td>{sizing}</td></tr>'.format(
                t=esc(ticker), d=esc(detail), dte=dte_lab, qty=int(qty), costb=money(cost),
                upcls="pos" if upnl >= 0 else "neg", upnl=money(upnl, sign=True), sizing=sizing))
    return "\n".join(rows), len(open_pos)


# ------------------------------------------------------------- watchlists --

def render_watchlists(watchlists, quotes):
    quotes = quotes or {}
    groups = []
    n_with_quote = 0
    n_total = 0
    for name, tickers in watchlists.items():
        rows = []
        movers = []
        for t in tickers:
            n_total += 1
            q = quotes.get(t)
            if not q or q.get("change_pct") is None:
                rows.append((t, None))
                continue
            n_with_quote += 1
            rows.append((t, q))
            movers.append((t, q))
        movers.sort(key=lambda x: x[1]["change_pct"], reverse=True)
        no_quote = sorted(t for t, q in rows if q is None)
        row_html = "\n".join(
            '<tr><td class="tkr">{t}</td><td class="num">{last}</td>'
            '<td class="num {cls}">{chg}</td></tr>'.format(
                t=esc(t), last=money2(q["last"]) if q.get("last") is not None else "&mdash;",
                cls="pos" if q["change_pct"] >= 0 else "neg", chg=pct(q["change_pct"]))
            for t, q in movers)
        missing_note = ("<p class=\"cap\">No quote: {}</p>".format(esc(", ".join(no_quote)))
                        if no_quote else "")
        groups.append("""
      <details class="tk">
        <summary><span class="tk-sym">{name}</span><span class="tk-n">{n} tickers</span>
          <span class="tk-v {topcls}">{top}</span></summary>
        <div class="tbl-wrap"><table><thead><tr><th>Ticker</th><th style="text-align:right">Last</th>
          <th style="text-align:right">Chg</th></tr></thead><tbody>{rows}</tbody></table></div>
        {missing}
      </details>""".format(
            name=esc(name), n=len(tickers),
            topcls="pos" if movers and movers[0][1]["change_pct"] >= 0 else "neg",
            top=(esc(movers[0][0]) + " " + pct(movers[0][1]["change_pct"])) if movers else "no quotes",
            rows=row_html, missing=missing_note))
    return "\n".join(groups), n_with_quote, n_total


TEMPLATE = r"""<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap">
<style>
  :root {{
    color-scheme: light;
    --bg: #f5f6f8; --surface: #ffffff; --surface-2: #eef0f4;
    --ink: #12151b; --ink-2: #4b5563; --ink-3: #7c8698;
    --rule: #e2e5eb; --rule-2: #c9cedb;
    --pos: #059669; --neg: #dc2626; --accent: #b8790a; --accent-ink: #7a5006;
    --warnbg: #fdf3df; --warnrule: #e8c583; --warnink: #6b4a08;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      color-scheme: dark;
      --bg: #0a0c10; --surface: #12151b; --surface-2: #1a1e26;
      --ink: #eef1f5; --ink-2: #a6afc0; --ink-3: #707a8c;
      --rule: #232833; --rule-2: #333b4a;
      --pos: #34d399; --neg: #f87171; --accent: #f0b342; --accent-ink: #f0b342;
      --warnbg: #241b0e; --warnrule: #5c431a; --warnink: #f0c674;
    }}
  }}
  :root[data-theme="dark"] {{
    color-scheme: dark;
    --bg: #0a0c10; --surface: #12151b; --surface-2: #1a1e26;
    --ink: #eef1f5; --ink-2: #a6afc0; --ink-3: #707a8c;
    --rule: #232833; --rule-2: #333b4a;
    --pos: #34d399; --neg: #f87171; --accent: #f0b342; --accent-ink: #f0b342;
    --warnbg: #241b0e; --warnrule: #5c431a; --warnink: #f0c674;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); }}
  .page {{ background: var(--bg); color: var(--ink); font-family: "Public Sans", system-ui, sans-serif;
    font-size: 16px; line-height: 1.6; max-width: 1040px; margin: 0 auto; padding: 32px 20px 80px;
    display: flex; flex-direction: column; gap: 36px; }}
  .mono {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
  .masthead {{ display: flex; flex-direction: column; gap: 10px; border-bottom: 2px solid var(--ink); padding-bottom: 20px; }}
  .masthead .kicker {{ font-family: "IBM Plex Mono", monospace; font-size: 0.74rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--accent-ink); font-weight: 600; }}
  .masthead h1 {{ font-family: "Fraunces", Georgia, serif; font-size: clamp(1.8rem, 4.6vw, 2.6rem);
    line-height: 1.1; margin: 0; font-weight: 600; }}
  .stamp {{ display: flex; flex-wrap: wrap; gap: 6px 20px; font-size: 0.82rem; color: var(--ink-3); }}
  .stamp b {{ color: var(--ink-2); font-weight: 600; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1px;
    background: var(--rule); border: 1px solid var(--rule); border-radius: 4px; overflow: hidden; }}
  .kpi {{ background: var(--surface); padding: 16px 18px 14px; display: flex; flex-direction: column; gap: 4px; }}
  .kpi .lab {{ font-size: 0.76rem; color: var(--ink-3); font-weight: 600; }}
  .kpi .val {{ font-family: "IBM Plex Mono", monospace; font-size: 1.6rem; font-weight: 600; }}
  .kpi .sub {{ font-size: 0.79rem; color: var(--ink-2); }}
  .pos {{ color: var(--pos); }} .neg {{ color: var(--neg); }} .ink2 {{ color: var(--ink-2); }}
  section {{ display: flex; flex-direction: column; gap: 14px; }}
  .sec-head {{ display: flex; align-items: baseline; gap: 12px; border-bottom: 1px solid var(--rule-2); padding-bottom: 8px; }}
  .sec-head h2 {{ font-family: "Fraunces", Georgia, serif; font-weight: 600; font-size: 1.3rem; margin: 0; }}
  .sec-head .tag {{ font-family: "IBM Plex Mono", monospace; font-size: 0.7rem; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--ink-3); font-weight: 600; margin-inline-start: auto; white-space: nowrap; }}
  section > p {{ margin: 0; max-width: 72ch; color: var(--ink-2); }}
  .callout {{ background: var(--warnbg); border: 1px solid var(--warnrule); border-radius: 4px; padding: 16px 18px;
    color: var(--warnink); display: flex; flex-direction: column; gap: 6px; }}
  .callout .ctitle {{ font-weight: 700; }}
  .callout p {{ margin: 0; color: var(--warnink); opacity: 0.92; max-width: 74ch; }}
  .tbl-wrap {{ overflow-x: auto; border: 1px solid var(--rule); border-radius: 4px; background: var(--surface); }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.86rem; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--rule); }}
  thead th {{ background: var(--surface-2); font-size: 0.7rem; letter-spacing: 0.06em; text-transform: uppercase;
    color: var(--ink-3); font-weight: 700; white-space: nowrap; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  td.num {{ font-family: "IBM Plex Mono", monospace; text-align: right; white-space: nowrap; }}
  td.tkr {{ font-family: "IBM Plex Mono", monospace; font-weight: 700; }}
  .cap {{ font-size: 0.82rem; color: var(--ink-3); margin: 6px 0 0; }}
  .watchlists {{ display: flex; flex-direction: column; gap: 2px; background: var(--rule);
    border: 1px solid var(--rule); border-radius: 4px; overflow: hidden; }}
  details.tk {{ background: var(--surface); }}
  details.tk > summary {{ cursor: pointer; list-style: none; display: flex; align-items: center; gap: 14px;
    padding: 10px 14px; font-size: 0.88rem; }}
  details.tk > summary::-webkit-details-marker {{ display: none; }}
  details.tk > summary::before {{ content: "\25b8"; color: var(--ink-3); font-size: 0.78rem; flex: 0 0 auto; transition: transform .12s ease; }}
  details.tk[open] > summary::before {{ transform: rotate(90deg); }}
  details.tk > summary:hover {{ background: var(--surface-2); }}
  .tk-sym {{ font-weight: 700; min-width: 200px; }}
  .tk-n {{ color: var(--ink-3); font-size: 0.8rem; }}
  .tk-v {{ margin-inline-start: auto; font-family: "IBM Plex Mono", monospace; font-weight: 600; font-size: 0.84rem; }}
  details.tk .tbl-wrap {{ border: none; border-top: 1px solid var(--rule); border-radius: 0; }}
  details.tk table {{ font-size: 0.82rem; }}
  .events {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 4px; padding: 16px 18px; }}
  footer.foot {{ border-top: 1px solid var(--rule); padding-top: 16px; font-size: 0.8rem; color: var(--ink-3); max-width: 74ch; }}
</style>

<div class="page">
  <header class="masthead">
    <div class="kicker">Trading Session Prep</div>
    <h1>{h1}</h1>
    <div class="stamp">
      <span>Generated <b>{stamp}</b></span>
      <span>Source <b>Interactive Brokers</b></span>
    </div>
  </header>

  <section>
    <div class="sec-head"><h2>Account</h2></div>
    {account_html}
  </section>

  <section>
    <div class="sec-head"><h2>Today's position sizing</h2><span class="tag">live, from net liquidation</span></div>
    <p>Computed fresh from today's net liquidation &mdash; not the account_value baked into risk-rules.md, which
      goes stale the moment the account moves. Base (1.0&times;) rung only; rule 13's ladder needs a tracked
      high-water mark this tool does not yet have (see the callout above if the account has moved a lot).</p>
    <div class="tbl-wrap">
      <table><thead><tr><th>Time to expiration</th><th style="text-align:right">Stop budget</th>
        <th style="text-align:right">Risk %</th><th style="text-align:right">Max premium</th>
        <th style="text-align:right">A-game (0-2d only)</th></tr></thead>
      <tbody>{sizing_rows}</tbody></table>
    </div>
  </section>

  {positions_section}

  <section>
    <div class="sec-head"><h2>Watchlists</h2><span class="tag">{n_quoted} of {n_total} tickers quoted</span></div>
    <p>{list_summary}Grouped by list; each opens to the full table, sorted by today's move.</p>
    <div class="watchlists">{watchlist_groups}</div>
  </section>

  <section>
    <div class="sec-head"><h2>Events this week</h2></div>
    <div class="events">{events_html}</div>
  </section>

  <footer class="foot">
    <p>Position sizing follows docs/risk-rules.md rules 1-4. Watchlist quotes and account state are a snapshot
      at generation time, not live. No IBKR endpoint returns an earnings/economic calendar directly, so the
      events section is only as good as what was checked before this ran.</p>
  </footer>
</div>
"""


def build(args):
    acct = load_json(args.account)
    positions = load_json(args.positions)["positions"]
    watchlists = load_json(args.watchlists)
    quotes = load_json(args.quotes) if args.quotes else {}
    params = load_rules_params(args.rules)

    today = datetime.date.today()
    net_liq = acct.get("net_liquidation", 0)

    account_html = render_account(acct, params, args.rules)
    sizing_rows = render_sizing_table(net_liq, params)
    pos_rows, n_open = render_positions(positions, params, net_liq, today)
    if pos_rows:
        positions_section = """
  <section>
    <div class="sec-head"><h2>Open positions</h2><span class="tag">{n} positions</span></div>
    <div class="tbl-wrap">
      <table><thead><tr><th>Ticker</th><th>Contract</th><th style="text-align:right">DTE</th>
        <th style="text-align:right">Qty</th><th style="text-align:right">Cost basis</th>
        <th style="text-align:right">Unrealized</th><th>Sizing</th></tr></thead>
      <tbody>{rows}</tbody></table>
    </div>
  </section>""".format(n=n_open, rows=pos_rows)
    else:
        positions_section = """
  <section>
    <div class="sec-head"><h2>Open positions</h2></div>
    <p>No open positions.</p>
  </section>"""

    wl_groups, n_quoted, n_total = render_watchlists(watchlists, quotes)
    list_summary = ""
    if n_total and n_quoted < n_total:
        list_summary = "{} of {} tickers had no live quote this run. ".format(n_total - n_quoted, n_total)

    events_html = "<p>No events file supplied for this run.</p>"
    if args.events:
        with open(args.events, encoding="utf-8") as fh:
            events_text = fh.read().strip()
        if events_text:
            # minimal markdown: paragraphs and "- " bullets, nothing fancier
            parts = []
            for block in events_text.split("\n\n"):
                lines = [l.strip() for l in block.splitlines() if l.strip()]
                if not lines:
                    continue
                if all(l.startswith("-") for l in lines):
                    parts.append("<ul>" + "".join(
                        "<li>{}</li>".format(esc(l[1:].strip())) for l in lines) + "</ul>")
                else:
                    parts.append("<p>{}</p>".format(esc(" ".join(lines))))
            events_html = "\n".join(parts)

    html = TEMPLATE.format(
        title=args.title,
        h1="{} prep".format(args.label or today.isoformat()),
        stamp=datetime.datetime.now().strftime("%a %b %d, %H:%M"),
        account_html=account_html,
        sizing_rows=sizing_rows,
        positions_section=positions_section,
        n_quoted=n_quoted, n_total=n_total, list_summary=list_summary,
        watchlist_groups=wl_groups,
        events_html=events_html,
    )
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--positions", required=True)
    ap.add_argument("--watchlists", required=True)
    ap.add_argument("--quotes")
    ap.add_argument("--rules", default="docs/risk-rules.md")
    ap.add_argument("--events")
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", help="e.g. 'Mon Sep 21' — defaults to today's date")
    ap.add_argument("--title", default="Session Prep")
    args = ap.parse_args()

    html = build(args)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
