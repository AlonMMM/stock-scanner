#!/usr/bin/env python3
"""
Technical-scan analysis engine.

Takes the raw JSON bar data and option open-interest table that Claude already
pulled from the IBKR MCP tools (get_price_history / get_option_data /
get_price_snapshot) and turns it into:

  - a JSON summary (support/resistance, options magnets, relative strength)
    printed to stdout
  - five PNG charts (daily, hourly, intraday+volume-profile, options OI/max
    pain, relative strength vs benchmark) written to --outdir
  - one self-contained HTML report that embeds all five charts plus the
    numeric summary, written to --outdir/report.html

This script does no network I/O. All data comes from the files Claude saved
after calling the MCP tools; see SKILL.md for the fetch sequence.
"""
import argparse
import base64
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import mplfinance as mpf
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_bars_df(path):
    """Load an IBKR get_price_history JSON payload into a DataFrame indexed by
    UTC timestamp with columns Open/High/Low/Close/Volume (mplfinance's
    expected capitalisation)."""
    with open(path) as f:
        d = json.load(f)
    idx = pd.to_datetime(d["time"], utc=True)
    df = pd.DataFrame(
        {
            "Open": d["open"],
            "High": d["high"],
            "Low": d["low"],
            "Close": d["close"],
            "Volume": d["volume"],
        },
        index=idx,
    )
    return df


def load_options(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Support / resistance
# ---------------------------------------------------------------------------

def classic_pivots(prev_high, prev_low, prev_close):
    pp = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pp - prev_low
    s1 = 2 * pp - prev_high
    r2 = pp + (prev_high - prev_low)
    s2 = pp - (prev_high - prev_low)
    r3 = prev_high + 2 * (pp - prev_low)
    s3 = prev_low - 2 * (prev_high - pp)
    return {"pp": pp, "r1": r1, "r2": r2, "r3": r3, "s1": s1, "s2": s2, "s3": s3}


def swing_points(df, window=3):
    """Fractal swing highs/lows: a bar is a swing high/low if it is the max/min
    of the `window` bars on each side of it."""
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)
    res, sup = [], []
    for i in range(window, n - window):
        seg_h = highs[i - window : i + window + 1]
        seg_l = lows[i - window : i + window + 1]
        if highs[i] == seg_h.max():
            res.append(highs[i])
        if lows[i] == seg_l.min():
            sup.append(lows[i])
    return res, sup


def cluster_levels(levels, tol_pct=0.006, top_n=6):
    """Merge nearby swing levels into zones; strength = how many swings landed
    in the zone. This is what turns a scatter of swing points into a short
    list of levels worth drawing."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters, cur = [], [levels[0]]
    for lv in levels[1:]:
        if abs(lv - cur[-1]) / cur[-1] <= tol_pct:
            cur.append(lv)
        else:
            clusters.append(cur)
            cur = [lv]
    clusters.append(cur)
    out = [{"level": sum(c) / len(c), "strength": len(c)} for c in clusters]
    out.sort(key=lambda x: -x["strength"])
    return out[:top_n]


def volume_profile(df, bins=40, value_area_pct=0.70):
    """Volume-at-price profile. Each bar's volume is spread across the price
    bins its High-Low range overlaps (not just dumped on the close), which is
    the standard construction. Returns bin centers, volume per bin, POC
    (point of control), VAH/VAL (value-area high/low)."""
    lo, hi = df["Low"].min(), df["High"].max()
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for l, h, c, v in zip(df["Low"], df["High"], df["Close"], df["Volume"]):
        if h <= l:
            idx = int(np.clip(np.searchsorted(edges, c) - 1, 0, bins - 1))
            vol[idx] += v
            continue
        ov = np.minimum(h, edges[1:]) - np.maximum(l, edges[:-1])
        ov = np.clip(ov, 0, None)
        total = ov.sum()
        if total <= 0:
            idx = int(np.clip(np.searchsorted(edges, c) - 1, 0, bins - 1))
            vol[idx] += v
        else:
            vol += v * ov / total
    centers = (edges[:-1] + edges[1:]) / 2
    poc_idx = int(np.argmax(vol))
    total = vol.sum()
    target = total * value_area_pct
    lo_i = hi_i = poc_idx
    acc = vol[poc_idx]
    while acc < target and (lo_i > 0 or hi_i < bins - 1):
        left = vol[lo_i - 1] if lo_i > 0 else -1
        right = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if right >= left:
            hi_i += 1
            acc += vol[hi_i]
        else:
            lo_i -= 1
            acc += vol[lo_i]
    return centers, vol, centers[poc_idx], edges[hi_i + 1], edges[lo_i]


def session_vwap(df):
    """Per-session (per calendar day) VWAP plus a +-1 stdev band, reset at the
    start of each session. Returns three Series aligned to df.index."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    day = df.index.date
    vwap = pd.Series(index=df.index, dtype=float)
    upper = pd.Series(index=df.index, dtype=float)
    lower = pd.Series(index=df.index, dtype=float)
    for d in pd.unique(day):
        mask = day == d
        v = df["Volume"][mask].values
        p = tp[mask].values
        cum_v = np.cumsum(v)
        cum_pv = np.cumsum(p * v)
        cum_pv2 = np.cumsum(p * p * v)
        safe_v = np.where(cum_v == 0, 1, cum_v)
        vw = cum_pv / safe_v
        var = np.clip(cum_pv2 / safe_v - vw * vw, 0, None)
        sd = np.sqrt(var)
        vwap[mask] = vw
        upper[mask] = vw + sd
        lower[mask] = vw - sd
    return vwap, upper, lower


# ---------------------------------------------------------------------------
# Options magnets
# ---------------------------------------------------------------------------

def call_put_walls(strikes):
    call_wall = max(strikes, key=lambda s: s["call_oi"])
    put_wall = max(strikes, key=lambda s: s["put_oi"])
    return call_wall, put_wall


def max_pain(strikes):
    """Strike that minimizes the total intrinsic value option WRITERS would
    have to pay out at expiry -- the classic 'max pain' price. This only uses
    open interest (no IV/gamma assumptions), so it is robust to missing
    Greeks."""
    best_k, best_cost = None, None
    for cand in strikes:
        K = cand["strike"]
        cost = 0.0
        for s in strikes:
            if K > s["strike"]:
                cost += s["call_oi"] * (K - s["strike"])
            if K < s["strike"]:
                cost += s["put_oi"] * (s["strike"] - K)
        if best_cost is None or cost < best_cost:
            best_cost, best_k = cost, K
    return best_k, best_cost


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

STYLE = mpf.make_mpf_style(
    base_mpf_style="charles",
    rc={"font.size": 9},
    marketcolors=mpf.make_marketcolors(
        up="#1a9e5c", down="#d1453b", edge="inherit", wick="inherit", volume="inherit"
    ),
)


def fig_to_b64(fig):
    import io

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def plot_daily(df, ticker, outdir, pivots, sr_clusters, prev_week_hi, prev_week_lo):
    hlines = [pivots["r1"], pivots["r2"], pivots["pp"], pivots["s1"], pivots["s2"]]
    colors = ["#d1453b", "#d1453b", "#7a7a7a", "#1a9e5c", "#1a9e5c"]
    for c in sr_clusters:
        hlines.append(c["level"])
        colors.append("#8a5cff")
    hlines += [prev_week_hi, prev_week_lo]
    colors += ["#c98a00", "#c98a00"]
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=STYLE,
        volume=True,
        hlines=dict(hlines=hlines, colors=colors, linestyle="--", linewidths=0.8),
        title=f"{ticker} - Daily (6mo) - pivots, swing S/R, prior-week range",
        returnfig=True,
        figsize=(11, 6.5),
    )
    path = os.path.join(outdir, "01_daily.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig


def plot_hourly(df, ticker, outdir, pivots):
    hlines = [pivots["r1"], pivots["pp"], pivots["s1"]]
    colors = ["#d1453b", "#7a7a7a", "#1a9e5c"]
    fig, axes = mpf.plot(
        df,
        type="candle",
        style=STYLE,
        volume=True,
        hlines=dict(hlines=hlines, colors=colors, linestyle="--", linewidths=0.8),
        title=f"{ticker} - Hourly (last month) - daily pivot context",
        returnfig=True,
        figsize=(11, 6.5),
    )
    path = os.path.join(outdir, "02_hourly.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig


def plot_intraday_with_profile(df, ticker, outdir, vwap, upper, lower, centers, vol, poc, vah, val):
    fig = plt.figure(figsize=(12, 6.5))
    gs = fig.add_gridspec(1, 5)
    ax_price = fig.add_subplot(gs[0, :4])
    ax_vp = fig.add_subplot(gs[0, 4], sharey=ax_price)

    mpf.plot(df, type="candle", style=STYLE, ax=ax_price)
    ax_price.plot(range(len(df)), vwap.values, color="#0057d8", linewidth=1.3, label="Session VWAP")
    ax_price.plot(range(len(df)), upper.values, color="#0057d8", linewidth=0.7, linestyle=":")
    ax_price.plot(range(len(df)), lower.values, color="#0057d8", linewidth=0.7, linestyle=":")
    ax_price.axhline(poc, color="#c98a00", linewidth=1.0, label="POC")
    ax_price.axhline(vah, color="#8a5cff", linewidth=0.8, linestyle="--", label="VAH")
    ax_price.axhline(val, color="#8a5cff", linewidth=0.8, linestyle="--", label="VAL")
    ax_price.legend(loc="upper left", fontsize=7)
    ax_price.set_title(f"{ticker} - last 2 sessions (5-min) - VWAP + volume profile")

    ax_vp.barh(centers, vol, height=(centers[1] - centers[0]) * 0.9, color="#7a7a7a")
    ax_vp.axhline(poc, color="#c98a00", linewidth=1.2)
    ax_vp.axhline(vah, color="#8a5cff", linewidth=0.8, linestyle="--")
    ax_vp.axhline(val, color="#8a5cff", linewidth=0.8, linestyle="--")
    ax_vp.set_title("Volume profile", fontsize=9)
    ax_vp.tick_params(labelleft=False)

    fig.tight_layout()
    path = os.path.join(outdir, "03_intraday_volume_profile.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig


def plot_options(strikes, ticker, expiry, spot, outdir):
    strikes_sorted = sorted(strikes, key=lambda s: s["strike"])
    ks = [s["strike"] for s in strikes_sorted]
    calls = [s["call_oi"] for s in strikes_sorted]
    puts = [s["put_oi"] for s in strikes_sorted]
    call_wall, put_wall = call_put_walls(strikes_sorted)
    mp_strike, _ = max_pain(strikes_sorted)

    x = np.arange(len(ks))
    width = 0.4
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x - width / 2, calls, width, label="Call OI", color="#1a9e5c")
    ax.bar(x + width / 2, puts, width, label="Put OI", color="#d1453b")
    ax.set_xticks(x)
    ax.set_xticklabels([str(k) for k in ks], rotation=45)
    ax.set_ylabel("Open interest (contracts)")
    ax.set_title(f"{ticker} options open interest by strike - exp {expiry}")

    spot_x = np.interp(spot, ks, x)
    ax.axvline(spot_x, color="black", linewidth=1.4, label=f"Spot {spot:g}")
    cw_x = ks.index(call_wall["strike"])
    pw_x = ks.index(put_wall["strike"])
    mp_x = ks.index(mp_strike)
    ax.axvline(cw_x, color="#1a9e5c", linewidth=1.2, linestyle="--", label=f"Call wall {call_wall['strike']:g}")
    ax.axvline(pw_x, color="#d1453b", linewidth=1.2, linestyle="--", label=f"Put wall {put_wall['strike']:g}")
    ax.axvline(mp_x, color="#8a5cff", linewidth=1.2, linestyle=":", label=f"Max pain {mp_strike:g}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = os.path.join(outdir, "04_options_oi.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig, call_wall, put_wall, mp_strike


def plot_relative_strength(df_t, df_b, ticker, bench, outdir):
    """Normalized intraday % move, ticker vs benchmark, re-based to 0 at the
    start of EACH session (so a multi-day window doesn't carry yesterday's
    drift into today) and plotted on a positional x-axis so the overnight
    gap doesn't get drawn as a sloped line connecting two sessions."""
    joined = pd.DataFrame({"t": df_t["Close"], "b": df_b["Close"]}).dropna()
    day = joined.index.date
    t_pct = pd.Series(index=joined.index, dtype=float)
    b_pct = pd.Series(index=joined.index, dtype=float)
    for d in pd.unique(day):
        mask = day == d
        t_pct[mask] = (joined["t"][mask] / joined["t"][mask].iloc[0] - 1) * 100
        b_pct[mask] = (joined["b"][mask] / joined["b"][mask].iloc[0] - 1) * 100
    spread = t_pct - b_pct

    x = np.arange(len(joined))
    # break the connecting line at each session boundary
    session_start = np.array([d != day[i - 1] if i > 0 else False for i, d in enumerate(day)])
    t_plot, b_plot, s_plot = t_pct.values.copy(), b_pct.values.copy(), spread.values.copy()

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"height_ratios": [2, 1]}
    )
    # plot each session as its own segment so matplotlib never bridges the gap
    bounds = [0] + list(np.where(session_start)[0]) + [len(x)]
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        label_t = f"{ticker} % chg" if i == 0 else None
        label_b = f"{bench} % chg" if i == 0 else None
        ax1.plot(x[a:b], t_plot[a:b], color="#0057d8", label=label_t)
        ax1.plot(x[a:b], b_plot[a:b], color="#7a7a7a", label=label_b)
        ax2.fill_between(x[a:b], s_plot[a:b], 0, where=(s_plot[a:b] >= 0), color="#1a9e5c", alpha=0.6)
        ax2.fill_between(x[a:b], s_plot[a:b], 0, where=(s_plot[a:b] < 0), color="#d1453b", alpha=0.6)
    for b in bounds[1:-1]:
        ax1.axvline(b, color="#cccccc", linewidth=0.8, linestyle=":")
        ax2.axvline(b, color="#cccccc", linewidth=0.8, linestyle=":")

    ax1.axhline(0, color="black", linewidth=0.6)
    ax1.legend(fontsize=8)
    ax1.set_title(f"{ticker} vs {bench} - normalized intraday % move, rebased each session")
    ax2.axhline(0, color="black", linewidth=0.6)
    ax2.set_title(f"Relative strength spread ({ticker} - {bench}), pp", fontsize=9)

    tick_idx = np.linspace(0, len(x) - 1, min(10, len(x))).astype(int)
    ax2.set_xticks(tick_idx)
    ax2.set_xticklabels([joined.index[i].strftime("%m-%d %H:%M") for i in tick_idx], rotation=45, ha="right")
    fig.tight_layout()
    path = os.path.join(outdir, "05_relative_strength.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig, float(spread.iloc[-1])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--benchmark", default="SPY")
    ap.add_argument("--daily", required=True, help="IBKR ONE_DAY bars JSON")
    ap.add_argument("--hourly", required=True, help="IBKR ONE_HOUR bars JSON")
    ap.add_argument("--intraday", required=True, help="IBKR intraday (1-5min) bars JSON, ticker")
    ap.add_argument("--bench-intraday", required=True, help="Same, for the benchmark")
    ap.add_argument("--options", required=True, help="options_oi.json (see SKILL.md schema)")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    daily = load_bars_df(args.daily)
    hourly = load_bars_df(args.hourly)
    intraday = load_bars_df(args.intraday)
    bench_intraday = load_bars_df(args.bench_intraday)
    opt = load_options(args.options)

    # --- pivots off the last completed daily bar ---
    prev = daily.iloc[-1]
    pivots = classic_pivots(prev["High"], prev["Low"], prev["Close"])

    # --- prior week range ---
    daily_by_week = daily.copy()
    daily_by_week["week"] = daily_by_week.index.isocalendar().week
    last_week = daily_by_week["week"].iloc[-1]
    prior_week_df = daily_by_week[daily_by_week["week"] != last_week].tail(5)
    prev_week_hi = prior_week_df["High"].max() if len(prior_week_df) else daily["High"].max()
    prev_week_lo = prior_week_df["Low"].min() if len(prior_week_df) else daily["Low"].min()

    # --- swing S/R clusters, daily timeframe ---
    res_swings, sup_swings = swing_points(daily, window=3)
    sr_clusters = cluster_levels(res_swings + sup_swings, tol_pct=0.008, top_n=6)

    # --- volume profile + VWAP on the intraday tape ---
    centers, vol, poc, vah, val = volume_profile(intraday, bins=36)
    vwap, vwap_u, vwap_l = session_vwap(intraday)

    # --- options magnets ---
    strikes = opt["strikes"]
    spot = opt.get("spot", float(intraday["Close"].iloc[-1]))

    # --- charts ---
    p1, f1 = plot_daily(daily, args.ticker, args.outdir, pivots, sr_clusters, prev_week_hi, prev_week_lo)
    p2, f2 = plot_hourly(hourly, args.ticker, args.outdir, pivots)
    p3, f3 = plot_intraday_with_profile(intraday, args.ticker, args.outdir, vwap, vwap_u, vwap_l, centers, vol, poc, vah, val)
    p4, f4, call_wall, put_wall, mp_strike = plot_options(strikes, args.ticker, opt.get("expiry", "?"), spot, args.outdir)
    p5, f5, rs_spread_now = plot_relative_strength(intraday, bench_intraday, args.ticker, args.benchmark, args.outdir)

    summary = {
        "ticker": args.ticker,
        "spot": spot,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pivots_from_prior_day": {k: round(v, 2) for k, v in pivots.items()},
        "prior_week_range": {"high": round(float(prev_week_hi), 2), "low": round(float(prev_week_lo), 2)},
        "swing_sr_clusters": [
            {"level": round(c["level"], 2), "strength": c["strength"]} for c in sr_clusters
        ],
        "volume_profile": {
            "poc": round(float(poc), 2),
            "value_area_high": round(float(vah), 2),
            "value_area_low": round(float(val), 2),
        },
        "session_vwap_last": round(float(vwap.iloc[-1]), 2),
        "options": {
            "expiry": opt.get("expiry"),
            "dte": opt.get("dte"),
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_pain": mp_strike,
        },
        "relative_strength_vs_benchmark_pp": round(rs_spread_now, 2),
        "charts": [os.path.basename(p) for p in [p1, p2, p3, p4, p5]],
    }

    with open(os.path.join(args.outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # --- self-contained HTML report ---
    imgs_b64 = {os.path.basename(p): fig_to_b64(fig) for p, fig in [(p1, f1), (p2, f2), (p3, f3), (p4, f4), (p5, f5)]}
    html = build_html_report(args.ticker, summary, imgs_b64)
    with open(os.path.join(args.outdir, "report.html"), "w") as f:
        f.write(html)

    print(json.dumps(summary, indent=2))


def build_html_report(ticker, summary, imgs_b64):
    def img(name):
        return f'<img src="data:image/png;base64,{imgs_b64[name]}" style="width:100%;border-radius:8px;margin:12px 0;">'

    opt = summary["options"]
    piv = summary["pivots_from_prior_day"]
    vp = summary["volume_profile"]
    pw = summary["prior_week_range"]

    rows = "".join(
        f"<tr><td>{c['level']:.2f}</td><td>{c['strength']}</td></tr>"
        for c in summary["swing_sr_clusters"]
    )

    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>{ticker} — ניתוח טכני</title>
<style>
body{{font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:920px;margin:24px auto;padding:0 16px;color:#1a1a1a;background:#fafafa}}
h1{{font-size:22px}} h2{{font-size:16px;border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:32px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #ddd;padding:6px 10px;text-align:center}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.card{{background:#fff;border:1px solid #e5e5e5;border-radius:8px;padding:12px 16px}}
.tag{{display:inline-block;background:#eef2ff;color:#3345cc;border-radius:6px;padding:2px 8px;font-size:12px;margin:2px}}
</style></head>
<body>
<h1>{ticker} — סריקה טכנית (רמות, ווליום, אופציות, חוזק יחסי)</h1>
<p>נוצר: {summary['generated_at']} &middot; מחיר נוכחי: <b>{summary['spot']:.2f}</b></p>

<div class="grid">
  <div class="card"><b>Pivot (יומי, מחושב מהיום הקודם)</b><br>
    R2 {piv['r2']:.2f} · R1 {piv['r1']:.2f} · <b>PP {piv['pp']:.2f}</b> · S1 {piv['s1']:.2f} · S2 {piv['s2']:.2f}
  </div>
  <div class="card"><b>טווח שבוע קודם</b><br>High {pw['high']:.2f} · Low {pw['low']:.2f}</div>
  <div class="card"><b>Volume Profile (יומיים אחרונים)</b><br>
    POC {vp['poc']:.2f} · VAH {vp['value_area_high']:.2f} · VAL {vp['value_area_low']:.2f}
  </div>
  <div class="card"><b>מגנטים באופציות (תפוגה {opt['expiry']}, {opt['dte']} DTE)</b><br>
    Call wall <span class="tag">{opt['call_wall']['strike']:g}</span> (OI {opt['call_wall']['call_oi']})<br>
    Put wall <span class="tag">{opt['put_wall']['strike']:g}</span> (OI {opt['put_wall']['put_oi']})<br>
    Max pain <span class="tag">{opt['max_pain']:g}</span>
  </div>
</div>

<h2>רמות תמיכה/התנגדות מבליטות (סווינג, יומי)</h2>
<table><tr><th>רמה</th><th>עוצמה (מס' פעמים שנגעה)</th></tr>{rows}</table>

<h2>1. יומי (6 חודשים) — Pivots, סווינג S/R, שבוע קודם</h2>
{img('01_daily.png')}

<h2>2. שעתי (חודש אחרון) — הקשר ה-Pivot היומי</h2>
{img('02_hourly.png')}

<h2>3. תוך-יומי (5 דק', יומיים אחרונים) — VWAP + Volume Profile</h2>
{img('03_intraday_volume_profile.png')}

<h2>4. מגנטים באופציות — Open Interest לפי סטרייק</h2>
{img('04_options_oi.png')}

<h2>5. חוזק יחסי מול {summary.get('relative_strength_vs_benchmark_pp') and 'הבנצ׳מרק'}</h2>
<p>פער נוכחי: <b>{summary['relative_strength_vs_benchmark_pp']:+.2f} נק' אחוז</b> (המניה פחות הבנצ׳מרק, מנורמל מתחילת החלון)</p>
{img('05_relative_strength.png')}

</body></html>"""


if __name__ == "__main__":
    main()
