"""
Weekday Analysis — Does day of entry matter?
============================================
Tests hypothesis: Monday entries outperform mid-week entries.
Uses existing extended_regime_results.csv trade log.
Re-fetches actual daily prices to compute day-of-week returns.
"""

import os
import numpy as np
import pandas as pd
from datetime import timedelta, datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

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

def get_signal_dates(trades_df):
    """Map each trade back to its signal date (Sunday) and entry date (Monday)."""
    results = []
    for _, row in trades_df.iterrows():
        period_start = pd.to_datetime(PERIOD_STARTS.get(
            (row["regime"], row["period"]), "2023-01-01"))
        week_num     = int(row["week"][1:])
        signal_date  = period_start + timedelta(days=(week_num-1)*7)
        # Find nearest Sunday
        days_to_sun  = (6 - signal_date.weekday()) % 7
        signal_date  = signal_date + timedelta(days=days_to_sun)
        entry_mon    = signal_date + timedelta(days=1)  # Monday
        entry_fri    = signal_date + timedelta(days=5)  # Friday (last day of week)
        results.append({
            "symbol":     row["symbol"],
            "regime":     row["regime"],
            "period":     row["period"],
            "week":       row["week"],
            "sleeve":     row["sleeve"],
            "entry_1w":   row.get("entry", 0),
            "ret_1w":     row.get("final_ret_%", row.get("ret_1w", 0)),
            "win_1w":     row.get("winner", row.get("win_1w", 0)),
            "signal_date": signal_date,
            "monday":     entry_mon,
            "friday":     entry_fri,
        })
    return pd.DataFrame(results)


def fetch_weekday_prices(trades_meta):
    """
    For each trade, fetch actual Mon-Fri closing prices.
    Returns enriched df with per-day returns.
    """
    # Group by period to minimize DB calls
    all_results = []
    engine = get_engine()

    period_groups = {}
    for _, row in trades_meta.iterrows():
        key = (row["regime"], row["period"])
        if key not in period_groups:
            period_groups[key] = []
        period_groups[key].append(row)

    for (regime, period), group in period_groups.items():
        symbols   = list(set(r["symbol"] for r in group))
        min_mon   = min(r["monday"] for r in group)
        max_fri   = max(r["friday"] for r in group)
        # Add buffer
        start = (min_mon - timedelta(days=2)).strftime("%Y-%m-%d")
        end   = (max_fri + timedelta(days=2)).strftime("%Y-%m-%d")

        try:
            with get_engine().connect() as conn:
                df = pd.read_sql(text("""
                    SELECT symbol, date, close_price FROM prices
                    WHERE symbol = ANY(:syms)
                    AND date BETWEEN :start AND :end
                    ORDER BY symbol, date
                """), conn, params={"syms": symbols, "start": start, "end": end})
            df["date"]        = pd.to_datetime(df["date"])
            df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
            df = df.dropna()

            price_dict = {}
            for sym, grp in df.groupby("symbol"):
                price_dict[sym] = grp.set_index("date")["close_price"]

            for row in group:
                sym    = row["symbol"]
                entry  = row["entry_1w"]
                mon    = pd.Timestamp(row["monday"])
                fri    = pd.Timestamp(row["friday"])

                if sym not in price_dict:
                    continue

                prices  = price_dict[sym]
                # Get Mon-Fri prices for this week
                week_px = prices[(prices.index >= mon) &
                                 (prices.index <= fri)].sort_index()

                if len(week_px) < 3:
                    continue

                # Find actual Mon close (first trading day of week)
                mon_close = float(week_px.iloc[0])
                # Find actual Fri close (last trading day of week)
                fri_close = float(week_px.iloc[-1])
                # Day-by-day
                days      = week_px.index.tolist()
                closes    = week_px.values.tolist()

                # Return if entered Monday close, exit Friday close
                ret_mon_to_fri = round((fri_close - mon_close)/mon_close*100, 2)
                win_mon_to_fri = 1 if ret_mon_to_fri > 0 else 0

                # Return if entered at the signal-detected entry (Sunday close approx)
                # already in ret_1w

                # What day of week is the signal entry?
                entry_day_idx = days[0].weekday()  # 0=Mon, 4=Fri
                entry_day_name = days[0].strftime("%A")

                all_results.append({
                    "symbol":          sym,
                    "regime":          regime,
                    "period":          period,
                    "week":            row["week"],
                    "entry_1w":        entry,
                    "ret_1w_original": row["ret_1w"],
                    "win_1w_original": row["win_1w"],
                    "mon_close":       round(mon_close, 2),
                    "fri_close":       round(fri_close, 2),
                    "ret_mon_fri":     ret_mon_to_fri,
                    "win_mon_fri":     win_mon_to_fri,
                    "trading_days":    len(week_px),
                    "entry_weekday":   entry_day_name,
                    # Mid-week entry simulation: enter Wed close, exit Fri close
                    "wed_close":       round(float(week_px.iloc[2]) if len(week_px) >= 3 else mon_close, 2),
                    "ret_wed_fri":     round((fri_close - float(week_px.iloc[min(2, len(week_px)-1)]))/
                                       float(week_px.iloc[min(2, len(week_px)-1)])*100, 2) if len(week_px) >= 3 else 0,
                })

        except Exception as e:
            print(f"Error fetching {regime} {period}: {e}")

    return pd.DataFrame(all_results)


def analyze(df):
    print("="*65)
    print("WEEKDAY ENTRY ANALYSIS — Mon entry/Fri exit vs original")
    print("="*65)
    print(f"Total trades analyzed: {len(df)}")

    # Overall comparison
    print(f"\n--- OVERALL ---")
    print(f"Original signal (Sunday→Friday):")
    print(f"  Win rate: {df['win_1w_original'].mean()*100:.1f}%  "
          f"Avg ret: {df['ret_1w_original'].mean():+.2f}%")
    print(f"Mon open → Fri close (same week):")
    print(f"  Win rate: {df['win_mon_fri'].mean()*100:.1f}%  "
          f"Avg ret: {df['ret_mon_fri'].mean():+.2f}%")

    # By regime
    print(f"\n--- BY REGIME ---")
    for regime in ["BULL","CHOPPY","BEAR"]:
        r = df[df["regime"]==regime]
        if r.empty: continue
        print(f"\n{regime} ({len(r)} trades):")
        print(f"  Original:    win={r['win_1w_original'].mean()*100:.1f}%  "
              f"avg={r['ret_1w_original'].mean():+.2f}%")
        print(f"  Mon→Fri:     win={r['win_mon_fri'].mean()*100:.1f}%  "
              f"avg={r['ret_mon_fri'].mean():+.2f}%")
        # Wed entry
        print(f"  Wed→Fri:     avg={r['ret_wed_fri'].mean():+.2f}%")

    # By day of week — which entry day performs best?
    print(f"\n--- PERFORMANCE BY ENTRY DAY OF WEEK ---")
    print(f"(What day does the market actually open the week's trading)")
    for day in ["Monday","Tuesday","Wednesday","Thursday","Friday"]:
        d = df[df["entry_weekday"]==day]
        if len(d) < 5: continue
        print(f"  {day:<12}: {len(d):>4} trades | "
              f"win {d['win_mon_fri'].mean()*100:.1f}% | "
              f"avg {d['ret_mon_fri'].mean():+.2f}%")

    # Weekly pattern — does Mon-Fri return correlate with original?
    print(f"\n--- WEEKS WHERE MON→FRI > 1% (strong weekly trend) ---")
    strong = df[df["ret_mon_fri"] > 1.0]
    weak   = df[df["ret_mon_fri"] <= 0]
    print(f"  Strong weeks (Mon→Fri > 1%): {len(strong)}/{len(df)} "
          f"= {len(strong)/len(df)*100:.1f}%")
    print(f"    Original signal avg return in these weeks: "
          f"{strong['ret_1w_original'].mean():+.2f}%")
    print(f"  Flat/down weeks (Mon→Fri <= 0%): {len(weak)}/{len(df)} "
          f"= {len(weak)/len(df)*100:.1f}%")
    print(f"    Original signal avg return in these weeks: "
          f"{weak['ret_1w_original'].mean():+.2f}%")

    # The key question: does Mon→Fri return predict signal success?
    print(f"\n--- KEY FINDING: Mon start predicts signal outcome? ---")
    # If Mon→Fri is positive, how often does original signal win?
    pos_week = df[df["ret_mon_fri"] > 0]
    neg_week = df[df["ret_mon_fri"] <= 0]
    print(f"  When Mon→Fri positive ({len(pos_week)} weeks): "
          f"original signal wins {pos_week['win_1w_original'].mean()*100:.1f}% "
          f"avg {pos_week['ret_1w_original'].mean():+.2f}%")
    print(f"  When Mon→Fri negative ({len(neg_week)} weeks): "
          f"original signal wins {neg_week['win_1w_original'].mean()*100:.1f}% "
          f"avg {neg_week['ret_1w_original'].mean():+.2f}%")

    # Save
    df.to_csv("weekday_analysis_results.csv", index=False)
    print(f"\nSaved: weekday_analysis_results.csv")


def main():
    print("Loading trade data...")
    trades = pd.read_csv("extended_regime_results.csv")
    # Focus on S2 trades only — these are the ones we're trading
    s2 = trades[trades["sleeve"] == 2].copy()
    print(f"S2 trades: {len(s2)}")

    print("Mapping to signal dates...")
    meta = get_signal_dates(s2)

    print(f"Fetching weekday prices for {len(meta)} trades...")
    results = fetch_weekday_prices(meta)

    print(f"\nAnalyzing {len(results)} trades with weekday data...")
    analyze(results)
    print("\nDone.")

if __name__ == "__main__":
    main()
