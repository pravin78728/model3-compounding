"""
6-Month Backtest — Apr 1 to Sep 30 2026 — Model 2 Sleeves 1 & 2
=================================================================
Runs both OBV screeners on each Sunday from Apr to Sep 2026,
takes top 4 signals per sleeve per week, tracks Mon-Fri performance.

Usage:
    python sixmonth_backtest.py
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
    """Create a fresh connection each time to avoid timeout."""
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

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
TOP_N         = 4

# ── All Sundays Apr 1 - Sep 30 2026 ──────────────────────────────────────────
WEEKS = [
    {"signal_date": "2026-04-05", "track_start": "2026-04-06", "track_end": "2026-04-10", "label": "Apr W1"},
    {"signal_date": "2026-04-12", "track_start": "2026-04-13", "track_end": "2026-04-17", "label": "Apr W2"},
    {"signal_date": "2026-04-19", "track_start": "2026-04-20", "track_end": "2026-04-24", "label": "Apr W3"},
    {"signal_date": "2026-04-26", "track_start": "2026-04-27", "track_end": "2026-04-30", "label": "Apr W4"},
    {"signal_date": "2026-05-03", "track_start": "2026-05-04", "track_end": "2026-05-08", "label": "May W1"},
    {"signal_date": "2026-05-10", "track_start": "2026-05-11", "track_end": "2026-05-15", "label": "May W2"},
    {"signal_date": "2026-05-17", "track_start": "2026-05-18", "track_end": "2026-05-22", "label": "May W3"},
    {"signal_date": "2026-05-24", "track_start": "2026-05-25", "track_end": "2026-05-29", "label": "May W4"},
    {"signal_date": "2026-05-31", "track_start": "2026-06-01", "track_end": "2026-06-05", "label": "Jun W1"},
    {"signal_date": "2026-06-07", "track_start": "2026-06-08", "track_end": "2026-06-12", "label": "Jun W2"},
    {"signal_date": "2026-06-14", "track_start": "2026-06-15", "track_end": "2026-06-19", "label": "Jun W3"},
    {"signal_date": "2026-06-21", "track_start": "2026-06-22", "track_end": "2026-06-26", "label": "Jun W4"},
    {"signal_date": "2026-06-28", "track_start": "2026-06-29", "track_end": "2026-07-03", "label": "Jul W1"},
    {"signal_date": "2026-07-05", "track_start": "2026-07-06", "track_end": "2026-07-10", "label": "Jul W2"},
    {"signal_date": "2026-07-12", "track_start": "2026-07-13", "track_end": "2026-07-17", "label": "Jul W3"},
    {"signal_date": "2026-07-19", "track_start": "2026-07-20", "track_end": "2026-07-24", "label": "Jul W4"},
    {"signal_date": "2026-07-26", "track_start": "2026-07-27", "track_end": "2026-07-31", "label": "Jul W5"},
    {"signal_date": "2026-08-02", "track_start": "2026-08-03", "track_end": "2026-08-07", "label": "Aug W1"},
    {"signal_date": "2026-08-09", "track_start": "2026-08-10", "track_end": "2026-08-14", "label": "Aug W2"},
    {"signal_date": "2026-08-16", "track_start": "2026-08-17", "track_end": "2026-08-21", "label": "Aug W3"},
    {"signal_date": "2026-08-23", "track_start": "2026-08-24", "track_end": "2026-08-28", "label": "Aug W4"},
    {"signal_date": "2026-08-30", "track_start": "2026-08-31", "track_end": "2026-09-04", "label": "Sep W1"},
    {"signal_date": "2026-09-06", "track_start": "2026-09-07", "track_end": "2026-09-11", "label": "Sep W2"},
    {"signal_date": "2026-09-13", "track_start": "2026-09-14", "track_end": "2026-09-18", "label": "Sep W3"},
    {"signal_date": "2026-09-20", "track_start": "2026-09-21", "track_end": "2026-09-25", "label": "Sep W4"},
    {"signal_date": "2026-09-27", "track_start": "2026-09-28", "track_end": "2026-09-30", "label": "Sep W5"},
]


# ── Regime check ──────────────────────────────────────────────────────────────
def get_regime_on_date(signal_date_str, symbol_data):
    """Compute regime as of signal date using NIFTY500_IDX from symbol_data."""
    if "NIFTY500_IDX" not in symbol_data:
        return "UNKNOWN"
    signal_date = pd.to_datetime(signal_date_str)
    df = symbol_data["NIFTY500_IDX"]
    hist = df[df["date"] <= signal_date].copy()
    if len(hist) < 250:
        return "UNKNOWN"
    rows    = list(zip(hist["date"], hist["close_price"]))
    rd      = rows[-1][0]
    p_now   = rows[-1][1]
    p_200   = [p for d,p in rows if d >= rd - timedelta(days=280)]
    p_12m   = next((p for d,p in reversed(rows) if d <= rd - timedelta(days=240)), None)
    dma200  = np.mean(p_200) if p_200 else None
    if dma200 and p_12m:
        if p_now > dma200 * 1.03 and p_now > p_12m * 1.05:
            return "BULL"
        elif p_now < dma200 * 0.97 and p_now < p_12m * 0.95:
            return "BEAR"
        return "CHOPPY"
    return "UNKNOWN"


# ── Fetch data ────────────────────────────────────────────────────────────────
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
    symbol_data = {sym: grp.reset_index(drop=True) for sym, grp in df.groupby("symbol")}

    # Always fetch NIFTY500_IDX separately for regime check (no volume requirement)
    with get_engine().connect() as conn:
        idx_df = pd.read_sql(text("""
            SELECT symbol, date, close_price, volume
            FROM prices
            WHERE symbol = 'NIFTY500_IDX'
            AND date BETWEEN :start AND :end
            ORDER BY date ASC
        """), conn, params={"start": start, "end": end})
    if not idx_df.empty:
        idx_df["date"]        = pd.to_datetime(idx_df["date"])
        idx_df["close_price"] = pd.to_numeric(idx_df["close_price"], errors="coerce")
        idx_df["volume"]      = pd.to_numeric(idx_df["volume"], errors="coerce").fillna(0)
        idx_df = idx_df.dropna(subset=["close_price"])
        symbol_data["NIFTY500_IDX"] = idx_df.reset_index(drop=True)

    return symbol_data


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


# ── Run screeners ─────────────────────────────────────────────────────────────
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
                           "sma50": round(sma50, 2),
                           "pct_above_sma": round((tc/sma50-1)*100, 1)})

        if obv_ok and tc > price_high and vol_ok and sma_ok and RSI_THRESHOLD <= tr < RSI_MAX:
            brk = round((tc - price_high) / price_high * 100, 2)
            sleeve2.append({"symbol": symbol, "entry": round(tc, 2),
                           "obv_%": obv_pct, "break_%": brk, "rsi": round(tr, 1),
                           "stop": round(tc * (1 - TRAIL_STOP), 2),
                           "sma50": round(sma50, 2),
                           "pct_above_sma": round((tc/sma50-1)*100, 1)})

    s1 = pd.DataFrame(sleeve1).sort_values("obv_%", ascending=False).head(TOP_N).reset_index(drop=True) if sleeve1 else pd.DataFrame()
    s2 = pd.DataFrame(sleeve2).sort_values("obv_%", ascending=False).head(TOP_N).reset_index(drop=True) if sleeve2 else pd.DataFrame()
    return s1, s2


# ── Track performance ─────────────────────────────────────────────────────────
def track_performance(signals, symbol_data, signal_date_str, track_start, track_end, sleeve):
    if signals.empty:
        return pd.DataFrame()

    t_start = pd.to_datetime(track_start)
    t_end   = pd.to_datetime(track_end)
    results = []

    for _, row in signals.iterrows():
        symbol = row["symbol"]
        entry  = row["entry"]
        stop   = row.get("stop", entry * (1 - TRAIL_STOP))

        if symbol not in symbol_data:
            continue

        df   = symbol_data[symbol]
        week = df[(df["date"] >= t_start) & (df["date"] <= t_end)].copy()
        if week.empty:
            continue

        closes     = week["close_price"].values
        dates      = week["date"].values
        peak       = entry
        stop_hit   = False
        exit_close = closes[-1]

        broke_res = False
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

        max_gain  = round((max(closes) - entry) / entry * 100, 2)
        max_dd    = round((min(closes) - entry) / entry * 100, 2)
        final_ret = round((float(exit_close) - entry) / entry * 100, 2)

        r = {
            "symbol":          symbol,
            "entry":           entry,
            "obv_%":           row["obv_%"],
            "rsi":             row["rsi"],
            "pct_above_sma":   row.get("pct_above_sma", 0),
            "max_gain_%":      max_gain,
            "max_dd_%":        max_dd,
            "final_ret_%":     final_ret,
            "winner":          1 if final_ret > 0 else 0,
        }
        if sleeve == 1:
            r["gap_%"]    = row["gap_%"]
            r["broke_res"] = 1 if broke_res else 0
        if sleeve == 2:
            r["break_%"]  = row["break_%"]
            r["stop_hit"] = 1 if stop_hit else 0
            r["peak"]     = round(float(peak), 2)

        results.append(r)

    return pd.DataFrame(results)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("6-Month Backtest — Apr-Sep 2026 — Model 2 Sleeves 1 & 2")
    print("=" * 65)

    # Resume: load existing results if present
    resume_file = "sixmonth_backtest_results.csv"
    if os.path.exists(resume_file):
        existing = pd.read_csv(resume_file)
        done_weeks = set(existing["week"].unique())
        all_s1 = [existing[(existing["week"] == w) & (existing["sleeve"] == 1)] for w in done_weeks]
        all_s2 = [existing[(existing["week"] == w) & (existing["sleeve"] == 2)] for w in done_weeks]
        all_s1 = [d for d in all_s1 if not d.empty]
        all_s2 = [d for d in all_s2 if not d.empty]
        print(f"Resuming — {len(done_weeks)} weeks already done: {sorted(done_weeks)}")
    else:
        existing   = pd.DataFrame()
        done_weeks = set()
        all_s1, all_s2 = [], []

    week_summary = []

    for week in WEEKS:
        if week["label"] in done_weeks:
            print(f"Skipping {week['label']} (already done)")
            continue
        print(f"Processing {week['label']} (signal: {week['signal_date']})...", end=" ")
        symbol_data = fetch_week_data(week["signal_date"])
        regime      = get_regime_on_date(week["signal_date"], symbol_data)
        s1, s2      = run_screeners(symbol_data, week["signal_date"])

        s1_res = track_performance(s1, symbol_data, week["signal_date"],
                                   week["track_start"], week["track_end"], sleeve=1)
        s2_res = track_performance(s2, symbol_data, week["signal_date"],
                                   week["track_start"], week["track_end"], sleeve=2)

        s1_win = int((s1_res["winner"].sum())) if not s1_res.empty else 0
        s2_win = int((s2_res["winner"].sum())) if not s2_res.empty else 0
        s1_ret = round(s1_res["final_ret_%"].mean(), 2) if not s1_res.empty else 0
        s2_ret = round(s2_res["final_ret_%"].mean(), 2) if not s2_res.empty else 0

        print(f"Regime: {regime} | S1: {s1_win}/{len(s1_res)} wins {s1_ret}% | S2: {s2_win}/{len(s2_res)} wins {s2_ret}%")

        week_summary.append({
            "week": week["label"], "regime": regime,
            "s1_signals": len(s1_res), "s1_wins": s1_win, "s1_avg_ret": s1_ret,
            "s2_signals": len(s2_res), "s2_wins": s2_win, "s2_avg_ret": s2_ret,
        })

        if not s1_res.empty:
            s1_res["week"]   = week["label"]
            s1_res["regime"] = regime
            s1_res["sleeve"] = 1
            all_s1.append(s1_res)
        if not s2_res.empty:
            s2_res["week"]   = week["label"]
            s2_res["regime"] = regime
            s2_res["sleeve"] = 2
            all_s2.append(s2_res)

        # Save after each week so we can resume if connection drops
        if all_s1 or all_s2:
            checkpoint = pd.concat(all_s1 + all_s2, ignore_index=True)
            checkpoint.to_csv("sixmonth_backtest_results.csv", index=False)

    # ── Save full trade log ──
    all_trades = pd.concat(all_s1 + all_s2, ignore_index=True) if (all_s1 or all_s2) else pd.DataFrame()
    all_trades.to_csv("sixmonth_backtest_results.csv", index=False)

    week_df = pd.DataFrame(week_summary)
    week_df.to_csv("sixmonth_backtest_weekly.csv", index=False)

    # ── Summary by regime ──
    print(f"\n{'='*65}")
    print("SUMMARY BY REGIME")
    print(f"{'='*65}")
    for regime in ["BULL", "CHOPPY", "BEAR", "UNKNOWN"]:
        rdf = all_trades[all_trades["regime"] == regime] if not all_trades.empty else pd.DataFrame()
        if rdf.empty:
            continue
        wins = rdf["winner"].sum()
        print(f"\n{regime} ({len(rdf)} trades):")
        print(f"  Win rate:     {wins}/{len(rdf)} ({round(wins/len(rdf)*100,1)}%)")
        print(f"  Avg return:   {round(rdf['final_ret_%'].mean(),2)}%")
        print(f"  Avg max gain: {round(rdf['max_gain_%'].mean(),2)}%")
        print(f"  Avg max DD:   {round(rdf['max_dd_%'].mean(),2)}%")

    # ── Sleeve breakdown ──
    print(f"\n{'='*65}")
    print("SLEEVE BREAKDOWN (all regimes)")
    print(f"{'='*65}")
    for sleeve, name in [(1,"Sleeve 1 Pre-Breakout"), (2,"Sleeve 2 Momentum")]:
        sdf = all_trades[all_trades["sleeve"] == sleeve] if not all_trades.empty else pd.DataFrame()
        if sdf.empty:
            continue
        wins = sdf["winner"].sum()
        print(f"\n{name} ({len(sdf)} trades):")
        print(f"  Win rate:     {wins}/{len(sdf)} ({round(wins/len(sdf)*100,1)}%)")
        print(f"  Avg return:   {round(sdf['final_ret_%'].mean(),2)}%")

    print(f"\nSaved: sixmonth_backtest_results.csv")
    print(f"Saved: sixmonth_backtest_weekly.csv")
    print("\nDone.")


if __name__ == "__main__":
    main()
