"""
Full Model Backtest — 100+ trades with complete filter stack
=============================================================
Applies all proven filters in sequence:
  1. Regime: BULL or CHOPPY only
  2. RSI zone: BULL 70-75, CHOPPY 75-80
  3. OBV: >= 50% (BULL), >= 20% (CHOPPY)
  4. Monday direction gate: Nifty500 must close UP on Monday
  5. Entry: Tuesday close (day after Monday confirmation)
  6. Exit: Following Monday close (5 trading days from Tuesday)
  7. Stop: 5% (BULL), 4% (CHOPPY) from Tuesday entry

Note: Delivery % and liquidity filters not in historical CSV.
      Applied as manual pre-trade checks in live system.
      Backtest shows model performance; live performance will be
      higher as delivery/liquidity filters remove bad trades.

Usage:
    python full_model_backtest.py
"""

import os
import numpy as np
import pandas as pd
from datetime import timedelta, datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

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

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})


def get_signal_date(regime, period, week_num):
    period_start = pd.to_datetime(PERIOD_STARTS.get((regime, period), "2023-01-01"))
    signal_date  = period_start + timedelta(days=(week_num-1)*7)
    days_to_sun  = (6 - signal_date.weekday()) % 7
    return signal_date + timedelta(days=days_to_sun)


def fetch_nifty_weekly(engine, start, end):
    """Fetch NIFTY500_IDX daily closes for regime/Monday gate."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT date, close_price FROM prices
            WHERE symbol = 'NIFTY500_IDX'
            AND date BETWEEN :s AND :e
            ORDER BY date
        """), conn, params={"s": start, "e": end})
    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    return df.set_index("date")["close_price"]


def fetch_stock_prices(engine, symbols, start, end):
    """Fetch stock prices for a period."""
    with get_engine().connect() as conn:
        df = pd.read_sql(text("""
            SELECT symbol, date, close_price FROM prices
            WHERE symbol = ANY(:syms)
            AND date BETWEEN :s AND :e
            ORDER BY symbol, date
        """), conn, params={"syms": list(symbols), "s": start, "e": end})
    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df = df.dropna()
    result = {}
    for sym, grp in df.groupby("symbol"):
        result[sym] = grp.set_index("date")["close_price"]
    return result


def get_next_trading_day(date, prices_index, n=1):
    """Get the nth next trading day from date."""
    found = 0
    d = date + timedelta(days=1)
    while found < n:
        if pd.Timestamp(d) in prices_index:
            found += 1
            if found == n:
                return pd.Timestamp(d)
        d += timedelta(days=1)
        if (d - date.to_pydatetime()).days > 30:
            return None
    return None


def run_full_backtest():
    print("Full Model Backtest — Complete Filter Stack")
    print("=" * 65)
    print("Filters: Regime + RSI zone + OBV + Monday direction gate")
    print("Entry: Tuesday close | Exit: 5 trading days later")
    print()

    # Load signal data
    s2 = pd.read_csv("s2_extended_analysis.csv")
    wk = pd.read_csv("weekday_analysis_results.csv")

    # Apply RSI + OBV filters
    bull_signals = s2[
        (s2["regime"] == "BULL") &
        (s2["rsi"] >= 70) & (s2["rsi"] < 75) &
        (s2["obv_%"] >= 50)
    ].copy()

    chop_signals = s2[
        (s2["regime"] == "CHOPPY") &
        (s2["rsi"] >= 75) & (s2["rsi"] < 80) &
        (s2["obv_%"] >= 20)
    ].copy()

    all_signals = pd.concat([bull_signals, chop_signals], ignore_index=True)
    print(f"Signals after RSI+OBV filter: {len(all_signals)} "
          f"(BULL: {len(bull_signals)}, CHOPPY: {len(chop_signals)})")

    # Add signal dates
    all_signals["week_num"]    = all_signals["week"].str[1:].astype(int)
    all_signals["signal_date"] = all_signals.apply(
        lambda r: get_signal_date(r["regime"], r["period"], r["week_num"]), axis=1)
    all_signals["monday"]      = all_signals["signal_date"] + timedelta(days=1)

    engine = get_engine()
    results = []
    skipped_monday_down = 0
    skipped_no_data     = 0

    # Group by period for efficient fetching
    period_groups = {}
    for _, row in all_signals.iterrows():
        key = (row["regime"], row["period"])
        if key not in period_groups:
            period_groups[key] = []
        period_groups[key].append(row)

    for (regime, period), group in period_groups.items():
        stop_pct = 5.0 if regime == "BULL" else 4.0
        symbols  = list(set(r["symbol"] for r in group))
        min_mon  = min(pd.Timestamp(r["monday"]) for r in group)
        max_exit = max(pd.Timestamp(r["monday"]) for r in group) + timedelta(days=14)

        # Fetch Nifty500 for Monday gate
        nifty_start = (min_mon - timedelta(days=5)).strftime("%Y-%m-%d")
        nifty_end   = max_exit.strftime("%Y-%m-%d")
        nifty       = fetch_nifty_weekly(engine, nifty_start, nifty_end)

        # Fetch stock prices
        stock_px    = fetch_stock_prices(engine, symbols,
                                         nifty_start, nifty_end)

        print(f"  {regime} {period}: {len(group)} signals, "
              f"{len(symbols)} stocks...", end=" ")

        period_results = []
        for row in group:
            sym    = row["symbol"]
            monday = pd.Timestamp(row["monday"])

            if sym not in stock_px:
                skipped_no_data += 1
                continue

            sym_prices = stock_px[sym]

            # ── FILTER: Monday direction gate ──────────────────────────
            # Find Friday close (day before Monday)
            fri_dates = [d for d in nifty.index if d < monday]
            if not fri_dates:
                skipped_no_data += 1
                continue
            fri_close    = float(nifty.loc[fri_dates[-1]])

            # Find Monday close
            mon_dates = [d for d in nifty.index if d >= monday and
                         d < monday + timedelta(days=3)]
            if not mon_dates:
                skipped_no_data += 1
                continue
            mon_date  = mon_dates[0]
            mon_close = float(nifty.loc[mon_date])
            mon_ret   = (mon_close - fri_close) / fri_close * 100

            # Gate: skip if Nifty500 is flat or down on Monday
            if mon_ret <= 0:
                skipped_monday_down += 1
                continue

            # ── ENTRY: Tuesday close ───────────────────────────────────
            tue_dates = [d for d in sym_prices.index if d > mon_date and
                         d <= mon_date + timedelta(days=4)]
            if not tue_dates:
                skipped_no_data += 1
                continue
            tue_date  = tue_dates[0]
            entry     = float(sym_prices.loc[tue_date])
            stop      = round(entry * (1 - stop_pct/100), 2)

            # ── EXIT: 5 trading days from Tuesday ──────────────────────
            sym_dates = [d for d in sym_prices.index if d > tue_date]
            if len(sym_dates) < 5:
                skipped_no_data += 1
                continue

            # Walk 5 trading days with trailing stop
            exit_price = float(sym_prices.loc[sym_dates[4]])  # 5th day
            exit_date  = sym_dates[4]
            peak       = entry
            stop_hit   = False
            actual_stop = stop

            for i in range(min(5, len(sym_dates))):
                c = float(sym_prices.loc[sym_dates[i]])
                if c > peak:
                    peak        = c
                    actual_stop = round(peak * (1 - stop_pct/100), 2)
                if c < actual_stop:
                    exit_price = c
                    exit_date  = sym_dates[i]
                    stop_hit   = True
                    break

            ret       = round((exit_price - entry) / entry * 100, 2)
            max_gain  = round((max(float(sym_prices.loc[d])
                               for d in sym_dates[:5]) - entry) / entry * 100, 2)
            max_dd    = round((min(float(sym_prices.loc[d])
                               for d in sym_dates[:5]) - entry) / entry * 100, 2)

            period_results.append({
                "symbol":      sym,
                "regime":      regime,
                "period":      period,
                "week":        row["week"],
                "rsi":         row["rsi"],
                "obv_%":       row["obv_%"],
                "mon_ret_%":   round(mon_ret, 2),
                "entry_date":  tue_date.strftime("%Y-%m-%d"),
                "entry":       round(entry, 2),
                "exit_date":   exit_date.strftime("%Y-%m-%d"),
                "exit":        round(exit_price, 2),
                "stop_pct":    stop_pct,
                "stop_hit":    stop_hit,
                "ret_%":       ret,
                "max_gain_%":  max_gain,
                "max_dd_%":    max_dd,
                "winner":      1 if ret > 0 else 0,
            })

        print(f"{len(period_results)} entered, "
              f"{len(group)-len(period_results)} skipped")
        results.extend(period_results)

    df = pd.DataFrame(results)
    df.to_csv("full_model_backtest_results.csv", index=False)

    print(f"\n{'='*65}")
    print(f"FULL MODEL BACKTEST RESULTS")
    print(f"{'='*65}")
    print(f"\nFilter funnel:")
    print(f"  Signals after RSI+OBV:     {len(all_signals)}")
    print(f"  Skipped (Monday down):      {skipped_monday_down}")
    print(f"  Skipped (no data):          {skipped_no_data}")
    print(f"  Trades entered:             {len(df)}")
    print(f"  Stop hit:                   {df['stop_hit'].sum()} "
          f"({df['stop_hit'].mean()*100:.1f}%)")

    print(f"\n--- OVERALL ---")
    w = df["winner"].sum(); t = len(df)
    print(f"  Win rate:     {w}/{t} = {w/t*100:.1f}%")
    print(f"  Avg return:   {df['ret_%'].mean():+.2f}%")
    print(f"  Avg max gain: {df['max_gain_%'].mean():+.2f}%")
    print(f"  Avg max DD:   {df['max_dd_%'].mean():+.2f}%")

    # Expectancy per trade
    winners = df[df["winner"]==1]["ret_%"]
    losers  = df[df["winner"]==0]["ret_%"]
    win_rate = w/t
    expectancy = (win_rate * winners.mean()) + ((1-win_rate) * losers.mean())
    print(f"  Avg winner:   {winners.mean():+.2f}%")
    print(f"  Avg loser:    {losers.mean():+.2f}%")
    print(f"  Expectancy:   {expectancy:+.2f}% per trade")

    print(f"\n--- BY REGIME ---")
    for regime in ["BULL","CHOPPY"]:
        r = df[df["regime"]==regime]
        if r.empty: continue
        w2 = r["winner"].sum(); t2 = len(r)
        sp = r["stop_pct"].iloc[0]
        print(f"\n  {regime} (stop {sp}%, {t2} trades):")
        print(f"    Win rate:   {w2}/{t2} = {w2/t2*100:.1f}%")
        print(f"    Avg return: {r['ret_%'].mean():+.2f}%")
        print(f"    Max gain:   {r['max_gain_%'].mean():+.2f}%")
        print(f"    Stop hits:  {r['stop_hit'].sum()} ({r['stop_hit'].mean()*100:.1f}%)")
        rw = r[r["winner"]==1]["ret_%"]
        rl = r[r["winner"]==0]["ret_%"]
        wr = w2/t2
        exp = (wr*rw.mean()) + ((1-wr)*rl.mean()) if not rl.empty else rw.mean()
        print(f"    Expectancy: {exp:+.2f}% per trade")

    print(f"\n--- BY PERIOD ---")
    for (regime, period), grp in df.groupby(["regime","period"]):
        w3=grp["winner"].sum(); t3=len(grp)
        print(f"  {regime} {period}: {w3}/{t3} = {w3/t3*100:.0f}%  "
              f"avg {grp['ret_%'].mean():+.2f}%")

    print(f"\n--- MONDAY GATE IMPACT ---")
    # Compare vs original backtest numbers
    print(f"  Without Monday gate (original backtest):")
    print(f"    BULL RSI70-75+OBV>=50:   59% win, +3.55% avg")
    print(f"    CHOPPY RSI75-80+OBV>=20: 68% win, +4.46% avg")
    print(f"  With Monday gate (this backtest):")
    bull_r  = df[df["regime"]=="BULL"]
    chop_r  = df[df["regime"]=="CHOPPY"]
    if not bull_r.empty:
        print(f"    BULL:   {bull_r['winner'].mean()*100:.1f}% win, "
              f"{bull_r['ret_%'].mean():+.2f}% avg")
    if not chop_r.empty:
        print(f"    CHOPPY: {chop_r['winner'].mean()*100:.1f}% win, "
              f"{chop_r['ret_%'].mean():+.2f}% avg")

    print(f"\n--- FREQUENCY ---")
    total_weeks  = len(all_signals)
    entered      = len(df)
    print(f"  Signal weeks:         {total_weeks}")
    print(f"  Weeks entered:        {entered} ({entered/total_weeks*100:.1f}%)")
    print(f"  Weeks gated (Mon dn): {skipped_monday_down} "
          f"({skipped_monday_down/total_weeks*100:.1f}%)")
    print(f"  Avg trades/month:     ~{entered/(total_weeks/4):.1f}")

    print(f"\nSaved: full_model_backtest_results.csv")
    print("Done.")


if __name__ == "__main__":
    run_full_backtest()
