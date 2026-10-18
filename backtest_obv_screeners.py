"""
OBV Screener Backtest — 6 Market Conditions
============================================
Tests both OBV screeners across 6 historical periods:
  - 2 Bear markets
  - 2 Bull markets  
  - 2 Choppy markets

For each period:
  - Runs Sleeve 1 (pre-breakout) and Sleeve 2 (confirmed momentum) signal logic
    on the SIGNAL DATE using only data available up to that date
  - Tracks each flagged stock for 20 trading days after signal
  - Measures outcomes: max gain, max drawdown, breakout confirmation (S1),
    stop hit (S2), final return

Usage:
    python backtest_obv_screeners.py

Output:
    - Terminal summary per period
    - obv_backtest_results.csv — full trade log
    - obv_backtest_summary.csv — period-level stats
"""

import os
import pandas as pd
import numpy as np
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL"))

# ── Parameters ────────────────────────────────────────────────────────────────
LOOKBACK        = 20
SMA_PERIOD      = 50
RSI_PERIOD      = 14
RSI_THRESHOLD   = 60
VOL_SHORT       = 20
VOL_LONG        = 50
TRAIL_STOP_PCT  = 0.10
TRACK_DAYS      = 20    # trading days to track after signal

# ── 6 Test Periods ────────────────────────────────────────────────────────────
TEST_PERIODS = [
    {
        "name":        "Bear 1 — Global Selloff",
        "regime":      "BEAR",
        "signal_date": "2022-04-01",
        "description": "Q2 2022: FII exodus, global rate hikes, Nifty500 -11.3%"
    },
    {
        "name":        "Bear 2 — FII Selloff 2025",
        "regime":      "BEAR",
        "signal_date": "2025-01-02",
        "description": "Q1 2025: Trump tariff fears, FII selling, Nifty500 -11.6%"
    },
    {
        "name":        "Bull 1 — Post-Bear Recovery",
        "regime":      "BULL",
        "signal_date": "2022-10-03",
        "description": "Q4 2022: Recovery rally after selloff, Nifty500 +5.5%"
    },
    {
        "name":        "Bull 2 — Mid-Cycle Rally",
        "regime":      "BULL",
        "signal_date": "2023-07-03",
        "description": "Q3 2023: Strong broad-based bull run, Nifty500 +4.2%"
    },
    {
        "name":        "Choppy 1 — Sideways 2025",
        "regime":      "CHOPPY",
        "signal_date": "2025-07-01",
        "description": "Q3 2025: Flat market, no clear direction, Nifty500 -3.7%"
    },
    {
        "name":        "Choppy 2 — Volatile Recovery",
        "regime":      "CHOPPY",
        "signal_date": "2026-04-01",
        "description": "Q2 2026: Sharp swings, recovery attempt, Nifty500 +9.8%"
    },
]


# ── Fetch data for one period ─────────────────────────────────────────────────
def fetch_period_data(signal_date_str):
    """
    Fetch data needed for signal computation (prior 400 days)
    AND tracking data (next 30 trading days after signal).
    Returns full DataFrame for all active symbols.
    """
    signal_date = pd.to_datetime(signal_date_str)
    # Data before signal: need 400 calendar days for 52w context
    start = signal_date - timedelta(days=400)
    # Data after signal: need ~45 calendar days to get 20 trading days
    end   = signal_date + timedelta(days=45)

    query = text("""
        SELECT symbol, date, close_price, high_price, low_price, volume
        FROM prices
        WHERE date BETWEEN :start AND :end
        AND symbol IN (
            SELECT DISTINCT symbol FROM prices
            WHERE date BETWEEN :sig_start AND :sig_end
        )
        ORDER BY symbol, date ASC
    """)

    # Active symbols: traded in a window around signal date
    sig_start = signal_date - timedelta(days=10)
    sig_end   = signal_date + timedelta(days=10)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={
            "start":     start.strftime("%Y-%m-%d"),
            "end":       end.strftime("%Y-%m-%d"),
            "sig_start": sig_start.strftime("%Y-%m-%d"),
            "sig_end":   sig_end.strftime("%Y-%m-%d"),
        })

    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce")
    df["high_price"]  = pd.to_numeric(df["high_price"],  errors="coerce")
    df["low_price"]   = pd.to_numeric(df["low_price"],   errors="coerce")

    df = df.dropna(subset=["close_price"])
    for col in ["volume", "high_price", "low_price"]:
        df[col] = df.groupby("symbol")[col].transform(
            lambda x: x.fillna(method="ffill").fillna(0)
        )

    return df


# ── OBV calculation ───────────────────────────────────────────────────────────
def compute_obv(close_vals, vol_vals):
    obv = np.zeros(len(close_vals))
    for i in range(1, len(close_vals)):
        if close_vals[i] > close_vals[i-1]:
            obv[i] = obv[i-1] + vol_vals[i]
        elif close_vals[i] < close_vals[i-1]:
            obv[i] = obv[i-1] - vol_vals[i]
        else:
            obv[i] = obv[i-1]
    return obv


# ── RSI calculation ───────────────────────────────────────────────────────────
def compute_rsi(close_series, period=14):
    delta    = close_series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ── Run both screeners on signal date ─────────────────────────────────────────
def run_screeners_on_date(df_all, signal_date_str):
    """
    For each symbol, use only data UP TO signal_date to compute signals.
    Returns two lists: sleeve1_hits, sleeve2_hits
    """
    signal_date = pd.to_datetime(signal_date_str)
    sleeve1     = []
    sleeve2     = []

    for symbol, grp in df_all.groupby("symbol"):
        # Use only data up to and including signal date
        hist = grp[grp["date"] <= signal_date].copy().reset_index(drop=True)

        if len(hist) < max(SMA_PERIOD, VOL_LONG, RSI_PERIOD + 10):
            continue

        # Find the actual signal date row (most recent trading day <= signal_date)
        signal_row_idx = len(hist) - 1
        if hist["date"].iloc[-1] > signal_date:
            continue

        close_vals = hist["close_price"].values
        vol_vals   = hist["volume"].values

        obv_series = compute_obv(close_vals, vol_vals)
        rsi_series = compute_rsi(hist["close_price"])

        today_close = close_vals[-1]
        today_obv   = obv_series[-1]
        today_rsi   = rsi_series.iloc[-1]
        today_date  = hist["date"].iloc[-1]

        if pd.isna(today_rsi):
            continue

        # 20-day prior window
        prior_obv   = obv_series[-(LOOKBACK+1):-1]
        prior_close = close_vals[-(LOOKBACK+1):-1]

        if len(prior_obv) < LOOKBACK:
            continue

        obv_prior_high   = prior_obv.max()
        price_20d_high   = prior_close.max()
        avg_vol_20       = vol_vals[-VOL_SHORT:].mean()
        avg_vol_50       = vol_vals[-VOL_LONG:].mean()
        sma_50           = close_vals[-SMA_PERIOD:].mean()

        obv_breakout     = today_obv > obv_prior_high
        price_breakout   = today_close > price_20d_high
        price_contained  = today_close <= price_20d_high
        volume_rising    = avg_vol_20 >= avg_vol_50
        above_sma        = today_close > sma_50
        rsi_strong       = today_rsi >= RSI_THRESHOLD

        # ── Sleeve 1: OBV up, price NOT broken out ──
        if obv_breakout and price_contained and volume_rising and above_sma:
            obv_pct = round((today_obv - obv_prior_high) / abs(obv_prior_high) * 100
                            if obv_prior_high != 0 else 0, 1)
            gap_pct = round((price_20d_high - today_close) / today_close * 100, 2)
            sleeve1.append({
                "symbol":       symbol,
                "signal_date":  today_date.strftime("%Y-%m-%d"),
                "entry_close":  round(today_close, 2),
                "obv_pct":      obv_pct,
                "gap_to_res_%": gap_pct,
                "rsi":          round(today_rsi, 1),
            })

        # ── Sleeve 2: OBV up AND price broke out ──
        if (obv_breakout and price_breakout and rsi_strong
                and volume_rising and above_sma):
            obv_pct   = round((today_obv - obv_prior_high) / abs(obv_prior_high) * 100
                              if obv_prior_high != 0 else 0, 1)
            price_pct = round((today_close - price_20d_high) / price_20d_high * 100, 2)
            sleeve2.append({
                "symbol":         symbol,
                "signal_date":    today_date.strftime("%Y-%m-%d"),
                "entry_close":    round(today_close, 2),
                "initial_stop":   round(today_close * (1 - TRAIL_STOP_PCT), 2),
                "obv_pct":        obv_pct,
                "price_break_%":  price_pct,
                "rsi":            round(today_rsi, 1),
            })

    return sleeve1, sleeve2


# ── Track outcomes for 20 trading days ───────────────────────────────────────
def track_outcomes(hits, df_all, signal_date_str, sleeve):
    """
    For each hit, find the next 20 trading days of close prices
    and compute outcome metrics.
    """
    signal_date = pd.to_datetime(signal_date_str)
    results     = []

    for hit in hits:
        symbol = hit["symbol"]
        entry  = hit["entry_close"]
        stop   = hit.get("initial_stop", entry * 0.90)

        sym_df = df_all[
            (df_all["symbol"] == symbol) &
            (df_all["date"] > signal_date)
        ].sort_values("date").head(TRACK_DAYS).reset_index(drop=True)

        if len(sym_df) < 3:
            continue

        closes      = sym_df["close_price"].values
        dates       = sym_df["date"].values
        peak_close  = entry
        stop_hit    = False
        stop_date   = None
        exit_close  = closes[-1]

        for i, c in enumerate(closes):
            if c > peak_close:
                peak_close = c
                stop = peak_close * (1 - TRAIL_STOP_PCT)  # trail up
            if c < stop:
                stop_hit   = True
                stop_date  = pd.to_datetime(dates[i]).strftime("%Y-%m-%d")
                exit_close = c
                break

        max_gain_pct = round((peak_close - entry) / entry * 100, 2)
        final_ret    = round((exit_close  - entry) / entry * 100, 2)

        # All closes to compute max drawdown from entry
        all_ret      = [(c - entry) / entry * 100 for c in closes[:i+1 if stop_hit else len(closes)]]
        max_dd       = round(min(all_ret), 2) if all_ret else 0

        # Sleeve 1 specific: did price break the 20d high?
        price_broke  = None
        if sleeve == 1:
            price_20d_high = entry / (1 - hit["gap_to_res_%"] / 100)
            price_broke    = any(c > price_20d_high for c in closes)

        row = {
            **hit,
            "days_tracked":  len(sym_df),
            "peak_close":    round(peak_close, 2),
            "exit_close":    round(exit_close, 2),
            "max_gain_%":    max_gain_pct,
            "max_dd_%":      max_dd,
            "final_ret_%":   final_ret,
        }

        if sleeve == 1:
            row["price_broke_out"] = "YES" if price_broke else "NO"
        if sleeve == 2:
            row["stop_hit"]        = "YES" if stop_hit else "NO"
            row["stop_date"]       = stop_date if stop_hit else "—"

        results.append(row)

    return pd.DataFrame(results)


# ── Print period summary ──────────────────────────────────────────────────────
def print_period_summary(period, s1_results, s2_results):
    print(f"\n{'='*70}")
    print(f"  {period['name']}")
    print(f"  {period['description']}")
    print(f"  Signal date: {period['signal_date']}")
    print(f"{'='*70}")

    # Sleeve 1
    print(f"\n  SLEEVE 1 — Pre-Breakout ({len(s1_results)} signals)")
    print(f"  {'─'*60}")
    if s1_results.empty:
        print("  No signals fired.")
    else:
        broke    = (s1_results["price_broke_out"] == "YES").sum()
        win_rate = round(broke / len(s1_results) * 100, 1)
        avg_gain = round(s1_results[s1_results["price_broke_out"] == "YES"]["max_gain_%"].mean(), 2) if broke > 0 else 0
        avg_ret  = round(s1_results["final_ret_%"].mean(), 2)
        avg_dd   = round(s1_results["max_dd_%"].mean(), 2)
        print(f"  Breakout confirmed: {broke}/{len(s1_results)} ({win_rate}%)")
        print(f"  Avg max gain (winners): {avg_gain}%")
        print(f"  Avg final return (all): {avg_ret}%")
        print(f"  Avg max drawdown:       {avg_dd}%")
        print(f"\n  Top 5 signals:")
        top = s1_results.nlargest(5, "final_ret_%")[
            ["symbol","entry_close","gap_to_res_%","obv_pct","price_broke_out","max_gain_%","final_ret_%","max_dd_%"]
        ]
        print(top.to_string(index=False))

    # Sleeve 2
    print(f"\n  SLEEVE 2 — Confirmed Momentum ({len(s2_results)} signals)")
    print(f"  {'─'*60}")
    if s2_results.empty:
        print("  No signals fired.")
    else:
        stopped  = (s2_results["stop_hit"] == "YES").sum()
        stop_rt  = round(stopped / len(s2_results) * 100, 1)
        avg_ret  = round(s2_results["final_ret_%"].mean(), 2)
        avg_gain = round(s2_results["max_gain_%"].mean(), 2)
        avg_dd   = round(s2_results["max_dd_%"].mean(), 2)
        print(f"  Stop hit: {stopped}/{len(s2_results)} ({stop_rt}%)")
        print(f"  Avg max gain:           {avg_gain}%")
        print(f"  Avg final return (all): {avg_ret}%")
        print(f"  Avg max drawdown:       {avg_dd}%")
        print(f"\n  Top 5 signals:")
        top = s2_results.nlargest(5, "final_ret_%")[
            ["symbol","entry_close","rsi","obv_pct","stop_hit","max_gain_%","final_ret_%","max_dd_%"]
        ]
        print(top.to_string(index=False))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("OBV Screener Backtest — 6 Market Conditions")
    print("=" * 70)

    all_s1   = []
    all_s2   = []
    summary  = []

    for period in TEST_PERIODS:
        print(f"\nFetching data for: {period['name']} ({period['signal_date']})...")
        df_all = fetch_period_data(period["signal_date"])
        print(f"  Loaded {len(df_all):,} rows for {df_all['symbol'].nunique()} symbols.")

        print(f"  Running screeners on {period['signal_date']}...")
        s1_hits, s2_hits = run_screeners_on_date(df_all, period["signal_date"])
        print(f"  Sleeve 1: {len(s1_hits)} signals | Sleeve 2: {len(s2_hits)} signals")

        print(f"  Tracking outcomes for {TRACK_DAYS} trading days...")
        s1_results = track_outcomes(s1_hits, df_all, period["signal_date"], sleeve=1)
        s2_results = track_outcomes(s2_hits, df_all, period["signal_date"], sleeve=2)

        # Tag with period info
        for df in [s1_results, s2_results]:
            if not df.empty:
                df.insert(0, "period",  period["name"])
                df.insert(1, "regime",  period["regime"])

        print_period_summary(period, s1_results, s2_results)

        # Collect for CSV
        if not s1_results.empty:
            s1_results["sleeve"] = 1
            all_s1.append(s1_results)
        if not s2_results.empty:
            s2_results["sleeve"] = 2
            all_s2.append(s2_results)

        # Period summary row
        s1_broke = (s1_results["price_broke_out"] == "YES").sum() if not s1_results.empty else 0
        s2_stopped = (s2_results["stop_hit"] == "YES").sum() if not s2_results.empty else 0
        summary.append({
            "period":           period["name"],
            "regime":           period["regime"],
            "signal_date":      period["signal_date"],
            "s1_signals":       len(s1_results),
            "s1_breakouts":     s1_broke,
            "s1_win_rate_%":    round(s1_broke / len(s1_results) * 100, 1) if len(s1_results) > 0 else 0,
            "s1_avg_ret_%":     round(s1_results["final_ret_%"].mean(), 2) if not s1_results.empty else 0,
            "s2_signals":       len(s2_results),
            "s2_stops_hit":     s2_stopped,
            "s2_stop_rate_%":   round(s2_stopped / len(s2_results) * 100, 1) if len(s2_results) > 0 else 0,
            "s2_avg_ret_%":     round(s2_results["final_ret_%"].mean(), 2) if not s2_results.empty else 0,
        })

    # ── Overall summary ──
    print(f"\n\n{'='*70}")
    print("  OVERALL BACKTEST SUMMARY")
    print(f"{'='*70}")
    summary_df = pd.DataFrame(summary)
    print(summary_df[[
        "period","regime","s1_signals","s1_win_rate_%","s1_avg_ret_%",
        "s2_signals","s2_stop_rate_%","s2_avg_ret_%"
    ]].to_string(index=False))

    # ── By regime ──
    print(f"\n  By Market Regime:")
    for regime in ["BULL","BEAR","CHOPPY"]:
        rdf = summary_df[summary_df["regime"] == regime]
        print(f"\n  {regime}:")
        print(f"    Sleeve 1 avg win rate:   {rdf['s1_win_rate_%'].mean():.1f}%")
        print(f"    Sleeve 1 avg return:     {rdf['s1_avg_ret_%'].mean():.2f}%")
        print(f"    Sleeve 2 avg stop rate:  {rdf['s2_stop_rate_%'].mean():.1f}%")
        print(f"    Sleeve 2 avg return:     {rdf['s2_avg_ret_%'].mean():.2f}%")

    # ── Save CSVs ──
    all_trades = pd.concat(all_s1 + all_s2, ignore_index=True) if (all_s1 or all_s2) else pd.DataFrame()
    if not all_trades.empty:
        all_trades.to_csv("obv_backtest_results.csv", index=False)
    summary_df.to_csv("obv_backtest_summary.csv", index=False)

    print(f"\n\nSaved:")
    print(f"  Full trade log  → obv_backtest_results.csv")
    print(f"  Period summary  → obv_backtest_summary.csv")
    print("\nDone.")


if __name__ == "__main__":
    main()
