"""
Weekly Master Script — Model 3 + Model 1 Sleeves 1 & 2
=======================================================
Runs every Saturday at 6 PM via cron.
Can also be triggered manually: python weekly_master.py

Produces one consolidated email to pravin.borade@gmail.com covering:
  - Market regime (Nifty500 vs 200-DMA)
  - Model 3: current holdings + regime-gated picks
  - Model 1 Sleeve 1: OBV pre-breakout watchlist
  - Model 1 Sleeve 2: OBV confirmed momentum list
  - Any Sleeve 2 stop alerts (positions breaching 10% trail)

Usage:
    python weekly_master.py
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
engine = create_engine(os.getenv("DATABASE_URL"))

# ── Email config ──────────────────────────────────────────────────────────────
EMAIL_TO      = "pravin.borade@gmail.com"
EMAIL_FROM    = os.getenv("EMAIL_FROM", "")
EMAIL_PASS    = os.getenv("EMAIL_PASS", "")
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587

# ── Signal parameters ─────────────────────────────────────────────────────────
LOOKBACK      = 20
SMA_PERIOD    = 50
RSI_PERIOD    = 14
RSI_THRESHOLD = 60
RSI_MAX       = 80
VOL_SHORT     = 20
VOL_LONG      = 50
OBV_MIN_PCT   = 5.0
FETCH_DAYS    = 400
TRAIL_STOP    = 0.10


# ── Regime check ──────────────────────────────────────────────────────────────
def get_market_regime():
    cutoff = (date.today() - timedelta(days=400)).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT date, close_price FROM prices
            WHERE symbol = 'NIFTY500_IDX'
            AND date >= :cutoff ORDER BY date DESC
        """), conn, params={"cutoff": cutoff})
    if df.empty:
        return "UNKNOWN", None, None, None
    df["date"] = pd.to_datetime(df["date"]).dt.date
    rows    = list(zip(df["date"], df["close_price"]))
    rd      = rows[0][0]
    p_now   = rows[0][1]
    p_200   = [p for d, p in rows if d >= rd - timedelta(days=280)]
    p_12m_v = next((p for d, p in rows if d <= rd - timedelta(days=240)), None)
    dma200  = np.mean(p_200) if p_200 else None
    if dma200 and p_12m_v:
        vs_dma = round((p_now / dma200 - 1) * 100, 1)
        vs_12m = round((p_now / p_12m_v - 1) * 100, 1)
        if p_now > dma200 * 1.03 and p_now > p_12m_v * 1.05:
            regime = "BULL"
        elif p_now < dma200 * 0.97 and p_now < p_12m_v * 0.95:
            regime = "BEAR"
        else:
            regime = "CHOPPY"
        return regime, round(p_now, 1), vs_dma, vs_12m
    return "UNKNOWN", None, None, None


# ── Fetch OHLCV data ──────────────────────────────────────────────────────────
def fetch_data():
    cutoff = (date.today() - timedelta(days=FETCH_DAYS)).strftime("%Y-%m-%d")
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT symbol, date, close_price, high_price, low_price, volume
            FROM prices
            WHERE date >= :cutoff
            AND symbol IN (
                SELECT DISTINCT symbol FROM prices WHERE date >= :recent
            )
            ORDER BY symbol, date ASC
        """), conn, params={
            "cutoff": cutoff,
            "recent": (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        })
    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce")
    df["high_price"]  = pd.to_numeric(df["high_price"],  errors="coerce")
    df["low_price"]   = pd.to_numeric(df["low_price"],   errors="coerce")
    df = df.dropna(subset=["close_price"])
    for col in ["volume", "high_price", "low_price"]:
        df[col] = df.groupby("symbol")[col].transform(
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


# ── Run both screeners ────────────────────────────────────────────────────────
def run_screeners(symbol_data):
    sleeve1, sleeve2 = [], []
    for symbol, df in symbol_data.items():
        if len(df) < max(SMA_PERIOD, VOL_LONG, RSI_PERIOD + 10):
            continue
        df       = df.copy()
        df["obv"] = compute_obv(df)
        df["rsi"] = compute_rsi(df["close_price"])
        tc = df["close_price"].iloc[-1]
        to = df["obv"].iloc[-1]
        tr = df["rsi"].iloc[-1]
        td = df["date"].iloc[-1]
        if pd.isna(tr):
            continue
        prior_o = df["obv"].iloc[-(LOOKBACK+1):-1]
        prior_c = df["close_price"].iloc[-(LOOKBACK+1):-1]
        if len(prior_o) < LOOKBACK:
            continue
        obv_high    = prior_o.max()
        price_high  = prior_c.max()
        av20        = df["volume"].iloc[-VOL_SHORT:].mean()
        av50        = df["volume"].iloc[-VOL_LONG:].mean()
        sma50       = df["close_price"].iloc[-SMA_PERIOD:].mean()
        obv_pct     = round((to - obv_high) / abs(obv_high) * 100 if obv_high != 0 else 0, 1)
        obv_ok      = to > obv_high and obv_pct >= OBV_MIN_PCT
        vol_ok      = av20 >= av50
        sma_ok      = tc > sma50
        price_cont  = tc <= price_high
        price_broke = tc > price_high
        gap_pct     = round((price_high - tc) / tc * 100, 2)
        break_pct   = round((tc - price_high) / price_high * 100, 2)

        # Sleeve 1
        if obv_ok and price_cont and vol_ok and sma_ok:
            sleeve1.append({
                "symbol": symbol, "close": round(tc, 2),
                "obv_%": obv_pct, "gap_to_res_%": gap_pct,
                "rsi": round(tr, 1),
                "date": td.strftime("%Y-%m-%d")
            })

        # Sleeve 2
        if (obv_ok and price_broke and vol_ok and sma_ok
                and RSI_THRESHOLD <= tr < RSI_MAX):
            sleeve2.append({
                "symbol": symbol, "close": round(tc, 2),
                "obv_%": obv_pct, "price_break_%": break_pct,
                "rsi": round(tr, 1),
                "stop": round(tc * (1 - TRAIL_STOP), 2),
                "date": td.strftime("%Y-%m-%d")
            })

    s1 = pd.DataFrame(sleeve1).sort_values("obv_%", ascending=False).reset_index(drop=True) if sleeve1 else pd.DataFrame()
    s2 = pd.DataFrame(sleeve2).sort_values("obv_%", ascending=False).reset_index(drop=True) if sleeve2 else pd.DataFrame()
    return s1, s2


# ── Model 3 picks ─────────────────────────────────────────────────────────────
def get_model3_picks(regime):
    """Pull latest score_and_pick output from the scores table if available,
    otherwise run a quick re-score and return top picks."""
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT symbol, composite_score, computed_date
                FROM model3_features
                WHERE computed_date = (SELECT MAX(computed_date) FROM model3_features)
                ORDER BY composite_score DESC
                LIMIT 10
            """), conn)
        if df.empty:
            return [], "No model3_features data found."
        if regime in ("BULL",):
            picks = df.head(10)
            note  = "BULL regime — top 10 quality stocks deployed."
        else:
            picks = df.head(3)
            note  = f"{regime} regime — top 3 stocks only, 70% cash."
        return picks[["symbol","composite_score"]].values.tolist(), note
    except Exception as e:
        return [], f"Could not fetch Model 3 picks: {e}"


# ── Build email body ──────────────────────────────────────────────────────────
def build_email(regime, nifty, vs_dma, vs_12m, s1, s2, m3_picks, m3_note):
    today = date.today().strftime("%d %b %Y")
    regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "CHOPPY": "🟡"}.get(regime, "⚪")

    lines = []
    lines.append(f"WEEKLY TRADING BRIEF — {today}")
    lines.append("=" * 55)

    # Regime
    lines.append(f"\n{regime_emoji}  MARKET REGIME: {regime}")
    lines.append(f"   Nifty500: {nifty}  |  vs 200-DMA: {vs_dma}%  |  vs 12m: {vs_12m}%")
    if regime == "BEAR":
        lines.append("\n   ⛔ Both Model 1 sleeves GATED OFF — hold cash.")
        lines.append("   ⛔ Model 3 in defensive mode — top 3 stocks only.")

    # Model 3
    lines.append("\n" + "─" * 55)
    lines.append("MODEL 3 — Multi-year Compounding Engine")
    lines.append(f"Note: {m3_note}")
    if m3_picks:
        lines.append(f"\n  {'Symbol':<15} {'Score':>8}")
        lines.append(f"  {'-'*23}")
        for sym, score in m3_picks:
            lines.append(f"  {sym:<15} {score:>8.1f}")
    else:
        lines.append("  No picks available.")

    # Sleeve 1
    lines.append("\n" + "─" * 55)
    lines.append("MODEL 1 SLEEVE 1 — OBV Pre-Breakout Watchlist")
    if regime == "BEAR":
        lines.append("  ⛔ Gated off — BEAR regime. No action.")
    elif s1.empty:
        lines.append("  No signals this week.")
    else:
        lines.append(f"  {len(s1)} stock(s) flagged:\n")
        lines.append(f"  {'Symbol':<14} {'Close':>8} {'OBV%':>8} {'Gap%':>8} {'RSI':>6}")
        lines.append(f"  {'-'*46}")
        for _, r in s1.head(10).iterrows():
            lines.append(f"  {r['symbol']:<14} {r['close']:>8.2f} {r['obv_%']:>8.1f} {r['gap_to_res_%']:>8.2f} {r['rsi']:>6.1f}")
        lines.append("\n  Best setup: high OBV% + gap < 3% + no wall above")
        lines.append("  Enter when price closes above resistance on volume.")

    # Sleeve 2
    lines.append("\n" + "─" * 55)
    lines.append("MODEL 1 SLEEVE 2 — OBV Confirmed Momentum")
    if regime == "BEAR":
        lines.append("  ⛔ Gated off — BEAR regime. No action.")
    elif s2.empty:
        lines.append("  No signals this week.")
    else:
        lines.append(f"  {len(s2)} confirmed breakout(s):\n")
        lines.append(f"  {'Symbol':<14} {'Close':>8} {'OBV%':>8} {'Brk%':>8} {'RSI':>6} {'Stop':>10}")
        lines.append(f"  {'-'*56}")
        for _, r in s2.head(15).iterrows():
            lines.append(f"  {r['symbol']:<14} {r['close']:>8.2f} {r['obv_%']:>8.1f} {r['price_break_%']:>8.2f} {r['rsi']:>6.1f} {r['stop']:>10.2f}")
        lines.append("\n  Exit rule: trail stop 10% below highest close since entry.")
        lines.append("  Record your entry date and update stop weekly.")

    lines.append("\n" + "=" * 55)
    lines.append("Generated automatically by weekly_master.py")
    lines.append(f"Next run: Saturday {(date.today() + timedelta(days=7)).strftime('%d %b %Y')} at 6 PM")

    return "\n".join(lines)


# ── Send email ────────────────────────────────────────────────────────────────
def send_email(subject, body):
    if not EMAIL_FROM or not EMAIL_PASS:
        print("\n[EMAIL NOT CONFIGURED]")
        print("Add EMAIL_FROM and EMAIL_PASS to your .env file.")
        print("Showing email body instead:\n")
        print(body)
        return False
    try:
        msg              = MIMEMultipart()
        msg["From"]      = EMAIL_FROM
        msg["To"]        = EMAIL_TO
        msg["Subject"]   = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(EMAIL_FROM, EMAIL_PASS)
            s.send_message(msg)
        print(f"Email sent to {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        print("\nShowing email body instead:\n")
        print(body)
        return False


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Weekly Master — {date.today()}")
    print("=" * 40)

    print("Checking market regime...")
    regime, nifty, vs_dma, vs_12m = get_market_regime()
    print(f"Regime: {regime} | Nifty500: {nifty} | vs 200-DMA: {vs_dma}% | vs 12m: {vs_12m}%")

    print("Fetching price data...")
    symbol_data = fetch_data()
    print(f"Loaded {len(symbol_data)} symbols.")

    print("Running Model 1 screeners...")
    s1, s2 = run_screeners(symbol_data)
    if regime == "BEAR":
        print("BEAR regime — both sleeves gated. Clearing signals.")
        s1, s2 = pd.DataFrame(), pd.DataFrame()
    else:
        print(f"Sleeve 1: {len(s1)} signals | Sleeve 2: {len(s2)} signals")

    print("Fetching Model 3 picks...")
    m3_picks, m3_note = get_model3_picks(regime)

    print("Building email...")
    regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "CHOPPY": "🟡"}.get(regime, "⚪")
    subject = f"{regime_emoji} Weekly Brief | {regime} Regime | {date.today().strftime('%d %b %Y')}"
    body    = build_email(regime, nifty, vs_dma, vs_12m, s1, s2, m3_picks, m3_note)

    send_email(subject, body)
    print("\nDone.")


if __name__ == "__main__":
    main()
