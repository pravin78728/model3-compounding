"""
Extended Regime Backtest — 100+ trades per regime
==================================================
5 periods x 13 weeks per regime = ~65 weeks each
Target: 100+ trades per RSI/OBV filter bucket

Regimes:
  BULL:   Q2+Q3+Q4 2023, Q2 2024, Q2 2025
  CHOPPY: Q1+Q4 2022, Q1 2024, Q3 2025, Q3 2026
  BEAR:   Q2 2022, Q1 2023, Q4 2024, Q1+Q2 2025 (partial), Q1 2026

Usage:
    python extended_regime_backtest.py
"""

import os, json
import numpy as np
import pandas as pd
from datetime import date, timedelta, datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

LOOKBACK=20; SMA_PERIOD=50; RSI_PERIOD=14
RSI_THRESHOLD=60; RSI_MAX=80
VOL_SHORT=20; VOL_LONG=50
OBV_MIN_PCT=5.0; TRAIL_STOP=0.10

def sundays_in_range(start_str, end_str):
    """Return all Sundays between start and end dates."""
    start = datetime.strptime(start_str, "%Y-%m-%d")
    end   = datetime.strptime(end_str,   "%Y-%m-%d")
    sundays = []
    d = start
    while d <= end:
        if d.weekday() == 6:  # Sunday
            track_start = d + timedelta(days=1)
            track_end   = d + timedelta(days=5)
            if track_end <= end + timedelta(days=7):
                sundays.append({
                    "signal":      d.strftime("%Y-%m-%d"),
                    "track_start": track_start.strftime("%Y-%m-%d"),
                    "track_end":   track_end.strftime("%Y-%m-%d"),
                })
        d += timedelta(days=1)
    return sundays

REGIME_PERIODS = [
    # BULL periods
    {"regime": "BULL", "period": "Q2-2023", "start": "2023-04-01", "end": "2023-06-30"},
    {"regime": "BULL", "period": "Q3-2023", "start": "2023-07-01", "end": "2023-09-30"},
    {"regime": "BULL", "period": "Q4-2023", "start": "2023-10-01", "end": "2023-12-31"},
    {"regime": "BULL", "period": "Q2-2024", "start": "2024-04-01", "end": "2024-06-30"},
    {"regime": "BULL", "period": "Q2-2025", "start": "2025-04-06", "end": "2025-06-29"},
    # CHOPPY periods
    {"regime": "CHOPPY", "period": "Q1-2022", "start": "2022-01-03", "end": "2022-03-31"},
    {"regime": "CHOPPY", "period": "Q4-2022", "start": "2022-10-01", "end": "2022-12-31"},
    {"regime": "CHOPPY", "period": "Q1-2024", "start": "2024-01-01", "end": "2024-03-31"},
    {"regime": "CHOPPY", "period": "Q3-2025", "start": "2025-07-06", "end": "2025-09-28"},
    {"regime": "CHOPPY", "period": "Q3-2026", "start": "2026-07-06", "end": "2026-09-28"},
    # BEAR periods
    {"regime": "BEAR", "period": "Q2-2022", "start": "2022-04-01", "end": "2022-06-30"},
    {"regime": "BEAR", "period": "Q1-2023", "start": "2023-01-01", "end": "2023-03-31"},
    {"regime": "BEAR", "period": "Q4-2024", "start": "2024-10-01", "end": "2024-12-31"},
    {"regime": "BEAR", "period": "Q1-2025", "start": "2025-01-01", "end": "2025-03-31"},
    {"regime": "BEAR", "period": "Q1-2026", "start": "2026-01-05", "end": "2026-03-29"},
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
    c=df["close_price"].values; v=df["volume"].values
    o=np.zeros(len(c))
    for i in range(1,len(c)):
        o[i]=o[i-1]+v[i] if c[i]>c[i-1] else o[i-1]-v[i] if c[i]<c[i-1] else o[i-1]
    return pd.Series(o,index=df.index)

def compute_rsi(series,period=14):
    d=series.diff()
    g=d.clip(lower=0).ewm(alpha=1/period,min_periods=period,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(alpha=1/period,min_periods=period,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,np.nan)))

def run_screeners(symbol_data, signal_date_str):
    signal_date = pd.to_datetime(signal_date_str)
    sleeve1, sleeve2 = [], []
    for symbol, df in symbol_data.items():
        hist = df[df["date"] <= signal_date].copy().reset_index(drop=True)
        if len(hist) < max(SMA_PERIOD,VOL_LONG,RSI_PERIOD+10): continue
        hist["obv"]=compute_obv(hist); hist["rsi"]=compute_rsi(hist["close_price"])
        tc=hist["close_price"].iloc[-1]; to=hist["obv"].iloc[-1]
        tr=hist["rsi"].iloc[-1]; td=hist["date"].iloc[-1]
        if pd.isna(tr) or abs((td-signal_date).days)>5: continue
        prior_o=hist["obv"].iloc[-(LOOKBACK+1):-1]
        prior_c=hist["close_price"].iloc[-(LOOKBACK+1):-1]
        if len(prior_o)<LOOKBACK: continue
        obv_high=prior_o.max(); price_high=prior_c.max()
        av20=hist["volume"].iloc[-VOL_SHORT:].mean()
        av50=hist["volume"].iloc[-VOL_LONG:].mean()
        sma50=hist["close_price"].iloc[-SMA_PERIOD:].mean()
        obv_pct=round((to-obv_high)/abs(obv_high)*100 if obv_high!=0 else 0,1)
        obv_ok=to>obv_high and obv_pct>=OBV_MIN_PCT
        vol_ok=av20>=av50; sma_ok=tc>sma50
        if obv_ok and tc<=price_high and vol_ok and sma_ok:
            sleeve1.append({"symbol":symbol,"entry":round(tc,2),
                "obv_%":obv_pct,"gap_%":round((price_high-tc)/tc*100,2),
                "rsi":round(tr,1),"resistance":round(price_high,2),
                "pct_above_sma":round((tc/sma50-1)*100,1)})
        if obv_ok and tc>price_high and vol_ok and sma_ok and RSI_THRESHOLD<=tr<RSI_MAX:
            sleeve2.append({"symbol":symbol,"entry":round(tc,2),
                "obv_%":obv_pct,"break_%":round((tc-price_high)/price_high*100,2),
                "rsi":round(tr,1),"stop":round(tc*(1-TRAIL_STOP),2),
                "pct_above_sma":round((tc/sma50-1)*100,1)})
    s1=pd.DataFrame(sleeve1).sort_values("obv_%",ascending=False).reset_index(drop=True) if sleeve1 else pd.DataFrame()
    s2=pd.DataFrame(sleeve2).sort_values("obv_%",ascending=False).reset_index(drop=True) if sleeve2 else pd.DataFrame()
    return s1, s2

def track_signals(signals, symbol_data, track_start, track_end, sleeve, top_n=4):
    if signals.empty: return pd.DataFrame()
    picks=signals.head(top_n)
    t_start=pd.to_datetime(track_start); t_end=pd.to_datetime(track_end)
    results=[]
    for _,row in picks.iterrows():
        symbol=row["symbol"]; entry=row["entry"]
        stop=row.get("stop",entry*(1-TRAIL_STOP))
        if symbol not in symbol_data: continue
        df=symbol_data[symbol]
        week=df[(df["date"]>=t_start)&(df["date"]<=t_end)].copy()
        if week.empty: continue
        closes=week["close_price"].values
        peak=entry; stop_hit=False; exit_close=closes[-1]
        broke_res=False
        if sleeve==1: broke_res=any(c>row.get("resistance",entry) for c in closes)
        for i,c in enumerate(closes):
            if sleeve==2:
                if c>peak: peak=c; stop=peak*(1-TRAIL_STOP)
                if c<stop: stop_hit=True; exit_close=c; break
        final_ret=round((float(exit_close)-entry)/entry*100,2)
        max_gain=round((max(closes)-entry)/entry*100,2)
        max_dd=round((min(closes)-entry)/entry*100,2)
        r={"symbol":symbol,"entry":entry,"obv_%":row["obv_%"],"rsi":row["rsi"],
           "pct_above_sma":row.get("pct_above_sma",0),
           "final_ret_%":final_ret,"max_gain_%":max_gain,
           "max_dd_%":max_dd,"winner":1 if final_ret>0 else 0}
        if sleeve==1: r["gap_%"]=row["gap_%"]; r["broke_res"]=1 if broke_res else 0
        if sleeve==2: r["break_%"]=row.get("break_%",0); r["stop_hit"]=1 if stop_hit else 0
        results.append(r)
    return pd.DataFrame(results)

def deep_analysis(regime_name, s1_all, s2_all):
    """Find optimal filter combinations for 90%+ win rate."""
    print(f"\n{'='*65}")
    print(f"  DEEP ANALYSIS: {regime_name}")
    print(f"{'='*65}")

    for sleeve_name, trades in [("S1", s1_all), ("S2", s2_all)]:
        if trades.empty: continue
        total = len(trades)
        wins  = trades["winner"].sum()
        print(f"\n  {sleeve_name} — {total} trades — baseline {wins}/{total} = {wins/total*100:.1f}%  avg {trades['final_ret_%'].mean():+.2f}%")

        # RSI buckets (S2 only)
        if sleeve_name == "S2":
            print(f"\n  RSI breakdown:")
            for lo, hi in [(60,65),(65,70),(70,75),(75,80)]:
                f=trades[(trades["rsi"]>=lo)&(trades["rsi"]<hi)]
                if len(f)<5: continue
                w=f["winner"].sum(); t=len(f)
                print(f"    RSI {lo}-{hi}: {w}/{t} = {w/t*100:.1f}%  avg {f['final_ret_%'].mean():+.2f}%  ({t} trades)")

        # OBV buckets
        print(f"\n  OBV breakdown:")
        for obv_min in [5,10,20,50,100,200]:
            f=trades[trades["obv_%"]>=obv_min]
            if len(f)<5: continue
            w=f["winner"].sum(); t=len(f)
            print(f"    OBV>={obv_min:>4}%: {w}/{t} = {w/t*100:.1f}%  avg {f['final_ret_%'].mean():+.2f}%  ({t} trades)")

        # Gap buckets (S1 only)
        if sleeve_name == "S1":
            print(f"\n  Gap to resistance:")
            for gap in [1,2,3,5]:
                f=trades[trades["gap_%"]<=gap]
                if len(f)<5: continue
                w=f["winner"].sum(); t=len(f)
                print(f"    Gap<={gap}%: {w}/{t} = {w/t*100:.1f}%  avg {f['final_ret_%'].mean():+.2f}%  ({t} trades)")

        # Combined filters — search for 90%+
        print(f"\n  COMBINED FILTER SEARCH (target 90%+, min 10 trades):")
        best = []
        if sleeve_name == "S2":
            for rsi_lo,rsi_hi in [(60,65),(65,70),(70,75),(75,80),(70,80)]:
                for obv_min in [5,10,20,50,100]:
                    for top_n in [1,2,4]:
                        f=trades[(trades["rsi"]>=rsi_lo)&(trades["rsi"]<rsi_hi)&(trades["obv_%"]>=obv_min)]
                        # Simulate top_n per week
                        f=f.groupby("week").head(top_n)
                        if len(f)<8: continue
                        w=f["winner"].sum(); t=len(f)
                        rate=w/t*100
                        ret=f["final_ret_%"].mean()
                        if rate>=75:
                            best.append((rate,t,ret,f"RSI {rsi_lo}-{rsi_hi} + OBV>={obv_min}% + Top{top_n}"))
        if sleeve_name == "S1":
            for gap_max in [1,2,3]:
                for obv_min in [5,10,20,50]:
                    for top_n in [1,2,4]:
                        f=trades[(trades["gap_%"]<=gap_max)&(trades["obv_%"]>=obv_min)]
                        f=f.groupby("week").head(top_n)
                        if len(f)<8: continue
                        w=f["winner"].sum(); t=len(f)
                        rate=w/t*100
                        ret=f["final_ret_%"].mean()
                        if rate>=65:
                            best.append((rate,t,ret,f"Gap<={gap_max}% + OBV>={obv_min}% + Top{top_n}"))

        best.sort(reverse=True)
        for rate,t,ret,label in best[:8]:
            marker = "🏆" if rate>=90 else "✅" if rate>=80 else "  "
            print(f"    {marker} {label}: {rate:.1f}% ({t} trades) avg {ret:+.2f}%")
        if not best:
            print("    No combination above threshold found.")

def main():
    print("Extended Regime Backtest — 100+ trades per filter")
    print("="*65)
    print("5 periods x ~13 weeks per regime")

    # Check for existing results to resume
    results_file = "extended_regime_results.csv"
    if os.path.exists(results_file):
        existing = pd.read_csv(results_file)
        done = set(zip(existing["regime"], existing["period"]))
        print(f"Resuming — {len(done)} period(s) already done")
    else:
        existing = pd.DataFrame()
        done = set()

    all_trades = [existing] if not existing.empty else []

    for rp in REGIME_PERIODS:
        regime  = rp["regime"]
        period  = rp["period"]
        if (regime, period) in done:
            print(f"  Skipping {regime} {period} (done)")
            continue

        weeks = sundays_in_range(rp["start"], rp["end"])
        print(f"\n{regime} {period} ({len(weeks)} weeks):")

        period_trades = []
        for i, week in enumerate(weeks):
            print(f"  W{i+1:02d} {week['signal']}...", end=" ", flush=True)
            try:
                symbol_data = fetch_week_data(week["signal"])
                s1, s2 = run_screeners(symbol_data, week["signal"])
                s1_res = track_signals(s1, symbol_data, week["track_start"], week["track_end"], sleeve=1, top_n=4)
                s2_res = track_signals(s2, symbol_data, week["track_start"], week["track_end"], sleeve=2, top_n=4)
                s1w=s1_res["winner"].sum() if not s1_res.empty else 0
                s2w=s2_res["winner"].sum() if not s2_res.empty else 0
                s1t=len(s1_res); s2t=len(s2_res)
                print(f"S1:{s1w}/{s1t}  S2:{s2w}/{s2t}")
                for res, sl in [(s1_res,1),(s2_res,2)]:
                    if not res.empty:
                        res["regime"]=regime; res["period"]=period
                        res["week"]=f"W{i+1:02d}"; res["sleeve"]=sl
                        period_trades.append(res)
            except Exception as e:
                print(f"ERROR: {e}")

        if period_trades:
            period_df = pd.concat(period_trades, ignore_index=True)
            all_trades.append(period_df)
            # Save checkpoint
            pd.concat(all_trades, ignore_index=True).to_csv(results_file, index=False)
            w=period_df["winner"].sum(); t=len(period_df)
            print(f"  Period total: {w}/{t} = {w/t*100:.1f}%  avg {period_df['final_ret_%'].mean():+.2f}%")

    # Full analysis
    if not all_trades:
        print("No data.")
        return

    full = pd.concat(all_trades, ignore_index=True)
    full.to_csv(results_file, index=False)
    print(f"\nTotal trades saved: {len(full)}")

    # Deep analysis per regime
    for regime in ["BULL","CHOPPY","BEAR"]:
        rdf = full[full["regime"]==regime]
        if rdf.empty: continue
        s1 = rdf[rdf["sleeve"]==1].copy()
        s2 = rdf[rdf["sleeve"]==2].copy()
        print(f"\n{regime}: {len(s1)} S1 trades, {len(s2)} S2 trades")
        deep_analysis(regime, s1, s2)

    # Final summary table
    print(f"\n\n{'='*65}")
    print("FINAL OPTIMAL CRITERIA — USE THIS IN WEEKLY MASTER")
    print(f"{'='*65}")
    for regime in ["BULL","CHOPPY","BEAR"]:
        rdf = full[full["regime"]==regime]
        if rdf.empty: continue
        print(f"\n{regime}:")
        for sleeve, sname in [(1,"S1"),(2,"S2")]:
            sdf = rdf[rdf["sleeve"]==sleeve]
            if sdf.empty: continue
            w=sdf["winner"].sum(); t=len(sdf)
            print(f"  {sname} baseline: {w}/{t} = {w/t*100:.1f}%  avg {sdf['final_ret_%'].mean():+.2f}%")

    print("\nDone.")

if __name__ == "__main__":
    main()
