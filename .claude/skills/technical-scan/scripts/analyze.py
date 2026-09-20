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
# Beta-adjusted relative strength
# ---------------------------------------------------------------------------

def compute_beta(stock_daily, bench_daily, lookback=60):
    """Beta of the stock vs. the benchmark from daily log returns:
    beta = cov(r_stock, r_bench) / var(r_bench), estimated over the trailing
    `lookback` trading days (default ~3 months) so it reflects the current
    regime rather than a stale full-history figure. Also returns the
    correlation, since a beta computed from a weak relationship is worth
    flagging rather than trusting blindly."""
    joined = pd.DataFrame(
        {"s": stock_daily["Close"], "b": bench_daily["Close"]}
    ).dropna()
    r = np.log(joined).diff().dropna()
    r = r.tail(lookback)
    var_b = r["b"].var()
    beta = float(r["s"].cov(r["b"]) / var_b) if var_b > 0 else 1.0
    corr = float(r["s"].corr(r["b"])) if len(r) > 2 else float("nan")
    return beta, corr, len(r)


def session_rebased_pct(df, day):
    """Cumulative % return from each session's own first bar (not the whole
    window's first bar), so a multi-day chart never carries one day's drift
    into the next day's normalization."""
    pct = pd.Series(index=df.index, dtype=float)
    for d in pd.unique(day):
        mask = day == d
        pct[mask] = (df["Close"][mask] / df["Close"][mask].iloc[0] - 1) * 100
    return pct


def detect_divergence_windows(times, stock_ret, bench_ret, window=6, bench_floor=0.15, stock_flat=0.07):
    """Scan a rolling `window`-bar return for two things worth calling out
    explicitly, not just leaving buried in a continuous line:

      - 'against': the stock's window return has the OPPOSITE SIGN of the
        benchmark's, i.e. it moved against the tape, not just less with it.
      - 'held': the benchmark moved by a real amount (>= bench_floor) while
        the stock stayed inside a small flat band (< stock_flat) -- it
        shrugged off a real index move rather than trading through it.

    Both thresholds are in percentage points over the window and exist so a
    single-bar bid/ask flicker doesn't get reported as "the stock fought the
    tape" -- the default window is 6 bars (30 minutes on 5-min data) with
    floors calibrated to a typical SPY half-hour move, deliberately coarser
    than the bar interval so only a sustained, real divergence gets flagged.
    Consecutive flagged bars of the same class are merged into a single
    interval. Returns a list of dicts with start/end index, start/end time,
    class, and the two window returns."""
    n = len(stock_ret)
    labels = [None] * n
    for i in range(window, n):
        sr = stock_ret[i] - stock_ret[i - window]
        br = bench_ret[i] - bench_ret[i - window]
        if abs(br) < bench_floor:
            continue
        if np.sign(sr) != np.sign(br) and abs(sr) >= stock_flat:
            labels[i] = "against"
        elif abs(sr) < stock_flat:
            labels[i] = "held"

    windows = []
    i = 0
    while i < n:
        if labels[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < n and labels[j + 1] == labels[i]:
            j += 1
        windows.append(
            {
                "class": labels[i],
                "start_idx": i - window,
                "end_idx": j,
                "start_time": times[max(i - window, 0)].isoformat(),
                "end_time": times[j].isoformat(),
                "stock_move_pp": round(float(stock_ret[j] - stock_ret[max(i - window, 0)]), 3),
                "bench_move_pp": round(float(bench_ret[j] - bench_ret[max(i - window, 0)]), 3),
            }
        )
        i = j + 1
    return windows


# ---------------------------------------------------------------------------
# Trade plan: a single ranked ladder of every level this script found,
# collapsed into what's actually next above and below spot
# ---------------------------------------------------------------------------

def build_level_ladder(spot, pivots, sr_clusters, vp, prev_week, vwap_last, options, zone_tol_pct=0.006):
    """Every support/resistance this script computed, from every source,
    merged into one list and split into what's above spot (resistance) and
    below it (support). This is the thing a chart full of separate lines
    doesn't answer directly: "what's the very next level either way, and
    does anything else agree with it?"

    Each entry: {level, label, source}. Sources: pivot, swing (with its
    touch count), volume_profile, prior_week, vwap, options.
    """
    raw = [
        {"level": pivots["r1"], "label": "R1", "source": "pivot"},
        {"level": pivots["r2"], "label": "R2", "source": "pivot"},
        {"level": pivots["r3"], "label": "R3", "source": "pivot"},
        {"level": pivots["pp"], "label": "PP", "source": "pivot"},
        {"level": pivots["s1"], "label": "S1", "source": "pivot"},
        {"level": pivots["s2"], "label": "S2", "source": "pivot"},
        {"level": pivots["s3"], "label": "S3", "source": "pivot"},
        {"level": vp["poc"], "label": "POC", "source": "volume_profile"},
        {"level": vp["value_area_high"], "label": "VAH", "source": "volume_profile"},
        {"level": vp["value_area_low"], "label": "VAL", "source": "volume_profile"},
        {"level": vwap_last, "label": "VWAP", "source": "vwap"},
        {"level": prev_week["high"], "label": "prior week high", "source": "prior_week"},
        {"level": prev_week["low"], "label": "prior week low", "source": "prior_week"},
        {"level": options["call_wall"]["strike"], "label": f"call wall (OI {options['call_wall']['call_oi']})", "source": "options"},
        {"level": options["put_wall"]["strike"], "label": f"put wall (OI {options['put_wall']['put_oi']})", "source": "options"},
        {"level": options["max_pain"], "label": "max pain", "source": "options"},
    ]
    for c in sr_clusters:
        raw.append({"level": c["level"], "label": f"swing ({c['strength']}x touched)", "source": "swing"})

    for r in raw:
        r["level"] = round(float(r["level"]), 2)
        r["distance_pct"] = round((r["level"] - spot) / spot * 100, 2)

    resistances = sorted([r for r in raw if r["level"] > spot], key=lambda r: r["level"])
    supports = sorted([r for r in raw if r["level"] < spot], key=lambda r: -r["level"])

    def merge_zones(levels_sorted_by_distance):
        """Collapse entries within zone_tol_pct of each other into one zone
        -- a resistance that is simultaneously R1, the VAH and a 3x swing
        touch is a much stronger level than any one of those alone, and
        that only shows up if they're merged rather than listed separately."""
        zones = []
        for r in levels_sorted_by_distance:
            if zones and abs(r["level"] - zones[-1]["level_avg"]) / zones[-1]["level_avg"] <= zone_tol_pct:
                z = zones[-1]
                z["members"].append(r)
                z["level_avg"] = sum(m["level"] for m in z["members"]) / len(z["members"])
            else:
                zones.append({"level_avg": r["level"], "members": [r]})
        for z in zones:
            z["level"] = round(z["level_avg"], 2)
            z["labels"] = [m["label"] for m in z["members"]]
            z["distance_pct"] = round((z["level"] - spot) / spot * 100, 2)
            del z["level_avg"]
        return zones

    resistance_zones = merge_zones(resistances)
    support_zones = merge_zones(supports)

    return {
        "spot": spot,
        "resistance_ladder": resistance_zones[:5],
        "support_ladder": support_zones[:5],
        "nearest_resistance": resistance_zones[0] if resistance_zones else None,
        "nearest_support": support_zones[0] if support_zones else None,
    }


def trade_scenarios(spot, ladder):
    """Mechanical risk/reward for a long using the nearest support as the
    stop and nearest resistance as the target, and the mirror for a short --
    not a directional call, just what the math says IF that trade is taken
    at the current price. Both scenarios are always returned; which one (if
    either) applies is for the trader to decide."""
    res_ladder, sup_ladder = ladder["resistance_ladder"], ladder["support_ladder"]
    ns = sup_ladder[0] if sup_ladder else None
    nr = res_ladder[0] if res_ladder else None
    ns2 = sup_ladder[1] if len(sup_ladder) > 1 else None
    nr2 = res_ladder[1] if len(res_ladder) > 1 else None

    def leg(entry, stop_zone, target_zone, target2_zone):
        if not stop_zone:
            return None
        risk = abs(entry - stop_zone["level"])
        d = {"entry": entry, "stop": stop_zone["level"], "stop_label": "/".join(stop_zone["labels"]),
             "risk": round(risk, 2)}
        if target_zone and risk > 0:
            reward = abs(target_zone["level"] - entry)
            d.update({"target": target_zone["level"], "target_label": "/".join(target_zone["labels"]),
                       "reward": round(reward, 2), "rr_ratio": round(reward / risk, 2)})
        if target2_zone and risk > 0:
            reward2 = abs(target2_zone["level"] - entry)
            d.update({"target_2": target2_zone["level"], "target_2_label": "/".join(target2_zone["labels"]),
                       "reward_2": round(reward2, 2), "rr_ratio_2": round(reward2 / risk, 2)})
        return d

    out = {}
    if ns is not None:
        out["if_long"] = leg(spot, ns, nr, nr2)
    if nr is not None:
        out["if_short"] = leg(spot, nr, ns, ns2)
    return out


def plot_trade_levels(spot, ladder, ticker, outdir):
    """A single vertical price ladder: spot in the middle, every resistance
    zone above it and support zone below, labeled with source and distance.
    This is the "what's actually next, and what agrees with it" chart that
    the other five don't draw directly -- they each show one lens (pivots,
    volume, options, ...) on its own timeframe; this collapses all of them
    onto one line relative to where price is right now."""
    res = list(reversed(ladder["resistance_ladder"]))
    sup = ladder["support_ladder"]
    all_levels = [z["level"] for z in res + sup] + [spot]
    lo, hi = min(all_levels), max(all_levels)
    pad = (hi - lo) * 0.08 or 1.0

    fig, ax = plt.subplots(figsize=(8, 9))
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(0, 1)
    ax.axis("off")

    def strength_style(z):
        n = len(z["members"])
        return (1.6 + 0.35 * n, 0.25 + min(0.55, 0.12 * n))

    for z in res:
        lw, alpha = strength_style(z)
        ax.axhline(z["level"], color="#d1453b", linewidth=lw, alpha=alpha, xmax=0.62)
        ax.text(0.65, z["level"], f"{z['level']:.2f}  ({z['distance_pct']:+.1f}%)\n{', '.join(z['labels'])}",
                va="center", fontsize=8.5, color="#a02c26")

    for z in sup:
        lw, alpha = strength_style(z)
        ax.axhline(z["level"], color="#1a9e5c", linewidth=lw, alpha=alpha, xmax=0.62)
        ax.text(0.65, z["level"], f"{z['level']:.2f}  ({z['distance_pct']:+.1f}%)\n{', '.join(z['labels'])}",
                va="center", fontsize=8.5, color="#12734a")

    ax.axhline(spot, color="black", linewidth=2.2, xmax=0.62)
    ax.plot([0.05], [spot], marker=">", color="black", markersize=10)
    ax.text(0.08, spot, f"  SPOT {spot:.2f}", va="center", fontsize=10.5, fontweight="bold",
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))

    ax.set_title(f"{ticker} - trade level ladder (line weight = how many sources agree)", fontsize=11)
    fig.tight_layout()
    path = os.path.join(outdir, "06_trade_levels.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    return path, fig


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


def plot_relative_strength(df_t, df_b, ticker, bench, beta, corr, outdir,
                            smooth_window=3, div_window=6, div_bench_floor=0.15, div_stock_flat=0.07):
    """Beta-adjusted relative strength, intraday, continuous through the
    session -- not a single end-of-window number.

    Noise handling:
      - Bars with zero volume on either side (halts, stale prints, a data
        hiccup) are dropped before anything is computed, so a flat artifact
        can't masquerade as "the stock held."
      - Every session is re-based to 0 at ITS OWN open and plotted on a
        positional x-axis with a hard break at each session boundary, so
        non-trading hours (overnight, weekend) never draw as a sloped line
        or get treated as a real move.
      - alpha(t) = stock_cum_pct(t) - beta * bench_cum_pct(t): the excess
        return net of what the stock's own beta to the benchmark would
        predict, not the raw spread (a 1.8-beta name is SUPPOSED to move
        more than the index in both directions -- alpha asks whether it
        moved more than THAT).
      - The drawn alpha line is lightly smoothed (`smooth_window` bars,
        rolling median) purely to stop single-bar bid/ask bounce from
        reading as a signal on the chart. The divergence SCAN below uses a
        separate, longer `div_window` (default 6 bars / 30 min) with its own
        floors -- a shorter window with tight floors flags a dozen-plus
        one-bar flickers a day, which is exactly the noise this is supposed
        to filter out; 30 minutes with real-move floors reliably surfaces
        only sustained decoupling.

    Returns the path, figure, beta-adjusted alpha's current value, the
    fraction of the (combined) session spent with positive alpha, and the
    list of explicit divergence windows (see detect_divergence_windows).
    """
    joined = pd.DataFrame({"t": df_t["Close"], "b": df_b["Close"], "tv": df_t["Volume"], "bv": df_b["Volume"]}).dropna()
    joined = joined[(joined["tv"] > 0) & (joined["bv"] > 0)]  # drop halted/stale bars
    day = joined.index.date

    t_pct = session_rebased_pct(joined.rename(columns={"t": "Close"}), day)
    b_pct = session_rebased_pct(joined.rename(columns={"b": "Close"}), day)
    alpha_raw = t_pct - beta * b_pct
    alpha_smooth = alpha_raw.rolling(smooth_window, min_periods=1, center=True).median()

    x = np.arange(len(joined))
    session_start = np.array([d != day[i - 1] if i > 0 else False for i, d in enumerate(day)])
    bounds = [0] + list(np.where(session_start)[0]) + [len(x)]

    windows = detect_divergence_windows(
        list(joined.index), t_pct.values, b_pct.values,
        window=div_window, bench_floor=div_bench_floor, stock_flat=div_stock_flat,
    )

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1.4]}
    )

    band_color = {"against": "#3a86ff", "held": "#f4a300"}
    band_label = {"against": "against tape", "held": "held flat"}
    for w in windows:
        a = max(w["start_idx"], 0)
        b = min(w["end_idx"] + 1, len(x))
        for ax in (ax1, ax2):
            ax.axvspan(a, b, color=band_color[w["class"]], alpha=0.16, linewidth=0)
        t0 = pd.Timestamp(w["start_time"]).strftime("%H:%M")
        ax1.text(
            (a + b) / 2, 0.98, f"{band_label[w['class']]}\n{t0}",
            transform=ax1.get_xaxis_transform(), ha="center", va="top",
            fontsize=7, color=band_color[w["class"]], fontweight="bold",
        )

    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        ax1.plot(x[a:b], t_pct.values[a:b], color="#0057d8", linewidth=1.3,
                  label=f"{ticker} % chg" if i == 0 else None)
        ax1.plot(x[a:b], b_pct.values[a:b], color="#9a9a9a", linewidth=1.1,
                  label=f"{bench} % chg" if i == 0 else None)
        av = alpha_smooth.values[a:b]
        xv = x[a:b]
        ax2.fill_between(xv, av, 0, where=(av >= 0), color="#1a9e5c", alpha=0.65)
        ax2.fill_between(xv, av, 0, where=(av < 0), color="#d1453b", alpha=0.65)
        ax2.plot(xv, alpha_raw.values[a:b], color="#00000033", linewidth=0.6)
    for b in bounds[1:-1]:
        ax1.axvline(b, color="#cccccc", linewidth=0.8, linestyle=":")
        ax2.axvline(b, color="#cccccc", linewidth=0.8, linestyle=":")

    ax1.axhline(0, color="black", linewidth=0.6)
    ax1.legend(fontsize=8, loc="upper left")
    ax1.set_title(
        f"{ticker} vs {bench} - normalized intraday % move, rebased each session "
        f"(60d beta={beta:.2f}, corr={corr:.2f})"
    )
    ax2.axhline(0, color="black", linewidth=0.6)
    ax2.set_title(
        f"Beta-adjusted alpha ({ticker} - {beta:.2f}×{bench}), pp — "
        f"blue = moved against the tape, amber = held flat through a real index move",
        fontsize=8.5,
    )

    tick_idx = np.linspace(0, len(x) - 1, min(10, len(x))).astype(int)
    ax2.set_xticks(tick_idx)
    ax2.set_xticklabels([joined.index[i].strftime("%m-%d %H:%M") for i in tick_idx], rotation=45, ha="right")
    fig.tight_layout()
    path = os.path.join(outdir, "05_relative_strength.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")

    pct_positive = float((alpha_smooth > 0).mean() * 100)
    return path, fig, float(alpha_smooth.iloc[-1]), pct_positive, windows


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
    ap.add_argument("--bench-daily", required=True, help="IBKR ONE_DAY bars JSON for the benchmark (used to fit beta)")
    ap.add_argument("--beta-lookback", type=int, default=60, help="Trading days used to fit beta (default 60)")
    ap.add_argument("--options", required=True, help="options_oi.json (see SKILL.md schema)")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    daily = load_bars_df(args.daily)
    hourly = load_bars_df(args.hourly)
    intraday = load_bars_df(args.intraday)
    bench_intraday = load_bars_df(args.bench_intraday)
    bench_daily = load_bars_df(args.bench_daily)
    opt = load_options(args.options)

    beta, beta_corr, beta_n = compute_beta(daily, bench_daily, lookback=args.beta_lookback)

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
    p5, f5, alpha_now, pct_time_positive, divergence_windows = plot_relative_strength(
        intraday, bench_intraday, args.ticker, args.benchmark, beta, beta_corr, args.outdir
    )

    # --- trade plan: every level found above, collapsed into one ladder ---
    ladder = build_level_ladder(
        spot, pivots, sr_clusters,
        {"poc": poc, "value_area_high": vah, "value_area_low": val},
        {"high": prev_week_hi, "low": prev_week_lo},
        float(vwap.iloc[-1]),
        {"call_wall": call_wall, "put_wall": put_wall, "max_pain": mp_strike},
    )
    scenarios = trade_scenarios(spot, ladder)
    p6, f6 = plot_trade_levels(spot, ladder, args.ticker, args.outdir)

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
        "relative_strength": {
            "benchmark": args.benchmark,
            "beta": round(beta, 2),
            "beta_correlation": round(beta_corr, 2),
            "beta_lookback_days": beta_n,
            "alpha_now_pp": round(alpha_now, 2),
            "pct_session_alpha_positive": round(pct_time_positive, 1),
            "divergence_windows": divergence_windows,
        },
        "trade_plan": {
            "spot": spot,
            "resistance_ladder": ladder["resistance_ladder"],
            "support_ladder": ladder["support_ladder"],
            "scenarios": scenarios,
        },
        "charts": [os.path.basename(p) for p in [p1, p2, p3, p4, p5, p6]],
    }

    with open(os.path.join(args.outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # --- self-contained HTML report ---
    imgs_b64 = {os.path.basename(p): fig_to_b64(fig) for p, fig in [(p1, f1), (p2, f2), (p3, f3), (p4, f4), (p5, f5), (p6, f6)]}
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
    rs = summary["relative_strength"]
    tp = summary["trade_plan"]

    rows = "".join(
        f"<tr><td>{c['level']:.2f}</td><td>{c['strength']}</td></tr>"
        for c in summary["swing_sr_clusters"]
    )

    against = [w for w in rs["divergence_windows"] if w["class"] == "against"]
    held = [w for w in rs["divergence_windows"] if w["class"] == "held"]
    if against or held:
        def fmt_w(w):
            t0 = w["start_time"][11:16]
            t1 = w["end_time"][11:16]
            return f"{t0}–{t1} (מניה {w['stock_move_pp']:+.2f} / בנצ'מרק {w['bench_move_pp']:+.2f})"
        parts = []
        if against:
            parts.append("נגד המגמה: " + "; ".join(fmt_w(w) for w in against))
        if held:
            parts.append("החזיקה ברמה: " + "; ".join(fmt_w(w) for w in held))
        div_summary = " &middot; ".join(parts)
    else:
        div_summary = "לא זוהו חלונות סטייה משמעותיים מהמדד היום (מעבר לרעש)."

    def ladder_rows(zones, color):
        return "".join(
            f"<tr><td class='val' style='color:{color}'>{z['level']:.2f}</td>"
            f"<td class='val'>{z['distance_pct']:+.1f}%</td>"
            f"<td>{', '.join(z['labels'])}</td></tr>"
            for z in zones
        )
    res_rows = ladder_rows(tp["resistance_ladder"], "#c23b32")
    sup_rows = ladder_rows(tp["support_ladder"], "#1a8f5c")

    sc = tp["scenarios"]
    def scenario_card(title, s, color):
        if not s or "target" not in s:
            return f"<div class='card'><b>{title}</b><br>אין מספיק נתונים לחשב.</div>"
        ext = ""
        if "target_2" in s:
            ext = (f"<br>יעד מורחב (אם נשבר היעד הראשון): <span style='color:#1a8f5c'>{s['target_2']:.2f}</span> "
                   f"({s['target_2_label']}) &middot; יחס סיכוי:סיכון מורחב = <b>{s['rr_ratio_2']:.2f}</b>")
        return (
            f"<div class='card'><b>{title}</b><br>"
            f"כניסה {s['entry']:.2f} &middot; סטופ <span style='color:#c23b32'>{s['stop']:.2f}</span> ({s['stop_label']}) "
            f"&middot; יעד <span style='color:#1a8f5c'>{s['target']:.2f}</span> ({s['target_label']})<br>"
            f"סיכון {s['risk']:.2f} / סיכוי {s['reward']:.2f} &middot; <b>יחס סיכוי:סיכון = {s['rr_ratio']:.2f}</b>"
            f"{ext}"
            f"</div>"
        )
    scenarios_html = scenario_card("אם נכנסים לונג", sc.get("if_long"), "#1a8f5c") + \
        scenario_card("אם נכנסים שורט", sc.get("if_short"), "#c23b32")

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

<h2>5. חוזק יחסי מול {rs['benchmark']} — מתוקנן לבטא</h2>
<p>
  בטא (60 יום, קורלציה {rs['beta_correlation']}): <b>{rs['beta']}</b> &middot;
  אלפא נוכחי: <b>{rs['alpha_now_pp']:+.2f} נק' אחוז</b> &middot;
  אחוז מהזמן היום עם אלפא חיובי: <b>{rs['pct_session_alpha_positive']}%</b>
</p>
<p>{div_summary}</p>
{img('05_relative_strength.png')}

<h2>6. מפת מסחר — תמיכות, התנגדויות ויחס סיכוי:סיכון</h2>
<p>כל הרמות שהמודלים למעלה מצאו (Pivot, סווינג, פרופיל נפח, VWAP, שבוע קודם, מגנטים באופציות), ממוזגות לרשימה אחת ומדורגות לפי מרחק מהמחיר. רמות שכמה מקורות מסכימים עליהן (בטווח 0.6%) מוצגות כאזור אחד — קו עבה יותר בגרף. <b>זו מפת רמות, לא המלצת קנייה/מכירה</b> — התרחישים למטה הם החשבון האריתמטי בהנחה שנכנסים עכשיו, לא קריאת כיוון.</p>
<div class="grid">
  <div class="card"><b>התנגדויות מעל המחיר</b>
    <table><tr><th>רמה</th><th>מרחק</th><th>מקורות</th></tr>{res_rows}</table>
  </div>
  <div class="card"><b>תמיכות מתחת למחיר</b>
    <table><tr><th>רמה</th><th>מרחק</th><th>מקורות</th></tr>{sup_rows}</table>
  </div>
</div>
<div class="grid" style="margin-top:12px">{scenarios_html}</div>
{img('06_trade_levels.png')}

</body></html>"""


if __name__ == "__main__":
    main()
