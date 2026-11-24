"""
Daily Signal Check — Model 2 Sleeve 2
======================================
Run any day to find today's qualifying S2 signals.
Applies regime-specific proven criteria:

  BULL:   RSI 70-75 + OBV >= 50% + Top 1  |  5% stop  |  hold 5 trading days
  CHOPPY: RSI 75-80 + OBV >= 20% + Top 1  |  4% stop  |  hold 5 trading days
  BEAR:   Both sleeves OFF

Expected performance (from 757-trade backtest):
  BULL:   58.9% win rate, +3.55% avg, R/R 1.83:1
  CHOPPY: 67.6% win rate, +4.46% avg, R/R 2.54:1

Usage:
    python daily_check.py              # check today, print to terminal
    python daily_check.py --email      # check today, email if signals found
    python daily_check.py --date 2026-11-15  # check specific date
"""

import os
import sys
import numpy as np
import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
EMAIL_TO     = "pravin.borade@gmail.com"
EMAIL_FROM   = os.getenv("EMAIL_FROM", "")
EMAIL_PASS   = os.getenv("EMAIL_PASS", "")

def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True,
                        connect_args={"connect_timeout": 30})

# ── Signal parameters ─────────────────────────────────────────────────────────
LOOKBACK      = 20
SMA_PERIOD    = 50
RSI_PERIOD    = 14
VOL_SHORT     = 20
VOL_LONG      = 50
TRAIL_STOP    = 0.10
FETCH_DAYS    = 400

# ── Regime-specific criteria (from backtest) ──────────────────────────────────
CRITERIA = {
    "BULL":   {"rsi_lo": 70, "rsi_hi": 75, "obv_min": 50, "stop_pct": 5.0,
               "win_rate": 58.9, "avg_ret": 3.55, "rr": 1.83},
    "CHOPPY": {"rsi_lo": 75, "rsi_hi": 80, "obv_min": 20, "stop_pct": 4.0,
               "win_rate": 67.6, "avg_ret": 4.46, "rr": 2.54},
    "BEAR":   None,
}


# ── Regime check ──────────────────────────────────────────────────────────────
def get_regime(engine, as_of_date):
    cutoff = (as_of_date - timedelta(days=400)).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT date, close_price FROM prices
            WHERE symbol = 'NIFTY500_IDX'
            AND date <= :asof AND date >= :cutoff
            ORDER BY date DESC
        """), conn, params={"asof": as_of_date.strftime("%Y-%m-%d"), "cutoff": cutoff})
    if df.empty:
        return "UNKNOWN", None, None, None
    df["date"] = pd.to_datetime(df["date"]).dt.date
    rows    = list(zip(df["date"], df["close_price"]))
    rd, p_now = rows[0]
    p_200   = [p for d,p in rows if d >= rd - timedelta(days=280)]
    p_12m   = next((p for d,p in rows if d <= rd - timedelta(days=240)), None)
    dma200  = np.mean(p_200) if p_200 else None
    if dma200 and p_12m:
        vs_dma = round((p_now/dma200-1)*100, 1)
        vs_12m = round((p_now/p_12m-1)*100, 1)
        if p_now > dma200*1.03 and p_now > p_12m*1.05:
            regime = "BULL"
        elif p_now < dma200*0.97 and p_now < p_12m*0.95:
            regime = "BEAR"
        else:
            regime = "CHOPPY"
        return regime, round(p_now,1), vs_dma, vs_12m
    return "UNKNOWN", None, None, None


# ── Fetch price data ──────────────────────────────────────────────────────────
def fetch_data(engine, as_of_date):
    cutoff = (as_of_date - timedelta(days=FETCH_DAYS)).strftime("%Y-%m-%d")
    asof   = as_of_date.strftime("%Y-%m-%d")
    recent = (as_of_date - timedelta(days=10)).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT symbol, date, close_price, volume
            FROM prices
            WHERE date BETWEEN :cutoff AND :asof
            AND symbol IN (
                SELECT DISTINCT symbol FROM prices
                WHERE date >= :recent AND volume IS NOT NULL
            )
            ORDER BY symbol, date ASC
        """), conn, params={"cutoff": cutoff, "asof": asof, "recent": recent})
    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce")
    df = df.dropna(subset=["close_price"])
    df["volume"] = df.groupby("symbol")["volume"].transform(
        lambda x: x.ffill().fillna(0))
    return {sym: grp.reset_index(drop=True) for sym, grp in df.groupby("symbol")}


# ── Fetch delivery % + 5-day trend for a list of symbols ─────────────────────
def fetch_delivery(engine, symbols, as_of_date):
    """
    Returns dict: symbol -> {
        today:    delivery % on signal date,
        avg_20d:  20-day average delivery %,
        trend_5d: list of last 5 daily delivery % values (oldest first),
        trend_str: human readable trend e.g. "55% → 48% → 62% → 31% → 19% ↓"
    }
    """
    if not symbols:
        return {}
    asof   = as_of_date.strftime("%Y-%m-%d")
    cutoff = (as_of_date - timedelta(days=40)).strftime("%Y-%m-%d")
    with get_engine().connect() as conn:
        df = pd.read_sql(text("""
            SELECT symbol, date, delivery_pct
            FROM prices
            WHERE symbol = ANY(:syms)
            AND date BETWEEN :cutoff AND :asof
            AND delivery_pct IS NOT NULL
            ORDER BY symbol, date ASC
        """), conn, params={"syms": list(symbols), "cutoff": cutoff, "asof": asof})
    if df.empty:
        return {}
    df["date"]         = pd.to_datetime(df["date"])
    df["delivery_pct"] = pd.to_numeric(df["delivery_pct"], errors="coerce")
    result = {}
    for sym, grp in df.groupby("symbol"):
        grp      = grp.sort_values("date").dropna(subset=["delivery_pct"])
        today    = round(float(grp["delivery_pct"].iloc[-1]), 1) if not grp.empty else None
        avg_20d  = round(float(grp["delivery_pct"].tail(20).mean()), 1) if not grp.empty else None
        last5    = grp["delivery_pct"].tail(5).tolist()
        # Trend arrow: compare today vs 5-day avg
        if len(last5) >= 2:
            direction = "↑" if last5[-1] > last5[-2] else "↓" if last5[-1] < last5[-2] else "→"
        else:
            direction = ""
        trend_str = " → ".join(f"{v:.0f}%" for v in last5) + f" {direction}"
        result[sym] = {
            "today":     today,
            "avg_20d":   avg_20d,
            "trend_5d":  last5,
            "trend_str": trend_str,
        }
    return result


# ── Fetch FII ownership % from institutional_holdings ────────────────────────
def fetch_fii_ownership(engine, symbols, as_of_date):
    """
    Returns dict: symbol -> (fii_pct, dii_pct, period)
    Uses most recent quarterly holding before as_of_date.
    """
    if not symbols:
        return {}
    asof = as_of_date.strftime("%Y-%m-%d")
    with get_engine().connect() as conn:
        df = pd.read_sql(text("""
            SELECT DISTINCT ON (symbol)
                symbol, period, fii_pct, dii_pct
            FROM institutional_holdings
            WHERE symbol = ANY(:syms)
            AND period <= :asof
            ORDER BY symbol, period DESC
        """), conn, params={"syms": list(symbols), "asof": asof})
    if df.empty:
        return {}
    result = {}
    for _, row in df.iterrows():
        result[row["symbol"]] = {
            "fii_pct": round(float(row["fii_pct"]), 1) if row["fii_pct"] else None,
            "dii_pct": round(float(row["dii_pct"]), 1) if row["dii_pct"] else None,
            "period":  str(row["period"]),
        }
    return result


# ── OBV & RSI ─────────────────────────────────────────────────────────────────
def compute_obv(df):
    c=df["close_price"].values; v=df["volume"].values
    o=np.zeros(len(c))
    for i in range(1,len(c)):
        o[i]=o[i-1]+v[i] if c[i]>c[i-1] else o[i-1]-v[i] if c[i]<c[i-1] else o[i-1]
    return pd.Series(o,index=df.index)

def compute_rsi(series, period=14):
    d=series.diff()
    g=d.clip(lower=0).ewm(alpha=1/period,min_periods=period,adjust=False).mean()
    l=(-d.clip(upper=0)).ewm(alpha=1/period,min_periods=period,adjust=False).mean()
    return 100-(100/(1+g/l.replace(0,np.nan)))


# ── Run S2 screener with regime-specific criteria ─────────────────────────────
def run_s2_screener(symbol_data, as_of_date, criteria):
    rsi_lo  = criteria["rsi_lo"]
    rsi_hi  = criteria["rsi_hi"]
    obv_min = criteria["obv_min"]
    signals = []

    for symbol, df in symbol_data.items():
        hist = df[df["date"] <= pd.Timestamp(as_of_date)].copy().reset_index(drop=True)
        if len(hist) < max(SMA_PERIOD, VOL_LONG, RSI_PERIOD+10):
            continue
        hist["obv"] = compute_obv(hist)
        hist["rsi"] = compute_rsi(hist["close_price"])
        tc = hist["close_price"].iloc[-1]
        to = hist["obv"].iloc[-1]
        tr = hist["rsi"].iloc[-1]
        td = hist["date"].iloc[-1]
        if pd.isna(tr) or abs((td - pd.Timestamp(as_of_date)).days) > 3:
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
        obv_pct    = round((to-obv_high)/abs(obv_high)*100 if obv_high!=0 else 0, 1)

        # S2 conditions
        obv_ok  = to > obv_high and obv_pct >= obv_min
        vol_ok  = av20 >= av50
        sma_ok  = tc > sma50
        rsi_ok  = rsi_lo <= tr < rsi_hi
        price_ok = tc > price_high

        if obv_ok and vol_ok and sma_ok and rsi_ok and price_ok:
            stop_pct  = criteria["stop_pct"]
            stop      = round(tc * (1 - stop_pct/100), 2)
            brk_pct   = round((tc - price_high)/price_high*100, 2)
            # 52w context
            w52       = hist["close_price"].iloc[-252:].max() if len(hist)>=252 else hist["close_price"].max()
            gap_52w   = round((w52-tc)/tc*100, 1)
            # Volume spike detection
            today_vol = hist["volume"].iloc[-1]
            avg_vol   = hist["volume"].iloc[-21:-1].mean()  # 20-day avg excluding today
            vol_spike = round(today_vol / avg_vol, 1) if avg_vol > 0 else 0
            # Liquidity — 20-day avg daily traded value in Cr
            # = avg(volume × close_price) / 1,00,00,000
            hist["traded_value"] = hist["close_price"] * hist["volume"]
            avg_traded_cr = round(
                hist["traded_value"].iloc[-21:-1].mean() / 1e7, 2
            ) if len(hist) >= 21 else round(
                hist["traded_value"].mean() / 1e7, 2
            )
            signals.append({
                "symbol":       symbol,
                "close":        round(tc, 2),
                "rsi":          round(tr, 1),
                "obv_%":        obv_pct,
                "break_%":      brk_pct,
                "stop":         stop,
                "stop_pct":     stop_pct,
                "gap_52w_%":    gap_52w,
                "sma50":        round(sma50, 2),
                "vol_spike":    vol_spike,
                "today_vol":    int(today_vol),
                "avg_vol_20d":  int(avg_vol),
                "liquidity_cr": avg_traded_cr,
            })

    if not signals:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df_out = pd.DataFrame(signals).sort_values("obv_%", ascending=False).reset_index(drop=True)
    syms   = df_out["symbol"].tolist()

    # Fetch delivery % with 5-day trend
    engine       = get_engine()
    delivery_map = fetch_delivery(engine, syms, as_of_date)
    df_out["delivery_today_%"] = df_out["symbol"].map(
        lambda s: delivery_map[s]["today"]     if s in delivery_map else None)
    df_out["delivery_20d_%"]   = df_out["symbol"].map(
        lambda s: delivery_map[s]["avg_20d"]   if s in delivery_map else None)
    df_out["delivery_trend"]   = df_out["symbol"].map(
        lambda s: delivery_map[s]["trend_str"] if s in delivery_map else "N/A")

    # Fetch FII/DII quarterly ownership
    fii_map = fetch_fii_ownership(engine, syms, as_of_date)
    df_out["fii_pct"]    = df_out["symbol"].map(
        lambda s: fii_map[s]["fii_pct"] if s in fii_map else None)
    df_out["dii_pct"]    = df_out["symbol"].map(
        lambda s: fii_map[s]["dii_pct"] if s in fii_map else None)
    df_out["fii_period"] = df_out["symbol"].map(
        lambda s: fii_map[s]["period"]  if s in fii_map else None)

    DELIVERY_MIN  = 40.0
    VOL_SPIKE_MAX = 5.0
    LIQUIDITY_MIN = 10.0   # minimum ₹10 Cr avg daily traded value

    # Flags
    df_out["vol_spike_flag"]    = df_out["vol_spike"] >= VOL_SPIKE_MAX
    df_out["liquidity_fail"]    = df_out["liquidity_cr"] < LIQUIDITY_MIN

    # Split into 4 buckets:
    # passed:        delivery >= 40% AND no vol spike AND liquidity >= 10 Cr
    # warned:        delivery NULL OR vol spike (but delivery not < 40% and liquidity ok)
    # liq_failed:    liquidity < 10 Cr (regardless of delivery)
    # del_failed:    delivery < 40%
    del_ok        = df_out["delivery_today_%"].notna() & (df_out["delivery_today_%"] >= DELIVERY_MIN)
    del_fail      = df_out["delivery_today_%"].notna() & (df_out["delivery_today_%"] < DELIVERY_MIN)
    del_null      = df_out["delivery_today_%"].isna()
    vol_spike_f   = df_out["vol_spike_flag"]
    liq_fail      = df_out["liquidity_fail"]

    # Liquidity fail takes priority over other buckets
    liq_failed = df_out[liq_fail].reset_index(drop=True)
    remaining  = df_out[~liq_fail]

    del_ok_r   = remaining["delivery_today_%"].notna() & (remaining["delivery_today_%"] >= DELIVERY_MIN)
    del_fail_r = remaining["delivery_today_%"].notna() & (remaining["delivery_today_%"] < DELIVERY_MIN)
    del_null_r = remaining["delivery_today_%"].isna()
    vol_spike_r = remaining["vol_spike_flag"]

    passed = remaining[del_ok_r & ~vol_spike_r].reset_index(drop=True)
    warned = remaining[(del_null_r | vol_spike_r) & ~del_fail_r].reset_index(drop=True)
    failed = remaining[del_fail_r].reset_index(drop=True)

    return passed, warned, failed, liq_failed


# ── Format output ─────────────────────────────────────────────────────────────
def format_output(regime, nifty, vs_dma, vs_12m, signals, signals_warn, signals_fail, signals_liq, criteria, check_date):
    regime_emoji = {"BULL":"🟢","CHOPPY":"🟡","BEAR":"🔴"}.get(regime,"⚪")
    lines = []
    lines.append(f"DAILY SIGNAL CHECK — {check_date.strftime('%A %d %b %Y')}")
    lines.append("="*55)
    lines.append(f"\n{regime_emoji} REGIME: {regime} | Nifty500: {nifty} | vs 200-DMA: {vs_dma}% | vs 12m: {vs_12m}%")

    if regime == "BEAR":
        lines.append("\n⛔ BEAR regime — both sleeves OFF. No new positions.")
        lines.append("="*55)
        return "\n".join(lines), False

    if regime == "UNKNOWN":
        lines.append("\n⚠️  Regime unknown — check NIFTY500_IDX data.")
        return "\n".join(lines), False

    c = criteria[regime]
    lines.append(f"\nApplying {regime} criteria:")
    lines.append(f"  RSI {c['rsi_lo']}-{c['rsi_hi']} + OBV >= {c['obv_min']}% | Top 2 shown, ranked by OBV strength")
    lines.append(f"  Expected: {c['win_rate']}% win rate, +{c['avg_ret']}% avg return, {c['rr']}:1 R/R")
    lines.append(f"  Stop loss: {c['stop_pct']}% | Hold: 5 trading days")

    if signals.empty:
        lines.append(f"\n  No qualifying signals today.")
        lines.append(f"  Criteria not met by any stock — skip this day.")
        lines.append("="*55)
        return "\n".join(lines), False

    # Calculate actual 5 trading days forward (skip weekends)
    trading_days = 0
    exit_date = check_date
    while trading_days < 5:
        exit_date += timedelta(days=1)
        if exit_date.weekday() < 5:  # Mon-Fri only
            trading_days += 1

    # Allocation rules from backtest by rank
    # BULL:   Rank1=60%, Rank2=40%, Rank3+=skip
    # CHOPPY: Rank1=100%, Rank2=100% only if rank1 fails checklist
    ALLOC = {
        "BULL":   {1: ("60%", "PRIMARY"),   2: ("40%", "SECONDARY"), 3: ("SKIP", "SKIP")},
        "CHOPPY": {1: ("100%", "PRIMARY"),  2: ("100%", "IF RANK 1 FAILS CHECKLIST")},
    }
    alloc_map = ALLOC.get(regime, {})

    # Cap at rank 2 for BULL, rank 2 for CHOPPY (rank 3+ skip in all regimes)
    max_rank = 2
    show_signals = signals.iloc[:max_rank]

    lines.append(f"\n{'─'*55}")
    lines.append(f"  {len(signals)} qualifying signal(s) today | Showing top {len(show_signals)}")
    lines.append(f"{'─'*55}")

    # Show summary table first
    lines.append(f"\n  SIGNAL SUMMARY:")
    lines.append(f"  {'Rank':<6} {'Symbol':<14} {'Alloc':<8} {'Entry':>8} {'Stop':>8} {'RSI':>6} {'OBV%':>8} {'Del%':>6} {'Liq(Cr)':>9}")
    lines.append(f"  {'─'*73}")
    for rank, (_, row) in enumerate(show_signals.iterrows(), 1):
        alloc_info = alloc_map.get(rank, ("SKIP", "SKIP"))
        alloc_pct  = alloc_info[0]
        if alloc_pct == "SKIP":
            continue
        del_today = row.get("delivery_today_%", None)
        del_str   = f"{del_today:.0f}%" if del_today is not None else "N/A"
        liq_cr    = row.get("liquidity_cr", 0)
        lines.append(f"  #{rank:<5} {row['symbol']:<14} {alloc_pct:<8} ₹{row['close']:>7} ₹{row['stop']:>7} {row['rsi']:>6.1f} {row['obv_%']:>7.1f}% {del_str:>6} ₹{liq_cr:>7.1f}Cr")

    # Backtest context
    lines.append(f"\n  BACKTEST CONTEXT ({regime}):")
    if regime == "BULL":
        lines.append(f"  Rank 1: 63.0% win rate, +3.93% avg → allocate 60% of trade capital")
        lines.append(f"  Rank 2: 47.8% win rate, +4.12% avg → allocate 40% of trade capital")
        lines.append(f"  Rank 3+: 28.6% win rate — skip entirely")
    elif regime == "CHOPPY":
        lines.append(f"  Rank 1: 67.6% win rate, +4.46% avg → full allocation")
        lines.append(f"  Rank 2: 50.0% win rate, +4.07% avg → only if Rank 1 fails checklist")

    # Per-stock detail + checklist
    for rank, (_, row) in enumerate(show_signals.iterrows(), 1):
        alloc_info = alloc_map.get(rank, ("SKIP", "SKIP"))
        alloc_pct, alloc_role = alloc_info
        if alloc_pct == "SKIP":
            lines.append(f"\n  Rank {rank}+ signals below threshold — skip.")
            break

        screener_url = f"https://www.screener.in/company/{row['symbol']}/"
        lines.append(f"\n{'═'*55}")
        lines.append(f"  RANK {rank} — {row['symbol']} | {alloc_role} | {alloc_pct} of capital")
        lines.append(f"{'═'*55}")
        lines.append(f"  Entry:      ₹{row['close']} (today's close)")
        lines.append(f"  Stop loss:  ₹{row['stop']} ({row['stop_pct']}% below entry)")
        lines.append(f"  Exit:       ~{exit_date.strftime('%d %b %Y')} (5 trading days)")
        lines.append(f"  RSI:        {row['rsi']} (in {c['rsi_lo']}-{c['rsi_hi']} zone)")
        lines.append(f"  OBV:        {row['obv_%']}% above 20d high")
        lines.append(f"  Breakout:   {row['break_%']}% above 20d resistance")
        lines.append(f"  52w wall:   {row['gap_52w_%']}% above current price")
        # Delivery
        del_today = row.get("delivery_today_%", None)
        del_20d   = row.get("delivery_20d_%", None)
        del_trend = row.get("delivery_trend", "N/A")
        del_today_str = f"{del_today:.0f}%" if del_today is not None else "N/A"
        del_20d_str   = f"{del_20d:.0f}%"   if del_20d   is not None else "N/A"
        liq_cr = row.get("liquidity_cr", 0)
        lines.append(f"  Liquidity:  ₹{liq_cr:.1f} Cr avg daily traded value  ✅ PASS (>=₹10 Cr)")
        lines.append(f"  Delivery:   {del_today_str} today | {del_20d_str} 20d avg  ✅ PASS (>=40%)")
        lines.append(f"  Del trend:  {del_trend} (5-day history)")
        vol_spike = row.get("vol_spike", 0)
        avg_vol   = row.get("avg_vol_20d", 0)
        today_vol = row.get("today_vol", 0)
        if vol_spike and vol_spike >= 5:
            lines.append(f"  Volume:     {today_vol:,} today | {avg_vol:,} 20d avg | {vol_spike}x spike ⚠️")
        else:
            lines.append(f"  Volume:     {today_vol:,} today | {avg_vol:,} 20d avg | {vol_spike}x (normal)")
        # FII/DII ownership
        fii_pct    = row.get("fii_pct", None)
        dii_pct    = row.get("dii_pct", None)
        fii_period = row.get("fii_period", "")
        if fii_pct is not None:
            fii_flag = " ⚠️  HIGH — sensitive to FII sector rotation" if fii_pct >= 40 else ""
            lines.append(f"  FII owned:  {fii_pct}% | DII owned: {dii_pct}% (as of {fii_period}){fii_flag}")
            lines.append(f"  FII note:   {'Check FII sector flow carefully — large FII holder' if fii_pct >= 40 else 'FII ownership moderate — less sensitive to sector rotation'}")
        else:
            lines.append(f"  FII owned:  Not available — check Screener shareholding")
        lines.append(f"  Screener:   {screener_url}")

        lines.append(f"\n  PRE-TRADE CHECKLIST:")
        lines.append(f"  [ ] 1. EARNINGS    — No results due before {exit_date.strftime('%d %b')}")
        lines.append(f"                       Check: Screener quarterly dates or NSE announcements")
        lines.append(f"  [ ] 2. PLEDGE      — Promoter pledge below 15%")
        lines.append(f"                       Check: Screener > Shareholding > Pledged %")
        lines.append(f"  [ ] 3. FII FLOW    — FIIs net buying in this sector (last 3 days)")
        lines.append(f"                       FII ownership % shown above. Check NSE India for daily sector flow")
        lines.append(f"  [ ] 4. MACRO       — No RBI/Budget/Fed event in next 5 days")
        lines.append(f"                       Check: NSE events or economic calendar")
        lines.append(f"  [ ] 5. NEWS        — No negative news today")
        lines.append(f"                       Check: Google '{row['symbol']} NSE news today'")
        lines.append(f"  [ ] 6. GLOBAL      — S&P 500/Nasdaq not down >1.5% last night")
        lines.append(f"                       Check: Google 'S&P 500 yesterday close'")
        lines.append(f"")
        lines.append(f"  All 6 passed → ENTER ₹{row['close']} | Stop ₹{row['stop']} | Exit {exit_date.strftime('%d %b')}")
        lines.append(f"  Any failed   → SKIP this rank, check next rank signal")

    # Liquidity-failed signals
    if not signals_liq.empty:
        lines.append(f"\n{'─'*55}")
        lines.append(f"  ⛔ SIGNALS BLOCKED — LOW LIQUIDITY")
        lines.append(f"  (Below ₹10 Cr avg daily traded value — exit risk)")
        lines.append(f"{'─'*55}")
        for _, row in signals_liq.iterrows():
            liq_cr    = row.get("liquidity_cr", 0)
            del_today = row.get("delivery_today_%", None)
            del_str   = f"{del_today:.0f}%" if del_today is not None else "N/A"
            lines.append(f"")
            lines.append(f"  ⛔ {row['symbol']}  |  RSI {row['rsi']} | OBV {row['obv_%']}% | Delivery {del_str}")
            lines.append(f"     Avg daily traded value: ₹{liq_cr:.2f} Cr  ← BELOW ₹10 Cr threshold")
            lines.append(f"     Approx daily volume: {row.get('avg_vol_20d',0):,} shares × ₹{row['close']:.0f} = ₹{liq_cr:.1f}Cr")
            lines.append(f"     Risk: Cannot exit position without moving the price against you")

    # Warned signals — NULL delivery or volume spike
    if not signals_warn.empty:
        lines.append(f"\n{'─'*55}")
        lines.append(f"  ⚠️  SIGNALS REQUIRING EXTRA CAUTION")
        lines.append(f"  (Passed model criteria but delivery unconfirmed or volume spike)")
        lines.append(f"{'─'*55}")
        for _, row in signals_warn.iterrows():
            del_today  = row.get("delivery_today_%", None)
            vol_spike  = row.get("vol_spike", 0)
            avg_vol    = row.get("avg_vol_20d", 0)
            today_vol  = row.get("today_vol", 0)
            del_trend  = row.get("delivery_trend", "N/A")
            fii_pct    = row.get("fii_pct", None)
            fii_str    = f"{fii_pct:.0f}% FII owned" if fii_pct is not None else "FII% unknown"
            lines.append(f"")
            lines.append(f"  ⚠ {row['symbol']}  |  RSI {row['rsi']} | OBV {row['obv_%']}% | {fii_str}")
            if del_today is None:
                lines.append(f"    Delivery today: NOT YET AVAILABLE — NSE delivery data delayed")
                lines.append(f"    Delivery 20d avg: {row.get('delivery_20d_%', 'N/A')}%")
                lines.append(f"    Delivery trend:  {del_trend}")
                lines.append(f"    Action: CHECK delivery on NSE/Trendlyne before entering")
                lines.append(f"             If delivery < 40% → SKIP")
            if vol_spike and vol_spike >= 5:
                lines.append(f"    Volume spike:   {today_vol:,} today vs {avg_vol:,} avg = {vol_spike}x normal volume")
                lines.append(f"    Action: VERIFY — extreme volume spike may indicate news/event")
                lines.append(f"             Check news before entering. If no fundamental reason → SKIP")

    # Delivery-failed signals section
    if not signals_fail.empty:
        lines.append(f"\n{'─'*55}")
        lines.append(f"  ⚠️  SIGNALS FOUND BUT SKIPPED — LOW DELIVERY %")
        lines.append(f"  (Met all model criteria but delivery below 40% threshold)")
        lines.append(f"{'─'*55}")
        for _, row in signals_fail.iterrows():
            del_today  = row.get("delivery_today_%", None)
            del_20d    = row.get("delivery_20d_%", None)
            del_trend  = row.get("delivery_trend", "N/A")
            fii_pct    = row.get("fii_pct", None)
            del_today_str = f"{del_today:.0f}%" if del_today is not None else "N/A"
            del_20d_str   = f"{del_20d:.0f}%"   if del_20d   is not None else "N/A"
            fii_str       = f"{fii_pct:.0f}% FII owned" if fii_pct is not None else "FII% unknown"
            lines.append(f"")
            lines.append(f"  ✗ {row['symbol']}  |  RSI {row['rsi']} | OBV {row['obv_%']}% | {fii_str}")
            lines.append(f"    Delivery today: {del_today_str}  ← BELOW 40% threshold → SKIP")
            lines.append(f"    Delivery 20d avg: {del_20d_str}")
            lines.append(f"    Delivery 5d trend: {del_trend}")
            lines.append(f"    Reason: OBV spike driven by speculative intraday volume, not institutional buying")

    lines.append(f"\n{'='*55}")
    return "\n".join(lines), True


def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_PASS:
        return False
    try:
        msg            = MIMEMultipart()
        msg["From"]    = EMAIL_FROM
        msg["To"]      = EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


def main():
    # Parse args
    send_mail  = "--email" in sys.argv
    check_date = date.today()
    for arg in sys.argv:
        if arg.startswith("--date="):
            check_date = date.fromisoformat(arg.split("=")[1])
        elif len(arg) == 10 and arg[4] == "-":
            try:
                check_date = date.fromisoformat(arg)
            except:
                pass

    print(f"Daily Signal Check — {check_date.strftime('%A %d %b %Y')}")
    print("-"*40)

    engine = get_engine()

    print("Checking regime...", end=" ")
    regime, nifty, vs_dma, vs_12m = get_regime(engine, check_date)
    print(f"{regime} | Nifty500: {nifty} | vs 200-DMA: {vs_dma}% | vs 12m: {vs_12m}%")

    if regime == "BEAR":
        print("⛔ BEAR regime — both sleeves OFF.")
        if send_mail:
            send_email(f"🔴 BEAR Regime | No signals | {check_date}", 
                      f"Market in BEAR regime. Both sleeves OFF.\nNifty500: {nifty} | vs 200-DMA: {vs_dma}% | vs 12m: {vs_12m}%")
        return

    criteria = CRITERIA.get(regime)
    if not criteria:
        print("Unknown regime — cannot apply criteria.")
        return

    print(f"Fetching data ({regime} criteria: RSI {criteria['rsi_lo']}-{criteria['rsi_hi']}, OBV>={criteria['obv_min']}%)...", end=" ")
    symbol_data = fetch_data(engine, check_date)
    print(f"{len(symbol_data)} symbols")

    print("Scanning for signals...")
    signals_pass, signals_warn, signals_fail, signals_liq = run_s2_screener(symbol_data, check_date, criteria)

    output, has_signals = format_output(regime, nifty, vs_dma, vs_12m,
                                        signals_pass, signals_warn, signals_fail, signals_liq, CRITERIA, check_date)

    print("\n" + output)

    if send_mail:
        regime_emoji = {"BULL":"🟢","CHOPPY":"🟡","BEAR":"🔴"}.get(regime,"⚪")
        if has_signals:
            top_symbol = signals_pass.iloc[0]["symbol"]
            subject = f"{regime_emoji} SIGNAL: {top_symbol} | {regime} | {check_date.strftime('%d %b %Y')}"
        elif not signals_warn.empty:
            subject = f"{regime_emoji} ⚠️ Signals need verification | {regime} | {check_date.strftime('%d %b %Y')}"
        elif not signals_liq.empty or not signals_fail.empty:
            subject = f"{regime_emoji} Signals blocked by filters | {regime} | {check_date.strftime('%d %b %Y')}"
        else:
            subject = f"{regime_emoji} No signals today | {regime} | {check_date.strftime('%d %b %Y')}"
        sent = send_email(subject, output)
        if sent:
            print(f"Email sent to {EMAIL_TO}")
        else:
            print("Email not configured — output printed above only.")

    # Save to log
    top = signals_pass.iloc[0] if not signals_pass.empty else (signals_warn.iloc[0] if not signals_warn.empty else (signals_fail.iloc[0] if not signals_fail.empty else None))
    log_entry = {
        "date":       check_date.isoformat(),
        "regime":     regime,
        "nifty":      nifty,
        "signals_pass": len(signals_pass),
        "signals_warn": len(signals_warn),
        "signals_fail": len(signals_fail),
        "signals_liq":  len(signals_liq),
        "top_pick":   top["symbol"] if top is not None else "",
        "top_close":  top["close"]  if top is not None else "",
        "top_stop":   top["stop"]   if top is not None else "",
        "top_rsi":    top["rsi"]    if top is not None else "",
        "top_obv":    top["obv_%"]  if top is not None else "",
        "top_del":    top["delivery_today_%"] if top is not None else "",
    }
    log_df = pd.DataFrame([log_entry])
    log_file = "daily_check_log.csv"
    if os.path.exists(log_file):
        existing = pd.read_csv(log_file)
        existing = existing[existing["date"] != check_date.isoformat()]
        log_df = pd.concat([existing, log_df], ignore_index=True)
    log_df.to_csv(log_file, index=False)
    print(f"\nLogged to {log_file}")


if __name__ == "__main__":
    main()
