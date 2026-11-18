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
            signals.append({
                "symbol":     symbol,
                "close":      round(tc, 2),
                "rsi":        round(tr, 1),
                "obv_%":      obv_pct,
                "break_%":    brk_pct,
                "stop":       stop,
                "stop_pct":   stop_pct,
                "gap_52w_%":  gap_52w,
                "sma50":      round(sma50, 2),
            })

    df_out = pd.DataFrame(signals).sort_values("obv_%", ascending=False).reset_index(drop=True)
    return df_out


# ── Format output ─────────────────────────────────────────────────────────────
def format_output(regime, nifty, vs_dma, vs_12m, signals, criteria, check_date):
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
    lines.append(f"  RSI {c['rsi_lo']}-{c['rsi_hi']} + OBV >= {c['obv_min']}% + Top 1 pick")
    lines.append(f"  Expected: {c['win_rate']}% win rate, +{c['avg_ret']}% avg return, {c['rr']}:1 R/R")
    lines.append(f"  Stop loss: {c['stop_pct']}% | Hold: 5 trading days")

    if signals.empty:
        lines.append(f"\n  No qualifying signals today.")
        lines.append(f"  Criteria not met by any stock — skip this day.")
        lines.append("="*55)
        return "\n".join(lines), False

    lines.append(f"\n{'─'*55}")
    lines.append(f"  {len(signals)} qualifying signal(s) — TOP PICK:")
    lines.append(f"{'─'*55}")

    # Top pick
    top = signals.iloc[0]
    exit_date = check_date + timedelta(days=7)  # approximate 5 trading days
    lines.append(f"\n  ★ {top['symbol']}")
    lines.append(f"    Entry:      ₹{top['close']} (today's close)")
    lines.append(f"    Stop loss:  ₹{top['stop']} ({top['stop_pct']}% below entry)")
    lines.append(f"    Exit:       ~{exit_date.strftime('%d %b %Y')} (5 trading days)")
    lines.append(f"    RSI:        {top['rsi']} (in {c['rsi_lo']}-{c['rsi_hi']} zone)")
    lines.append(f"    OBV:        {top['obv_%']}% above 20d high")
    lines.append(f"    Breakout:   {top['break_%']}% above 20d resistance")
    lines.append(f"    52w wall:   {top['gap_52w_%']}% above current price")

    if len(signals) > 1:
        lines.append(f"\n  Other signals (not actioned — top 1 only):")
        for _, r in signals.iloc[1:4].iterrows():
            lines.append(f"    {r['symbol']}: RSI {r['rsi']}, OBV {r['obv_%']}%, Stop ₹{r['stop']}")

    lines.append(f"\n{'─'*55}")
    lines.append(f"  Action: Enter {top['symbol']} at today's close ₹{top['close']}")
    lines.append(f"  Set stop loss at ₹{top['stop']}")
    lines.append(f"  Exit at close on {exit_date.strftime('%d %b %Y')} unless stop hit earlier")

    # Pre-trade manual checklist
    screener_url = f"https://www.screener.in/company/{top['symbol']}/"
    lines.append(f"\n{'─'*55}")
    lines.append(f"  PRE-TRADE CHECKLIST — verify before entering")
    lines.append(f"  Screener: {screener_url}")
    lines.append(f"{'─'*55}")
    lines.append(f"")
    lines.append(f"  [ ] 1. EARNINGS — No results due in next 7 days")
    lines.append(f"         Check: NSE announcements or Screener quarterly dates")
    lines.append(f"         → If results due before {exit_date.strftime('%d %b')}: SKIP this trade")
    lines.append(f"")
    lines.append(f"  [ ] 2. LIQUIDITY — Avg daily traded value >= ₹10 Cr")
    lines.append(f"         Check: Screener > Market Cap section > Avg Volume x Price")
    lines.append(f"         → If below ₹10 Cr/day: SKIP — exit will be difficult")
    lines.append(f"")
    lines.append(f"  [ ] 3. DELIVERY % — Above 40% on breakout day")
    lines.append(f"         Check: NSE bhavcopy or Trendlyne delivery data")
    lines.append(f"         → If below 40%: move is speculative, not institutional")
    lines.append(f"")
    lines.append(f"  [ ] 4. PROMOTER PLEDGE — Below 15%")
    lines.append(f"         Check: Screener > Shareholding > Pledged %")
    lines.append(f"         → If above 15%: hidden forced-selling risk, SKIP")
    lines.append(f"")
    lines.append(f"  [ ] 5. SECTOR FII FLOW — FIIs net buying in this sector (last 3 days)")
    lines.append(f"         Check: NSE India > FII/DII data > sector breakdown")
    lines.append(f"         → If FIIs net selling in sector: wait or skip")
    lines.append(f"")
    lines.append(f"  [ ] 6. MACRO EVENTS — No binary event in next 5 trading days")
    lines.append(f"         Check: NSE events calendar or Economic calendar")
    lines.append(f"         → RBI policy / Budget / Fed decision in next 5 days: SKIP")
    lines.append(f"")
    lines.append(f"  [ ] 7. NEWS CHECK — No negative stock-specific news today")
    lines.append(f"         Check: Google '{top['symbol']} NSE news today'")
    lines.append(f"         → SEBI action / management change / contract loss: SKIP")
    lines.append(f"")
    lines.append(f"  [ ] 8. GLOBAL MARKETS — S&P 500 / Nasdaq not down >1.5% last night")
    lines.append(f"         Check: Google 'S&P 500 yesterday close'")
    lines.append(f"         → If global risk-off: wait for Indian market to stabilise by 11 AM")
    lines.append(f"")
    lines.append(f"  All 8 checks passed? → ENTER at today's close ₹{top['close']}")
    lines.append(f"  Any check failed?    → SKIP or WAIT for next signal")
    lines.append("="*55)

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
    signals = run_s2_screener(symbol_data, check_date, criteria)

    output, has_signals = format_output(regime, nifty, vs_dma, vs_12m, signals, CRITERIA, check_date)

    print("\n" + output)

    if send_mail:
        regime_emoji = {"BULL":"🟢","CHOPPY":"🟡","BEAR":"🔴"}.get(regime,"⚪")
        if has_signals:
            top_symbol = signals.iloc[0]["symbol"]
            subject = f"{regime_emoji} SIGNAL: {top_symbol} | {regime} | {check_date.strftime('%d %b %Y')}"
        else:
            subject = f"{regime_emoji} No signals today | {regime} | {check_date.strftime('%d %b %Y')}"
        sent = send_email(subject, output)
        if sent:
            print(f"Email sent to {EMAIL_TO}")
        else:
            print("Email not configured — output printed above only.")

    # Save to log
    log_entry = {
        "date": check_date.isoformat(),
        "regime": regime,
        "nifty": nifty,
        "signals": len(signals) if not signals.empty else 0,
        "top_pick": signals.iloc[0]["symbol"] if not signals.empty else "",
        "top_close": signals.iloc[0]["close"] if not signals.empty else "",
        "top_stop": signals.iloc[0]["stop"] if not signals.empty else "",
        "top_rsi": signals.iloc[0]["rsi"] if not signals.empty else "",
        "top_obv": signals.iloc[0]["obv_%"] if not signals.empty else "",
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
