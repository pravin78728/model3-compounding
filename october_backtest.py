"""
October 2026 Backtest — Model 2 Sleeves 1 & 2
===============================================
Runs both OBV screeners on each Sunday of October 2026,
takes top 4 signals per sleeve per week, tracks performance
Monday through Friday of that week.

Signal dates (Sundays): Oct 4, Oct 11, Oct 18, Oct 25
Tracking periods:
  Week 1: Oct 5-9
  Week 2: Oct 12-16
  Week 3: Oct 19-23
  Week 4: Oct 26-30

Usage:
    python october_backtest.py
"""

import os
import numpy as np
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

# ── Parameters ────────────────────────────────────────────────────────────────
LOOKBACK      = 20
SMA_PERIOD    = 50
RSI_PERIOD    = 14
RSI_THRESHOLD = 60
RSI_MAX       = 80
VOL_SHORT     = 20
VOL_LONG      = 50
OBV_MIN_PCT   = 5.0
TRAIL_STOP    = 0.10
TOP_N         = 4   # top signals to track per sleeve per week

# ── 4 weekly signal dates (Sundays in October) ───────────────────────────────
WEEKS = [
    {"signal_date": "2026-10-04", "track_start": "2026-10-05", "track_end": "2026-10-09", "label": "Week 1 (Oct 5-9)"},
    {"signal_date": "2026-10-11", "track_start": "2026-10-12", "track_end": "2026-10-16", "label": "Week 2 (Oct 12-16)"},
    {"signal_date": "2026-10-18", "track_start": "2026-10-19", "track_end": "2026-10-23", "label": "Week 3 (Oct 19-23)"},
    {"signal_date": "2026-10-25", "track_start": "2026-10-26", "track_end": "2026-10-30", "label": "Week 4 (Oct 26-30)"},
]


# ── Fetch data for one week ───────────────────────────────────────────────────
def fetch_week_data(signal_date_str):
    signal_date = pd.to_datetime(signal_date_str)
    start = (signal_date - timedelta(days=400)).strftime("%Y-%m-%d")
    end   = (signal_date + timedelta(days=14)).strftime("%Y-%m-%d")

    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT symbol, date, close_price, volume
            FROM prices
            WHERE date BETWEEN :start AND :end
            AND symbol IN (
                SELECT DISTINCT symbol FROM prices
                WHERE date BETWEEN :sig_start AND :sig_end
                AND volume IS NOT NULL
            )
            ORDER BY symbol, date ASC
        """), conn, params={
            "start": start, "end": end,
            "sig_start": (signal_date - timedelta(days=5)).strftime("%Y-%m-%d"),
            "sig_end":   (signal_date + timedelta(days=5)).strftime("%Y-%m-%d"),
        })

    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce")
    df = df.dropna(subset=["close_price"])
    df["volume"] = df.groupby("symbol")["volume"].transform(
        lambda x: x.ffill().fillna(0))

    return {sym: grp.reset_index(drop=True) for sym, grp in df.groupby("symbol")}


# ── OBV ───────────────────────────────────────────────────────────────────────
def compute_obv(df):
    c = df["close_price"].values
    v = df["volume"].values
    o = np.zeros(len(c))
    for i in range(1, len(c)):
        o[i] = o[i-1] + v[i] if c[i] > c[i-1] else o[i-1] - v[i] if c[i] < c[i-1] else o[i-1]
    return pd.Series(o, index=df.index)


# ── RSI ───────────────────────────────────────────────────────────────────────
def compute_rsi(series, period=14):
    d = series.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))


# ── Run screeners on signal date ──────────────────────────────────────────────
def run_screeners(symbol_data, signal_date_str):
    signal_date = pd.to_datetime(signal_date_str)
    sleeve1, sleeve2 = [], []

    for symbol, df in symbol_data.items():
        hist = df[df["date"] <= signal_date].copy().reset_index(drop=True)
        if len(hist) < max(SMA_PERIOD, VOL_LONG, RSI_PERIOD + 10):
            continue

        hist["obv"] = compute_obv(hist)
        hist["rsi"] = compute_rsi(hist["close_price"])

        tc = hist["close_price"].iloc[-1]
        to = hist["obv"].iloc[-1]
        tr = hist["rsi"].iloc[-1]
        td = hist["date"].iloc[-1]

        if pd.isna(tr) or abs((td - signal_date).days) > 5:
            continue

        prior_o = hist["obv"].iloc[-(LOOKBACK+1):-1]
        prior_c = hist["close_price"].iloc[-(LOOKBACK+1):-1]
        if len(prior_o) < LOOKBACK:
            continue

        obv_high   = prior_o.max()
        price_high = prior_c.max()
        av20       = hist["volume"].iloc[-VOL_SHORT:].mean()
        av50       = hist["volume"].iloc[-VOL_LONG:].mean()
        sma50      = hist["close_price"].iloc[-SMA_PERIOD:].mean()
        obv_pct    = round((to - obv_high) / abs(obv_high) * 100 if obv_high != 0 else 0, 1)

        obv_ok  = to > obv_high and obv_pct >= OBV_MIN_PCT
        vol_ok  = av20 >= av50
        sma_ok  = tc > sma50

        # Sleeve 1: OBV up, price NOT broken
        if obv_ok and tc <= price_high and vol_ok and sma_ok:
            gap = round((price_high - tc) / tc * 100, 2)
            sleeve1.append({"symbol": symbol, "entry": round(tc, 2),
                           "obv_%": obv_pct, "gap_%": gap, "rsi": round(tr, 1),
                           "resistance": round(price_high, 2)})

        # Sleeve 2: OBV up, price BROKE out, RSI 60-80
        if obv_ok and tc > price_high and vol_ok and sma_ok and RSI_THRESHOLD <= tr < RSI_MAX:
            brk = round((tc - price_high) / price_high * 100, 2)
            sleeve2.append({"symbol": symbol, "entry": round(tc, 2),
                           "obv_%": obv_pct, "break_%": brk, "rsi": round(tr, 1),
                           "stop": round(tc * (1 - TRAIL_STOP), 2)})

    s1 = pd.DataFrame(sleeve1).sort_values("obv_%", ascending=False).head(TOP_N).reset_index(drop=True) if sleeve1 else pd.DataFrame()
    s2 = pd.DataFrame(sleeve2).sort_values("obv_%", ascending=False).head(TOP_N).reset_index(drop=True) if sleeve2 else pd.DataFrame()
    return s1, s2


# ── Track performance ─────────────────────────────────────────────────────────
def track_performance(signals, symbol_data, signal_date_str, track_start, track_end, sleeve):
    if signals.empty:
        return pd.DataFrame()

    signal_date = pd.to_datetime(signal_date_str)
    t_start     = pd.to_datetime(track_start)
    t_end       = pd.to_datetime(track_end)
    results     = []

    for _, row in signals.iterrows():
        symbol = row["symbol"]
        entry  = row["entry"]
        stop   = row.get("stop", entry * (1 - TRAIL_STOP))

        if symbol not in symbol_data:
            continue

        df = symbol_data[symbol]
        week = df[(df["date"] >= t_start) & (df["date"] <= t_end)].copy()

        if week.empty:
            continue

        closes     = week["close_price"].values
        dates      = week["date"].values
        peak       = entry
        stop_hit   = False
        exit_close = closes[-1]
        exit_date  = dates[-1]

        # For Sleeve 1: did price break resistance?
        broke_resistance = False
        if sleeve == 1:
            resistance = row.get("resistance", entry)
            broke_resistance = any(c > resistance for c in closes)

        for i, c in enumerate(closes):
            if sleeve == 2:
                if c > peak:
                    peak = c
                    stop = peak * (1 - TRAIL_STOP)
                if c < stop:
                    stop_hit   = True
                    exit_close = c
                    exit_date  = dates[i]
                    break

        max_gain = round((max(closes) - entry) / entry * 100, 2)
        max_dd   = round((min(closes) - entry) / entry * 100, 2)
        final_ret = round((exit_close - entry) / entry * 100, 2)

        r = {
            "symbol":     symbol,
            "entry":      entry,
            "exit_close": round(float(exit_close), 2),
            "exit_date":  pd.to_datetime(exit_date).strftime("%Y-%m-%d"),
            "max_gain_%": max_gain,
            "max_dd_%":   max_dd,
            "final_ret_%": final_ret,
        }
        if sleeve == 1:
            r["obv_%"]          = row["obv_%"]
            r["gap_%"]          = row["gap_%"]
            r["broke_res"]      = "YES" if broke_resistance else "NO"
        if sleeve == 2:
            r["obv_%"]          = row["obv_%"]
            r["stop_hit"]       = "YES" if stop_hit else "NO"
            r["peak_close"]     = round(float(peak), 2)

        results.append(r)

    return pd.DataFrame(results)


# ── Print weekly summary ──────────────────────────────────────────────────────
def print_week(week, s1_signals, s2_signals, s1_results, s2_results):
    print(f"\n{'='*65}")
    print(f"  {week['label']}  |  Signal date: {week['signal_date']}")
    print(f"{'='*65}")

    # Sleeve 1
    print(f"\n  SLEEVE 1 — Pre-Breakout ({len(s1_signals)} signals, tracking top {len(s1_results)})")
    print(f"  {'─'*55}")
    if s1_results.empty:
        print("  No results.")
    else:
        broke = (s1_results["broke_res"] == "YES").sum()
        avg_ret = round(s1_results["final_ret_%"].mean(), 2)
        avg_gain = round(s1_results["max_gain_%"].mean(), 2)
        print(f"  Broke resistance: {broke}/{len(s1_results)} | Avg return: {avg_ret}% | Avg max gain: {avg_gain}%\n")
        for _, r in s1_results.iterrows():
            ret_emoji = "✅" if r["final_ret_%"] > 0 else "❌"
            print(f"  {ret_emoji} {r['symbol']:<14} Entry ₹{r['entry']} | "
                  f"Broke: {r['broke_res']} | Max gain: {r['max_gain_%']}% | "
                  f"Return: {r['final_ret_%']}% | Max DD: {r['max_dd_%']}%")

    # Sleeve 2
    print(f"\n  SLEEVE 2 — Confirmed Momentum ({len(s2_signals)} signals, tracking top {len(s2_results)})")
    print(f"  {'─'*55}")
    if s2_results.empty:
        print("  No results.")
    else:
        stopped = (s2_results["stop_hit"] == "YES").sum()
        avg_ret = round(s2_results["final_ret_%"].mean(), 2)
        avg_gain = round(s2_results["max_gain_%"].mean(), 2)
        print(f"  Stop hit: {stopped}/{len(s2_results)} | Avg return: {avg_ret}% | Avg max gain: {avg_gain}%\n")
        for _, r in s2_results.iterrows():
            ret_emoji = "✅" if r["final_ret_%"] > 0 else "❌"
            print(f"  {ret_emoji} {r['symbol']:<14} Entry ₹{r['entry']} | "
                  f"Stop hit: {r['stop_hit']} | Peak: ₹{r['peak_close']} | "
                  f"Return: {r['final_ret_%']}% | Max DD: {r['max_dd_%']}%")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("October 2026 Backtest — Model 2 Sleeves 1 & 2")
    print("=" * 65)
    print(f"Signal logic: OBV > {OBV_MIN_PCT}%, RSI {RSI_THRESHOLD}-{RSI_MAX}, Vol rising, Above SMA50")
    print(f"Tracking: top {TOP_N} signals per sleeve per week, Mon-Fri performance")

    all_s1, all_s2 = [], []

    for week in WEEKS:
        print(f"\nFetching data for {week['label']}...")
        symbol_data = fetch_week_data(week["signal_date"])
        print(f"  Loaded {len(symbol_data)} symbols.")

        s1, s2 = run_screeners(symbol_data, week["signal_date"])
        print(f"  Sleeve 1: {len(s1)} signals | Sleeve 2: {len(s2)} signals")

        s1_res = track_performance(s1, symbol_data, week["signal_date"],
                                   week["track_start"], week["track_end"], sleeve=1)
        s2_res = track_performance(s2, symbol_data, week["signal_date"],
                                   week["track_start"], week["track_end"], sleeve=2)

        print_week(week, s1, s2, s1_res, s2_res)

        if not s1_res.empty:
            s1_res["week"] = week["label"]
            all_s1.append(s1_res)
        if not s2_res.empty:
            s2_res["week"] = week["label"]
            all_s2.append(s2_res)

    # ── Overall summary ──
    print(f"\n\n{'='*65}")
    print("  OCTOBER 2026 — OVERALL SUMMARY")
    print(f"{'='*65}")

    if all_s1:
        s1_all = pd.concat(all_s1)
        broke  = (s1_all["broke_res"] == "YES").sum()
        print(f"\n  SLEEVE 1 — {len(s1_all)} total trades")
        print(f"  Resistance broken:  {broke}/{len(s1_all)} ({round(broke/len(s1_all)*100,1)}%)")
        print(f"  Avg final return:   {round(s1_all['final_ret_%'].mean(),2)}%")
        print(f"  Avg max gain:       {round(s1_all['max_gain_%'].mean(),2)}%")
        print(f"  Avg max drawdown:   {round(s1_all['max_dd_%'].mean(),2)}%")
        winners = (s1_all["final_ret_%"] > 0).sum()
        print(f"  Win rate (>0%):     {winners}/{len(s1_all)} ({round(winners/len(s1_all)*100,1)}%)")

    if all_s2:
        s2_all = pd.concat(all_s2)
        stopped = (s2_all["stop_hit"] == "YES").sum()
        print(f"\n  SLEEVE 2 — {len(s2_all)} total trades")
        print(f"  Stops hit:          {stopped}/{len(s2_all)} ({round(stopped/len(s2_all)*100,1)}%)")
        print(f"  Avg final return:   {round(s2_all['final_ret_%'].mean(),2)}%")
        print(f"  Avg max gain:       {round(s2_all['max_gain_%'].mean(),2)}%")
        print(f"  Avg max drawdown:   {round(s2_all['max_dd_%'].mean(),2)}%")
        winners = (s2_all["final_ret_%"] > 0).sum()
        print(f"  Win rate (>0%):     {winners}/{len(s2_all)} ({round(winners/len(s2_all)*100,1)}%)")

    # Save
    if all_s1 or all_s2:
        all_trades = pd.concat(all_s1 + all_s2, ignore_index=True)
        all_trades.to_csv("october_backtest_results.csv", index=False)
        print(f"\nSaved: october_backtest_results.csv")

    print("\nDone.")


if __name__ == "__main__":
    main()
