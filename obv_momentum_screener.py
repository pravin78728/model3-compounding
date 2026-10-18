"""
OBV Confirmed Breakout Momentum Screener — Model 1 Sleeve 2 (NSE Universe)
===========================================================================
Finds stocks where volume AND price have both broken out — confirmed momentum.
Ride these until they fall 10% from their highest close since discovery.

Signal conditions (ALL must be true):
  1. OBV broke its 20-day high        (volume confirmed)
  2. Price close broke its 20-day high (price confirmed — breakout is real)
  3. RSI(14) above 60                 (momentum is strong, not overbought yet)
  4. 20-day avg volume >= 50-day avg volume  (volume picking up vs baseline)
  5. Price above 50-day SMA           (uptrend bias)

Exit tracking (manual — use the tracker when built):
  - Initial stop = today's close x 0.90 (10% below entry close)
  - Trailing stop moves up as stock makes new closing highs after discovery
  - Exit when end-of-day close falls below trailing stop

Run weekly (Monday morning before market open).

Usage:
    python obv_momentum_screener.py

Output:
    - Prints ranked results to terminal
    - Saves results to obv_momentum_YYYY-MM-DD.csv
"""

import os
import pandas as pd
import numpy as np
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Load environment ──────────────────────────────────────────────────────────
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in .env file. Check your .env.")

engine = create_engine(DATABASE_URL)

# ── Parameters ────────────────────────────────────────────────────────────────
LOOKBACK        = 20    # days for OBV high and price high comparison
SMA_PERIOD      = 50    # days for trend filter
RSI_PERIOD      = 14    # days for RSI calculation
RSI_THRESHOLD   = 60    # RSI must be above this
RSI_MAX         = 80    # RSI must be below this (avoid overbought — quality filter)
OBV_MIN_PCT     = 5.0   # minimum OBV breakout strength % (quality filter)
VOL_SHORT       = 20    # days for recent average volume
VOL_LONG        = 50    # days for baseline average volume
TRAIL_STOP_PCT  = 0.10  # 10% trailing stop from discovery close
FETCH_DAYS      = 400   # calendar days to fetch (covers 52-week context)


# ── Step 1: Fetch data ────────────────────────────────────────────────────────
def fetch_data(engine, fetch_days):
    """
    Fetch OHLCV data for all active symbols (updated since Oct 1 2026).
    """
    cutoff = date.today() - timedelta(days=fetch_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    query = text("""
        SELECT symbol, date, close_price, high_price, low_price, volume
        FROM prices
        WHERE date >= :cutoff
        AND symbol IN (
            SELECT DISTINCT symbol FROM prices
            WHERE date >= '2026-10-01'
        )
        ORDER BY symbol, date ASC
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"cutoff": cutoff_str})

    print(f"Fetched {len(df):,} rows covering {df['symbol'].nunique()} symbols.")

    df["date"]        = pd.to_datetime(df["date"])
    df["close_price"] = pd.to_numeric(df["close_price"], errors="coerce")
    df["high_price"]  = pd.to_numeric(df["high_price"],  errors="coerce")
    df["low_price"]   = pd.to_numeric(df["low_price"],   errors="coerce")
    df["volume"]      = pd.to_numeric(df["volume"],      errors="coerce")

    df = df.dropna(subset=["close_price"])

    for col in ["volume", "high_price", "low_price"]:
        df[col] = df.groupby("symbol")[col].transform(
            lambda x: x.fillna(method="ffill").fillna(0)
        )

    symbol_data = {}
    for symbol, group in df.groupby("symbol"):
        symbol_data[symbol] = group.reset_index(drop=True)

    return symbol_data


# ── Step 2: Compute OBV ───────────────────────────────────────────────────────
def compute_obv(df):
    close  = df["close_price"].values
    volume = df["volume"].values
    obv    = np.zeros(len(close))

    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            obv[i] = obv[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            obv[i] = obv[i - 1] - volume[i]
        else:
            obv[i] = obv[i - 1]

    return pd.Series(obv, index=df.index)


# ── Step 3: Compute RSI ───────────────────────────────────────────────────────
def compute_rsi(df, period=14):
    """
    Standard Wilder RSI calculation.
    Uses exponential moving average of gains and losses.
    """
    close  = df["close_price"]
    delta  = close.diff()

    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)

    # Wilder smoothing (equivalent to EMA with alpha = 1/period)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


# ── Step 4: Apply signal logic for one symbol ─────────────────────────────────
def check_signal(df, symbol):
    min_rows = max(SMA_PERIOD, VOL_LONG, RSI_PERIOD + 10)
    if len(df) < min_rows:
        return None

    df = df.copy()
    df["obv"] = compute_obv(df)
    df["rsi"] = compute_rsi(df, RSI_PERIOD)

    # ── Latest values ──
    today_close = df["close_price"].iloc[-1]
    today_obv   = df["obv"].iloc[-1]
    today_rsi   = df["rsi"].iloc[-1]
    today_date  = df["date"].iloc[-1]

    if pd.isna(today_rsi):
        return None

    # ── 20-day lookback window (excludes today) ──
    prior_obv   = df["obv"].iloc[-(LOOKBACK + 1):-1]
    prior_close = df["close_price"].iloc[-(LOOKBACK + 1):-1]

    if len(prior_obv) < LOOKBACK:
        return None

    obv_prior_high   = prior_obv.max()
    price_20d_high   = prior_close.max()

    # ── Condition 1: OBV broke 20-day high ──
    obv_breakout = today_obv > obv_prior_high

    # ── Condition 2: Price close ALSO broke 20-day high ──
    price_breakout = today_close > price_20d_high

    # ── Condition 3: RSI 60–80 sweet spot (quality filter) ──
    rsi_strong = RSI_THRESHOLD <= today_rsi < RSI_MAX

    # ── Condition 4: 20-day avg volume >= 50-day avg volume ──
    avg_vol_20  = df["volume"].iloc[-VOL_SHORT:].mean()
    avg_vol_50  = df["volume"].iloc[-VOL_LONG:].mean()
    volume_rising = avg_vol_20 >= avg_vol_50

    # ── Condition 5: Price above 50-day SMA ──
    sma_50     = df["close_price"].iloc[-SMA_PERIOD:].mean()
    above_sma  = today_close > sma_50

    # ── OBV minimum strength check (quality filter) ──
    obv_strength_early = (
        (today_obv - obv_prior_high) / abs(obv_prior_high) * 100
        if obv_prior_high != 0 else 0
    )
    obv_strong = obv_strength_early >= OBV_MIN_PCT

    # ── Final signal ──
    signal = (obv_breakout and price_breakout and
              rsi_strong and volume_rising and above_sma and obv_strong)

    if not signal:
        return None

    # ── Exit levels ──
    initial_stop     = round(today_close * (1 - TRAIL_STOP_PCT), 2)
    stop_buffer_pct  = round((today_close - initial_stop) / today_close * 100, 2)

    # ── OBV strength ──
    obv_strength_pct = round(
        (today_obv - obv_prior_high) / abs(obv_prior_high) * 100
        if obv_prior_high != 0 else 0, 1
    )

    # ── Price breakout strength — how far above 20d high ──
    price_breakout_pct = round(
        (today_close - price_20d_high) / price_20d_high * 100, 2
    )

    # ── 52-week high context ──
    weeks_52       = df["close_price"].iloc[-252:] if len(df) >= 252 else df["close_price"]
    high_52w       = weeks_52.max()
    gap_to_52w_pct = round((high_52w - today_close) / today_close * 100, 2)

    if high_52w <= price_20d_high * 1.02:
        wall_label = "✅ AT 52W HIGH"      # breaking to new highs — most bullish
    elif gap_to_52w_pct < 5.0:
        wall_label = "⚠️  WALL NEAR"       # 52w high just above — potential cap
    else:
        wall_label = "🟢 CLEAR ABOVE"      # room to run before hitting 52w high

    # ── Momentum score (0-100) ──
    score = 0
    score += min(obv_strength_pct, 40)              # OBV strength: up to 40 pts
    score += min(price_breakout_pct * 5, 20)        # price breakout strength: up to 20 pts
    score += min((today_rsi - 60) * 2, 20)          # RSI above 60: up to 20 pts
    score += 15 if high_52w <= price_20d_high * 1.02 else (5 if gap_to_52w_pct > 10 else 0)
    score += 5 if avg_vol_20 >= avg_vol_50 * 1.5 else 0   # volume surge bonus
    score = round(min(score, 100), 1)

    return {
        "symbol":               symbol,
        "date":                 today_date.strftime("%Y-%m-%d"),
        "close":                round(today_close, 2),
        "momentum_score":       score,
        "rsi":                  round(today_rsi, 1),
        "obv_strength_%":       obv_strength_pct,
        "price_breakout_%":     price_breakout_pct,
        "52w_context":          wall_label,
        "gap_to_52w_%":         gap_to_52w_pct,
        "initial_stop":         initial_stop,
        "stop_buffer_%":        stop_buffer_pct,
        "avg_vol_20d":          int(avg_vol_20),
        "avg_vol_50d":          int(avg_vol_50),
        "sma_50":               round(sma_50, 2),
    }


# ── Step 5: Run screener ──────────────────────────────────────────────────────
def run_screener(symbol_data):
    results = []
    skipped = 0

    for symbol, df in symbol_data.items():
        result = check_signal(df, symbol)
        if result is None:
            skipped += 1
            continue
        results.append(result)

    print(f"Found {len(results)} confirmed breakouts. Skipped {skipped} (no signal or insufficient data).")

    if not results:
        return pd.DataFrame()

    df_out = pd.DataFrame(results)
    df_out = df_out.sort_values("momentum_score", ascending=False)
    df_out = df_out.reset_index(drop=True)
    df_out.index += 1

    return df_out


# ── Step 6: Display results ───────────────────────────────────────────────────
def display_results(df_out):
    today_str = date.today().strftime("%Y-%m-%d")

    print("\n" + "=" * 80)
    print(f"  OBV MOMENTUM SCREENER (Sleeve 2) — {today_str}")
    print("=" * 80)

    if df_out.empty:
        print("  No confirmed breakouts today.")
        return

    print(f"  {len(df_out)} confirmed breakout(s):\n")

    for idx, row in df_out.iterrows():
        print(f"  {'─' * 60}")
        print(f"  #{idx}  {row['symbol']}  |  Close: ₹{row['close']}  |  Score: {row['momentum_score']}/100")
        print(f"       RSI:               {row['rsi']} {'✅ strong' if row['rsi'] >= 70 else '🟡 building'}")
        print(f"       OBV strength:      {row['obv_strength_%']}% above 20d high")
        print(f"       Price breakout:    {row['price_breakout_%']}% above 20d high")
        print(f"       52w context:       {row['52w_context']}  ({row['gap_to_52w_%']}% to 52w high)")
        print(f"       Initial stop:      ₹{row['initial_stop']}  ({row['stop_buffer_%']}% below close)")
        print(f"       Vol 20d avg: {row['avg_vol_20d']:,}  |  Vol 50d avg: {row['avg_vol_50d']:,}  |  SMA50: ₹{row['sma_50']}")

    print(f"  {'─' * 60}")
    print("\n  Score guide: OBV strength (40pts) + price breakout (20pts) + RSI 60-80 (20pts) + 52w wall (15pts) + vol surge (5pts)")
    print("  Best setup: high score + RSI 65-75 + AT 52W HIGH + strong OBV (RSI capped at 80 — no chasing overbought)")
    print("  Exit rule:  trail stop at 10% below highest close since your discovery date")
    print("=" * 80)


# ── Step 7: Save results ──────────────────────────────────────────────────────
def save_results(df_out):
    today_str = date.today().strftime("%Y-%m-%d")
    filename  = f"obv_momentum_{today_str}.csv"
    df_out.to_csv(filename, index=True)
    print(f"\nSaved: {filename}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting OBV Momentum Screener (Sleeve 2)...")
    print("-" * 40)
    symbol_data = fetch_data(engine, FETCH_DAYS)
    df_out      = run_screener(symbol_data)
    display_results(df_out)
    save_results(df_out)
    print("\nDone.")


if __name__ == "__main__":
    main()
