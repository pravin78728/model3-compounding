"""
Extended Analysis — Sleeve 2 Return Optimization
=================================================
1. Re-runs Sleeve 2 tracking with 3-week holding window
2. Finds best return combinations for both 1-week and 3-week windows
Uses existing extended_regime_results.csv trade log.

Usage:
    python analyze_extended.py
"""

import os
import numpy as np
import pandas as pd
from datetime import timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

TRAIL_STOP = 0.10

# ── Load existing trade log ───────────────────────────────────────────────────
def load_trades():
    path = "extended_regime_results.csv"
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found. Run extended_regime_backtest.py first.")
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} trades from {path}")
    print(f"Regimes: {df['regime'].value_counts().to_dict()}")
    print(f"Sleeves: {df['sleeve'].value_counts().to_dict()}")
    return df

# ── Fetch 3-week forward prices for S2 trades ────────────────────────────────
def fetch_forward_prices(trades_df):
    """
    For each S2 trade, fetch 15 trading days of forward prices.
    Returns dict: {(symbol, period, week): [closes]}
    """
    # Get unique symbol+period+week combinations from S2
    s2 = trades_df[trades_df["sleeve"] == 2].copy()
    
    # We need to map period+week back to actual dates
    # Build period date map
    PERIOD_STARTS = {
        ("BULL","Q2-2023"): "2023-04-01",
        ("BULL","Q3-2023"): "2023-07-01",
        ("BULL","Q4-2023"): "2023-10-01",
        ("BULL","Q2-2024"): "2024-04-01",
        ("BULL","Q2-2025"): "2025-04-06",
        ("CHOPPY","Q1-2022"): "2022-01-03",
        ("CHOPPY","Q4-2022"): "2022-10-01",
        ("CHOPPY","Q1-2024"): "2024-01-01",
        ("CHOPPY","Q3-2025"): "2025-07-06",
        ("CHOPPY","Q3-2026"): "2026-07-06",
        ("BEAR","Q2-2022"): "2022-04-01",
        ("BEAR","Q1-2023"): "2023-01-01",
        ("BEAR","Q4-2024"): "2024-10-01",
        ("BEAR","Q1-2025"): "2025-01-01",
        ("BEAR","Q1-2026"): "2026-01-05",
    }

    # Collect all symbols and date ranges needed
    queries = []
    for _, row in s2.iterrows():
        period_start = pd.to_datetime(PERIOD_STARTS.get((row["regime"], row["period"]), "2023-01-01"))
        week_num = int(row["week"][1:])  # W01 -> 1
        # Signal date is approximately week_num Sundays from period start
        signal_date = period_start + timedelta(days=(week_num-1)*7)
        # Find nearest Sunday
        days_to_sunday = (6 - signal_date.weekday()) % 7
        signal_date = signal_date + timedelta(days=days_to_sunday)
        track_start  = signal_date + timedelta(days=1)
        track_end_3w = signal_date + timedelta(days=22)  # ~3 weeks
        queries.append({
            "symbol": row["symbol"],
            "regime": row["regime"],
            "period": row["period"],
            "week":   row["week"],
            "entry":  row["entry"],
            "rsi":    row["rsi"],
            "obv_%":  row["obv_%"],
            "break_%": row.get("break_%", 0),
            "track_start": track_start.strftime("%Y-%m-%d"),
            "track_end_3w": track_end_3w.strftime("%Y-%m-%d"),
        })

    print(f"\nFetching 3-week forward prices for {len(queries)} S2 trades...")

    # Batch fetch by period to minimize DB calls
    results = []
    engine = get_engine()

    # Group by period for efficient fetching
    period_groups = {}
    for q in queries:
        key = (q["regime"], q["period"])
        if key not in period_groups:
            period_groups[key] = []
        period_groups[key].append(q)

    for (regime, period), group in period_groups.items():
        symbols = list(set(q["symbol"] for q in group))
        min_start = min(q["track_start"] for q in group)
        max_end   = max(q["track_end_3w"] for q in group)

        print(f"  Fetching {regime} {period}: {len(symbols)} symbols...", end=" ")
        try:
            with get_engine().connect() as conn:
                df = pd.read_sql(text("""
                    SELECT symbol, date, close_price FROM prices
                    WHERE symbol = ANY(:syms)
                    AND date BETWEEN :start AND :end
                    ORDER BY symbol, date
                """), conn, params={
                    "syms": symbols,
                    "start": min_start,
                    "end": max_end
                })
            df["date"] = pd.to_datetime(df["date"])
            df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
            df = df.dropna()

            # Map to price dict
            price_dict = {}
            for sym, grp in df.groupby("symbol"):
                price_dict[sym] = grp.set_index("date")["close_price"]

            # Process each trade
            for q in group:
                sym    = q["symbol"]
                entry  = q["entry"]
                t_start = pd.to_datetime(q["track_start"])
                t_end_3w = pd.to_datetime(q["track_end_3w"])

                if sym not in price_dict:
                    continue

                prices = price_dict[sym]
                # 1-week window (5 days)
                w1 = prices[(prices.index >= t_start) &
                            (prices.index <= t_start + timedelta(days=7))].values[:5]
                # 3-week window (15 days)
                w3 = prices[(prices.index >= t_start) &
                            (prices.index <= t_end_3w)].values[:15]

                if len(w1) == 0 or len(w3) == 0:
                    continue

                # 1-week metrics
                stop1 = entry * (1 - TRAIL_STOP)
                peak1 = entry
                exit1 = w1[-1]
                for c in w1:
                    if c > peak1: peak1=c; stop1=peak1*(1-TRAIL_STOP)
                    if c < stop1: exit1=c; break

                # 3-week metrics with trailing stop
                stop3 = entry * (1 - TRAIL_STOP)
                peak3 = entry
                exit3 = w3[-1]
                for c in w3:
                    if c > peak3: peak3=c; stop3=peak3*(1-TRAIL_STOP)
                    if c < stop3: exit3=c; break

                ret1 = round((float(exit1)-entry)/entry*100, 2)
                ret3 = round((float(exit3)-entry)/entry*100, 2)
                mg1  = round((max(w1)-entry)/entry*100, 2)
                mg3  = round((max(w3)-entry)/entry*100, 2)

                results.append({
                    "symbol":   sym,
                    "regime":   regime,
                    "period":   period,
                    "week":     q["week"],
                    "entry":    entry,
                    "rsi":      q["rsi"],
                    "obv_%":    q["obv_%"],
                    "break_%":  q["break_%"],
                    "ret_1w":   ret1,
                    "ret_3w":   ret3,
                    "max_gain_1w": mg1,
                    "max_gain_3w": mg3,
                    "win_1w":   1 if ret1 > 0 else 0,
                    "win_3w":   1 if ret3 > 0 else 0,
                })
            print(f"{len([r for r in results if r['regime']==regime and r['period']==period])} trades")
        except Exception as e:
            print(f"ERROR: {e}")

    return pd.DataFrame(results)


def analyze_returns(df):
    """Find best return combinations for 1w and 3w windows."""

    print(f"\n{'='*65}")
    print(f"SLEEVE 2 — RETURN OPTIMIZATION")
    print(f"Total trades: {len(df)}")
    print(f"{'='*65}")

    # Overall comparison
    print(f"\n1-WEEK vs 3-WEEK WINDOW — OVERALL:")
    print(f"  1-week: win={df['win_1w'].sum()}/{len(df)} = {df['win_1w'].mean()*100:.1f}%  avg ret = {df['ret_1w'].mean():+.2f}%")
    print(f"  3-week: win={df['win_3w'].sum()}/{len(df)} = {df['win_3w'].mean()*100:.1f}%  avg ret = {df['ret_3w'].mean():+.2f}%")

    # By regime
    print(f"\nBY REGIME:")
    for regime in ["BULL","CHOPPY","BEAR"]:
        r = df[df["regime"]==regime]
        if r.empty: continue
        print(f"\n  {regime} ({len(r)} trades):")
        print(f"    1-week: win={r['win_1w'].sum()}/{len(r)} = {r['win_1w'].mean()*100:.1f}%  avg={r['ret_1w'].mean():+.2f}%  max_gain={r['max_gain_1w'].mean():+.2f}%")
        print(f"    3-week: win={r['win_3w'].sum()}/{len(r)} = {r['win_3w'].mean()*100:.1f}%  avg={r['ret_3w'].mean():+.2f}%  max_gain={r['max_gain_3w'].mean():+.2f}%")

    # Best return combinations — search all filters
    print(f"\n{'='*65}")
    print(f"BEST RETURN COMBINATIONS — RANKED BY AVG RETURN")
    print(f"(minimum 15 trades for statistical validity)")
    print(f"{'='*65}")

    for window, ret_col, win_col in [("1-WEEK","ret_1w","win_1w"),("3-WEEK","ret_3w","win_3w")]:
        print(f"\n--- {window} WINDOW ---")
        candidates = []
        for regime in ["BULL","CHOPPY","BEAR"]:
            rdf = df[df["regime"]==regime]
            if rdf.empty: continue
            for rsi_lo,rsi_hi in [(60,65),(65,70),(70,75),(75,80),(60,70),(70,80),(60,80)]:
                for obv_min in [5,10,20,50,100]:
                    for top_n in [1,2,4]:
                        f = rdf[(rdf["rsi"]>=rsi_lo)&(rdf["rsi"]<rsi_hi)&(rdf["obv_%"]>=obv_min)]
                        f = f.groupby(["period","week"]).head(top_n)
                        if len(f) < 15: continue
                        avg_ret = f[ret_col].mean()
                        win_rate = f[win_col].mean()*100
                        avg_gain = f["max_gain_1w" if window=="1-WEEK" else "max_gain_3w"].mean()
                        candidates.append({
                            "regime": regime,
                            "filter": f"RSI {rsi_lo}-{rsi_hi} + OBV>={obv_min}% + Top{top_n}",
                            "trades": len(f),
                            "win_%": round(win_rate,1),
                            "avg_ret": round(avg_ret,2),
                            "avg_max_gain": round(avg_gain,2),
                        })

        # Sort by avg return
        cdf = pd.DataFrame(candidates).sort_values("avg_ret", ascending=False)
        print(f"\n  Top 15 by avg return:")
        print(f"  {'Regime':<8} {'Filter':<35} {'N':>5} {'Win%':>6} {'AvgRet':>8} {'MaxGain':>9}")
        print(f"  {'-'*72}")
        for _, row in cdf.head(15).iterrows():
            marker = "🏆" if row["avg_ret"] >= 5 else "✅" if row["avg_ret"] >= 3 else "  "
            print(f"  {marker}{row['regime']:<8} {row['filter']:<35} {row['trades']:>5} "
                  f"{row['win_%']:>6.1f}% {row['avg_ret']:>+8.2f}% {row['avg_max_gain']:>+8.2f}%")

    # Head-to-head: same filter, 1w vs 3w
    print(f"\n{'='*65}")
    print(f"HEAD-TO-HEAD: 1-WEEK vs 3-WEEK — KEY FILTERS")
    print(f"{'='*65}")
    key_filters = [
        ("BULL",   60, 80, 5),
        ("BULL",   70, 75, 5),
        ("BULL",   70, 75, 20),
        ("CHOPPY", 75, 80, 5),
        ("CHOPPY", 75, 80, 20),
        ("CHOPPY", 70, 80, 5),
    ]
    print(f"\n  {'Filter':<45} {'1W Win%':>8} {'1W Ret':>8} {'3W Win%':>8} {'3W Ret':>8}")
    print(f"  {'-'*77}")
    for regime, rlo, rhi, obv in key_filters:
        f = df[(df["regime"]==regime)&(df["rsi"]>=rlo)&(df["rsi"]<rhi)&(df["obv_%"]>=obv)]
        if len(f) < 5: continue
        label = f"{regime} RSI {rlo}-{rhi} OBV>={obv}%"
        print(f"  {label:<45} "
              f"{f['win_1w'].mean()*100:>7.1f}% "
              f"{f['ret_1w'].mean():>+7.2f}% "
              f"{f['win_3w'].mean()*100:>7.1f}% "
              f"{f['ret_3w'].mean():>+7.2f}%")

    # Save results
    df.to_csv("s2_extended_analysis.csv", index=False)
    print(f"\nSaved: s2_extended_analysis.csv")


def main():
    # Load 1-week results
    trades_1w = load_trades()

    # Fetch 3-week forward prices and compute both windows
    df = fetch_forward_prices(trades_1w)

    if df.empty:
        print("No data fetched.")
        return

    print(f"\nProcessed {len(df)} S2 trades with both 1-week and 3-week windows")

    # Run analysis
    analyze_returns(df)
    print("\nDone.")

if __name__ == "__main__":
    main()
