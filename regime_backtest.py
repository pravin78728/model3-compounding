"""
Regime-Specific Backtest — Bull / Bear / Choppy
================================================
Runs both OBV screeners across 3 clean 3-month regime periods:
  BULL:   Apr-Jun 2025  (+18.8%)
  CHOPPY: Jul-Sep 2025  (-3.7%)
  BEAR:   Jan-Mar 2026  (-14.8%)

For each regime:
  - Runs screeners every Sunday
  - Tracks top 1, 2, and 4 picks per sleeve
  - Measures win rate and returns at each position count
  - Outputs regime-specific criteria for optimal entry

Usage:
    python regime_backtest.py
"""

import os
import numpy as np
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

LOOKBACK      = 20
SMA_PERIOD    = 50
RSI_PERIOD    = 14
RSI_THRESHOLD = 60
RSI_MAX       = 80
VOL_SHORT     = 20
VOL_LONG      = 50
OBV_MIN_PCT   = 5.0
TRAIL_STOP    = 0.10

REGIMES = [
    {
        "name": "BULL",
        "desc": "Apr-Jun 2025 (+18.8%)",
        "weeks": [
            {"signal": "2025-04-06", "start": "2025-04-07", "end": "2025-04-11"},
            {"signal": "2025-04-13", "start": "2025-04-14", "end": "2025-04-17"},
            {"signal": "2025-04-20", "start": "2025-04-21", "end": "2025-04-25"},
            {"signal": "2025-04-27", "start": "2025-04-28", "end": "2025-04-30"},
            {"signal": "2025-05-04", "start": "2025-05-05", "end": "2025-05-09"},
            {"signal": "2025-05-11", "start": "2025-05-12", "end": "2025-05-16"},
            {"signal": "2025-05-18", "start": "2025-05-19", "end": "2025-05-23"},
            {"signal": "2025-05-25", "start": "2025-05-26", "end": "2025-05-30"},
            {"signal": "2025-06-01", "start": "2025-06-02", "end": "2025-06-06"},
            {"signal": "2025-06-08", "start": "2025-06-09", "end": "2025-06-13"},
            {"signal": "2025-06-15", "start": "2025-06-16", "end": "2025-06-20"},
            {"signal": "2025-06-22", "start": "2025-06-23", "end": "2025-06-27"},
        ]
    },
    {
        "name": "CHOPPY",
        "desc": "Jul-Sep 2025 (-3.7%)",
        "weeks": [
            {"signal": "2025-07-06", "start": "2025-07-07", "end": "2025-07-11"},
            {"signal": "2025-07-13", "start": "2025-07-14", "end": "2025-07-18"},
            {"signal": "2025-07-20", "start": "2025-07-21", "end": "2025-07-25"},
            {"signal": "2025-07-27", "start": "2025-07-28", "end": "2025-08-01"},
            {"signal": "2025-08-03", "start": "2025-08-04", "end": "2025-08-08"},
            {"signal": "2025-08-10", "start": "2025-08-11", "end": "2025-08-15"},
            {"signal": "2025-08-17", "start": "2025-08-18", "end": "2025-08-22"},
            {"signal": "2025-08-24", "start": "2025-08-25", "end": "2025-08-29"},
            {"signal": "2025-08-31", "start": "2025-09-01", "end": "2025-09-05"},
            {"signal": "2025-09-07", "start": "2025-09-08", "end": "2025-09-12"},
            {"signal": "2025-09-14", "start": "2025-09-15", "end": "2025-09-19"},
            {"signal": "2025-09-21", "start": "2025-09-22", "end": "2025-09-26"},
        ]
    },
    {
        "name": "BEAR",
        "desc": "Jan-Mar 2026 (-14.8%)",
        "weeks": [
            {"signal": "2026-01-04", "start": "2026-01-05", "end": "2026-01-09"},
            {"signal": "2026-01-11", "start": "2026-01-12", "end": "2026-01-16"},
            {"signal": "2026-01-18", "start": "2026-01-19", "end": "2026-01-23"},
            {"signal": "2026-01-25", "start": "2026-01-26", "end": "2026-01-30"},
            {"signal": "2026-02-01", "start": "2026-02-02", "end": "2026-02-06"},
            {"signal": "2026-02-08", "start": "2026-02-09", "end": "2026-02-13"},
            {"signal": "2026-02-15", "start": "2026-02-16", "end": "2026-02-20"},
            {"signal": "2026-02-22", "start": "2026-02-23", "end": "2026-02-27"},
            {"signal": "2026-03-01", "start": "2026-03-02", "end": "2026-03-06"},
            {"signal": "2026-03-08", "start": "2026-03-09", "end": "2026-03-13"},
            {"signal": "2026-03-15", "start": "2026-03-16", "end": "2026-03-20"},
            {"signal": "2026-03-22", "start": "2026-03-23", "end": "2026-03-27"},
        ]
    }
]


def fetch_week_data(signal_date_str):
    signal_date = pd.to_datetime(signal_date_str)
    start = (signal_date - timedelta(days=400)).strftime("%Y-%m-%d")
    end   = (signal_date + timedelta(days=14)).strftime("%Y-%m-%d")
    engine = get_engine()
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


def compute_obv(df):
    c = df["close_price"].values
    v = df["volume"].values
    o = np.zeros(len(c))
    for i in range(1, len(c)):
        o[i] = o[i-1] + v[i] if c[i] > c[i-1] else o[i-1] - v[i] if c[i] < c[i-1] else o[i-1]
    return pd.Series(o, index=df.index)


def compute_rsi(series, period=14):
    d = series.diff()
    g = d.clip(lower=0).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))


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
        obv_ok = to > obv_high and obv_pct >= OBV_MIN_PCT
        vol_ok = av20 >= av50
        sma_ok = tc > sma50

        if obv_ok and tc <= price_high and vol_ok and sma_ok:
            gap = round((price_high - tc) / tc * 100, 2)
            sleeve1.append({"symbol": symbol, "entry": round(tc, 2),
                           "obv_%": obv_pct, "gap_%": gap, "rsi": round(tr, 1),
                           "resistance": round(price_high, 2),
                           "pct_above_sma": round((tc/sma50-1)*100, 1)})

        if obv_ok and tc > price_high and vol_ok and sma_ok and RSI_THRESHOLD <= tr < RSI_MAX:
            brk = round((tc - price_high) / price_high * 100, 2)
            sleeve2.append({"symbol": symbol, "entry": round(tc, 2),
                           "obv_%": obv_pct, "break_%": brk, "rsi": round(tr, 1),
                           "stop": round(tc * (1 - TRAIL_STOP), 2),
                           "pct_above_sma": round((tc/sma50-1)*100, 1)})

    s1 = pd.DataFrame(sleeve1).sort_values("obv_%", ascending=False).reset_index(drop=True) if sleeve1 else pd.DataFrame()
    s2 = pd.DataFrame(sleeve2).sort_values("obv_%", ascending=False).reset_index(drop=True) if sleeve2 else pd.DataFrame()
    return s1, s2


def track_signals(signals, symbol_data, track_start, track_end, sleeve, top_n):
    if signals.empty or len(signals) == 0:
        return pd.DataFrame()
    picks = signals.head(top_n)
    t_start = pd.to_datetime(track_start)
    t_end   = pd.to_datetime(track_end)
    results = []

    for _, row in picks.iterrows():
        symbol = row["symbol"]
        entry  = row["entry"]
        stop   = row.get("stop", entry * (1 - TRAIL_STOP))
        if symbol not in symbol_data:
            continue
        df   = symbol_data[symbol]
        week = df[(df["date"] >= t_start) & (df["date"] <= t_end)].copy()
        if week.empty:
            continue
        closes    = week["close_price"].values
        peak      = entry
        stop_hit  = False
        exit_close = closes[-1]
        broke_res  = False

        if sleeve == 1:
            broke_res = any(c > row.get("resistance", entry) for c in closes)

        for i, c in enumerate(closes):
            if sleeve == 2:
                if c > peak:
                    peak = c
                    stop = peak * (1 - TRAIL_STOP)
                if c < stop:
                    stop_hit   = True
                    exit_close = c
                    break

        final_ret = round((float(exit_close) - entry) / entry * 100, 2)
        max_gain  = round((max(closes) - entry) / entry * 100, 2)
        max_dd    = round((min(closes) - entry) / entry * 100, 2)

        r = {
            "symbol": symbol, "entry": entry,
            "obv_%": row["obv_%"], "rsi": row["rsi"],
            "pct_above_sma": row.get("pct_above_sma", 0),
            "final_ret_%": final_ret, "max_gain_%": max_gain,
            "max_dd_%": max_dd, "winner": 1 if final_ret > 0 else 0,
        }
        if sleeve == 1:
            r["gap_%"]     = row["gap_%"]
            r["broke_res"] = 1 if broke_res else 0
        if sleeve == 2:
            r["break_%"]  = row.get("break_%", 0)
            r["stop_hit"] = 1 if stop_hit else 0
        results.append(r)

    return pd.DataFrame(results)


def analyze_regime(regime_name, all_trades_s1, all_trades_s2):
    """Analyze what filters give best win rates within a regime."""
    print(f"\n{'─'*60}")
    print(f"  ANALYSIS: {regime_name} REGIME")
    print(f"{'─'*60}")

    for sleeve_name, trades in [("Sleeve 1", all_trades_s1), ("Sleeve 2", all_trades_s2)]:
        if trades.empty:
            continue
        print(f"\n  {sleeve_name} — {len(trades)} trades total")

        # By position count (top 1 vs top 2 vs top 4)
        for n in [1, 2, 4]:
            # Simulate taking only top N per week
            top_n = trades.groupby("week").head(n)
            w = top_n["winner"].sum()
            t = len(top_n)
            r = round(top_n["final_ret_%"].mean(), 2)
            print(f"    Top {n} per week: {w}/{t} = {w/t*100:.1f}% win rate  avg ret {r:+.2f}%")

        # OBV strength filter
        print(f"\n  {sleeve_name} — OBV strength breakdown:")
        for obv_min in [10, 20, 50, 100]:
            filtered = trades[trades["obv_%"] >= obv_min]
            if len(filtered) < 3:
                continue
            w = filtered["winner"].sum()
            t = len(filtered)
            r = round(filtered["final_ret_%"].mean(), 2)
            print(f"    OBV >= {obv_min:>4}%: {w}/{t} = {w/t*100:.1f}% win rate  avg ret {r:+.2f}%  ({t} trades)")

        # RSI range filter
        if sleeve_name == "Sleeve 2":
            print(f"\n  {sleeve_name} — RSI range breakdown:")
            for rsi_min, rsi_max in [(60,65),(65,70),(70,75),(75,80)]:
                filtered = trades[(trades["rsi"] >= rsi_min) & (trades["rsi"] < rsi_max)]
                if len(filtered) < 3:
                    continue
                w = filtered["winner"].sum()
                t = len(filtered)
                r = round(filtered["final_ret_%"].mean(), 2)
                print(f"    RSI {rsi_min}-{rsi_max}: {w}/{t} = {w/t*100:.1f}% win rate  avg ret {r:+.2f}%  ({t} trades)")

        # Gap filter for S1
        if sleeve_name == "Sleeve 1":
            print(f"\n  {sleeve_name} — Gap to resistance breakdown:")
            for gap_max in [1, 2, 3, 5]:
                filtered = trades[trades["gap_%"] <= gap_max]
                if len(filtered) < 3:
                    continue
                w = filtered["winner"].sum()
                t = len(filtered)
                r = round(filtered["final_ret_%"].mean(), 2)
                print(f"    Gap <= {gap_max}%: {w}/{t} = {w/t*100:.1f}% win rate  avg ret {r:+.2f}%  ({t} trades)")


def main():
    print("Regime-Specific Backtest — Bull / Bear / Choppy")
    print("=" * 60)

    all_results = {}

    for regime in REGIMES:
        print(f"\n{'='*60}")
        print(f"Processing {regime['name']} — {regime['desc']}")
        print(f"{'='*60}")

        all_s1, all_s2 = [], []

        for i, week in enumerate(regime["weeks"]):
            print(f"  Week {i+1:2d} ({week['signal']})...", end=" ", flush=True)
            try:
                symbol_data = fetch_week_data(week["signal"])
                s1, s2 = run_screeners(symbol_data, week["signal"])

                # Track top 4 (we'll analyze subsets in post-processing)
                s1_res = track_signals(s1, symbol_data, week["start"], week["end"], sleeve=1, top_n=4)
                s2_res = track_signals(s2, symbol_data, week["start"], week["end"], sleeve=2, top_n=4)

                s1w = s1_res["winner"].sum() if not s1_res.empty else 0
                s2w = s2_res["winner"].sum() if not s2_res.empty else 0
                s1t = len(s1_res); s2t = len(s2_res)
                s1r = round(s1_res["final_ret_%"].mean(), 2) if not s1_res.empty else 0
                s2r = round(s2_res["final_ret_%"].mean(), 2) if not s2_res.empty else 0
                print(f"S1: {s1w}/{s1t} {s1r:+.1f}%  S2: {s2w}/{s2t} {s2r:+.1f}%")

                if not s1_res.empty:
                    s1_res["week"] = f"W{i+1:02d}"
                    s1_res["regime"] = regime["name"]
                    s1_res["sleeve"] = 1
                    all_s1.append(s1_res)
                if not s2_res.empty:
                    s2_res["week"] = f"W{i+1:02d}"
                    s2_res["regime"] = regime["name"]
                    s2_res["sleeve"] = 2
                    all_s2.append(s2_res)

            except Exception as e:
                print(f"ERROR: {e}")

        s1_all = pd.concat(all_s1, ignore_index=True) if all_s1 else pd.DataFrame()
        s2_all = pd.concat(all_s2, ignore_index=True) if all_s2 else pd.DataFrame()
        all_results[regime["name"]] = {"s1": s1_all, "s2": s2_all}

        # Quick summary
        if not s1_all.empty:
            w=s1_all["winner"].sum(); t=len(s1_all)
            print(f"\n  S1 total: {w}/{t} = {w/t*100:.1f}%  avg {s1_all['final_ret_%'].mean():+.2f}%")
        if not s2_all.empty:
            w=s2_all["winner"].sum(); t=len(s2_all)
            print(f"  S2 total: {w}/{t} = {w/t*100:.1f}%  avg {s2_all['final_ret_%'].mean():+.2f}%")

        # Save checkpoint
        combined = pd.concat([s1_all, s2_all], ignore_index=True) if (not s1_all.empty or not s2_all.empty) else pd.DataFrame()
        if not combined.empty:
            fname = f"regime_backtest_{regime['name'].lower()}.csv"
            combined.to_csv(fname, index=False)
            print(f"  Saved: {fname}")

    # ── Deep analysis per regime ──────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("REGIME-SPECIFIC OPTIMAL CRITERIA")
    print(f"{'='*60}")

    for regime_name, data in all_results.items():
        analyze_regime(regime_name, data["s1"], data["s2"])

    # ── Cross-regime summary table ────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("FINAL CRITERIA TABLE — WHAT TO USE IN EACH REGIME")
    print(f"{'='*60}")
    print(f"\n{'Regime':<10} {'Sleeve':<10} {'Top N':<8} {'OBV min':<10} {'Win Rate':<12} {'Avg Ret'}")
    print("-"*58)

    for regime_name, data in all_results.items():
        for sleeve_name, trades in [("S1", data["s1"]), ("S2", data["s2"])]:
            if trades.empty:
                continue
            best_rate = 0
            best_config = ""
            # Find best combination
            for n in [1, 2]:
                for obv_min in [5, 20, 50]:
                    subset = trades[trades["obv_%"] >= obv_min].groupby("week").head(n)
                    if len(subset) < 5:
                        continue
                    w = subset["winner"].sum()
                    t = len(subset)
                    rate = w/t*100
                    ret = subset["final_ret_%"].mean()
                    if rate > best_rate:
                        best_rate = rate
                        best_n = n
                        best_obv = obv_min
                        best_ret = ret
                        best_t = t
            if best_rate > 0:
                print(f"{regime_name:<10} {sleeve_name:<10} Top {best_n:<5} OBV>={best_obv}%{'':<4} {best_rate:.1f}% ({best_t} trades){'':<2} {best_ret:+.2f}%")

    print("\nDone.")


if __name__ == "__main__":
    main()
