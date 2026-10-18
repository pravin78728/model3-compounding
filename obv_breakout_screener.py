"""
OBV Breakout Screener — Model 1 Signal (NSE Universe)
======================================================
Scans all stocks in the prices table for the following setup:

  1. OBV broke its 20-day high            (volume is leading)
  2. Price did NOT break its 20-day high  (price hasn't caught up yet)
  3. 20-day avg volume >= 50-day avg volume  (volume picking up vs baseline)
  4. Price is above the 50-day SMA        (uptrend bias)

Additional price resistance checks:
  A. 20-day high proximity  — how close price is to immediate resistance
  B. 52-week high proximity — is the bigger wall clear or blocking?
  C. Price coil (compression) — has price been in a tight band last 5-9 sessions?

Run weekly (Monday morning before market open).

Usage:
    python obv_breakout_screener.py

Output:
    - Prints ranked results to terminal
    - Saves results to obv_breakout_YYYY-MM-DD.csv
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
LOOKBACK        = 20   # days for OBV high and price high comparison
SMA_PERIOD      = 50   # days for trend filter (price must be above this)
VOL_SHORT       = 20   # days for recent average volume
VOL_LONG        = 50   # days for baseline average volume
OBV_MIN_PCT     = 5.0  # minimum OBV breakout strength % (quality filter)
COIL_SHORT      = 5    # sessions for tight coil check
COIL_LONG       = 9    # sessions for broader coil check
COIL_THRESHOLD  = 4.0  # % range considered a coil (high-low / avg_close)
FETCH_DAYS      = 400  # calendar days to fetch (covers 52-week high + buffer)


# ── Step 1: Fetch all symbols ─────────────────────────────────────────────────
def get_symbols(engine):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT symbol FROM prices ORDER BY symbol"))
        symbols = [row[0] for row in result]
    print(f"Found {len(symbols)} symbols in database.")
    return symbols


# ── Step 2: Fetch price + volume data ────────────────────────────────────────
def fetch_data(engine, fetch_days):
    """
    Fetch OHLCV data for all active symbols (updated since Oct 1 2026).
    Fetches 400 calendar days to cover 52-week high calculation.
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

    # Drop rows with missing close price only
    df = df.dropna(subset=["close_price"])

    # Forward-fill missing volume and high/low from prior trading day
    for col in ["volume", "high_price", "low_price"]:
        df[col] = df.groupby("symbol")[col].transform(
            lambda x: x.fillna(method="ffill").fillna(0)
        )

    # Split into per-symbol DataFrames
    symbol_data = {}
    for symbol, group in df.groupby("symbol"):
        symbol_data[symbol] = group.reset_index(drop=True)

    return symbol_data


# ── Step 3: Compute OBV ───────────────────────────────────────────────────────
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


# ── Step 4: Price coil detection ─────────────────────────────────────────────
def compute_coil(df, sessions):
    """
    Measures how tight price has been over the last N sessions.
    Coil % = (highest high - lowest low) / avg close * 100
    Lower % = tighter coil = stronger compression = more imminent breakout.
    Uses high/low where available, falls back to close range.
    """
    recent = df.iloc[-sessions:]

    if "high_price" in recent.columns and recent["high_price"].notna().sum() > sessions * 0.5:
        highest = recent["high_price"].max()
        lowest  = recent["low_price"].min()
    else:
        highest = recent["close_price"].max()
        lowest  = recent["close_price"].min()

    avg_close = recent["close_price"].mean()
    if avg_close == 0:
        return 999.0

    return round((highest - lowest) / avg_close * 100, 2)


# ── Step 5: Apply signal logic for one symbol ─────────────────────────────────
def check_signal(df, symbol):
    min_rows = max(SMA_PERIOD, VOL_LONG)
    if len(df) < min_rows:
        return None

    df = df.copy()
    df["obv"] = compute_obv(df)

    # ── Latest values ──
    today_close = df["close_price"].iloc[-1]
    today_obv   = df["obv"].iloc[-1]
    today_date  = df["date"].iloc[-1]

    # ── 20-day lookback window (excludes today) ──
    prior_obv   = df["obv"].iloc[-(LOOKBACK + 1):-1]
    prior_close = df["close_price"].iloc[-(LOOKBACK + 1):-1]

    if len(prior_obv) < LOOKBACK:
        return None

    obv_prior_high   = prior_obv.max()
    price_20d_high   = prior_close.max()

    # ── Condition 1: OBV broke 20-day high ──
    obv_breakout = today_obv > obv_prior_high

    # ── Condition 2: Price did NOT break 20-day high ──
    price_no_breakout = today_close <= price_20d_high

    # ── Condition 3: 20-day avg volume >= 50-day avg volume ──
    avg_vol_20 = df["volume"].iloc[-VOL_SHORT:].mean()
    avg_vol_50 = df["volume"].iloc[-VOL_LONG:].mean()
    volume_rising = avg_vol_20 >= avg_vol_50

    # ── Condition 4: Price above 50-day SMA ──
    sma_50     = df["close_price"].iloc[-SMA_PERIOD:].mean()
    above_sma  = today_close > sma_50

    # ── OBV strength check (quality filter) ──
    obv_breakout_pct_early = (
        (today_obv - obv_prior_high) / abs(obv_prior_high) * 100
        if obv_prior_high != 0 else 0
    )
    obv_strong = obv_breakout_pct_early >= OBV_MIN_PCT

    # ── Core signals ──
    raw_signal      = obv_breakout and price_no_breakout
    filtered_signal = obv_breakout and price_no_breakout and volume_rising and above_sma and obv_strong

    # ── Resistance Check A: 20-day high proximity ──
    gap_to_20d_high = round((price_20d_high - today_close) / today_close * 100, 2)

    if gap_to_20d_high < 2.0:
        resistance_20d = "🔴 AT RESISTANCE"      # price right at the wall
    elif gap_to_20d_high < 5.0:
        resistance_20d = "🟡 APPROACHING"         # closing in
    else:
        resistance_20d = "🟢 ROOM TO RUN"         # early stage

    # ── Resistance Check B: 52-week high proximity ──
    weeks_52 = df["close_price"].iloc[-252:] if len(df) >= 252 else df["close_price"]
    high_52w  = weeks_52.max()
    gap_to_52w_high = round((high_52w - today_close) / today_close * 100, 2)

    # Is 52w high the same as 20d high? (no bigger wall above)
    wall_cleared = high_52w <= price_20d_high * 1.02  # within 2% means same level

    if wall_cleared:
        resistance_52w = "✅ NO WALL ABOVE"        # 52w high is the 20d high — path clear
    elif gap_to_52w_high < 5.0:
        resistance_52w = "⚠️  WALL NEAR"           # bigger resistance just above
    else:
        resistance_52w = "🟢 WALL FAR"             # 52w high is far above — room to run

    # ── Resistance Check C: Price coil (compression) ──
    coil_5d = compute_coil(df, COIL_SHORT)
    coil_9d = compute_coil(df, COIL_LONG)

    # Both windows must be tight to confirm coil
    is_coiled = coil_5d <= COIL_THRESHOLD and coil_9d <= COIL_THRESHOLD * 1.5

    if coil_5d <= 2.0:
        coil_label = "🔥 TIGHT COIL"              # very compressed — breakout imminent
    elif coil_5d <= COIL_THRESHOLD:
        coil_label = "🟡 MILD COIL"               # some compression
    else:
        coil_label = "〰️  NO COIL"                # price moving freely

    # ── OBV strength ──
    obv_breakout_pct = round(
        (today_obv - obv_prior_high) / abs(obv_prior_high) * 100
        if obv_prior_high != 0 else 0, 1
    )

    # ── Breakout readiness score (0-100) ──
    # Combines all checks into one number for easy ranking
    score = 0
    score += min(obv_breakout_pct, 50)              # OBV strength: up to 50 pts
    score += max(0, 20 - gap_to_20d_high * 4)       # closer to 20d high: up to 20 pts
    score += 15 if wall_cleared else (5 if gap_to_52w_high > 10 else 0)  # 52w wall: up to 15 pts
    score += 15 if coil_5d <= 2.0 else (8 if coil_5d <= 4.0 else 0)     # coil: up to 15 pts
    score = round(min(score, 100), 1)

    return {
        "symbol":             symbol,
        "date":               today_date.strftime("%Y-%m-%d"),
        "close":              round(today_close, 2),
        "filtered_signal":    filtered_signal,
        "raw_signal":         raw_signal,
        "breakout_score":     score,
        "obv_strength_%":     obv_breakout_pct,
        "gap_to_20d_high_%":  gap_to_20d_high,
        "resistance_20d":     resistance_20d,
        "gap_to_52w_high_%":  gap_to_52w_high,
        "resistance_52w":     resistance_52w,
        "coil_5d_%":          coil_5d,
        "coil_9d_%":          coil_9d,
        "coil_signal":        coil_label,
        "avg_vol_20d":        int(avg_vol_20),
        "avg_vol_50d":        int(avg_vol_50),
        "sma_50":             round(sma_50, 2),
    }


# ── Step 6: Run screener across all symbols ───────────────────────────────────
def run_screener(symbol_data):
    results  = []
    skipped  = 0

    for symbol, df in symbol_data.items():
        result = check_signal(df, symbol)
        if result is None:
            skipped += 1
            continue
        results.append(result)

    print(f"Processed {len(results)} symbols. Skipped {skipped} (insufficient data).")

    all_df = pd.DataFrame(results)

    if all_df.empty:
        return all_df, all_df

    filtered_df = all_df[all_df["filtered_signal"] == True].copy()
    filtered_df = filtered_df.sort_values("breakout_score", ascending=False)
    filtered_df = filtered_df.reset_index(drop=True)
    filtered_df.index += 1

    return all_df, filtered_df


# ── Step 7: Display results ───────────────────────────────────────────────────
def display_results(filtered_df):
    today_str = date.today().strftime("%Y-%m-%d")

    print("\n" + "=" * 80)
    print(f"  OBV BREAKOUT SCREENER — {today_str}")
    print("=" * 80)

    if filtered_df.empty:
        print("  No stocks passed all 4 filters today.")
        return

    print(f"  {len(filtered_df)} stock(s) passed all filters:\n")

    for idx, row in filtered_df.iterrows():
        print(f"  {'─' * 60}")
        print(f"  #{idx}  {row['symbol']}  |  Close: ₹{row['close']}  |  Score: {row['breakout_score']}/100")
        print(f"       OBV strength:      {row['obv_strength_%']}% above 20d high")
        print(f"       20d resistance:    {row['gap_to_20d_high_%']}% gap  →  {row['resistance_20d']}")
        print(f"       52w resistance:    {row['gap_to_52w_high_%']}% gap  →  {row['resistance_52w']}")
        print(f"       Price coil (5d):   {row['coil_5d_%']}%  |  Coil (9d): {row['coil_9d_%']}%  →  {row['coil_signal']}")
        print(f"       Vol 20d avg: {row['avg_vol_20d']:,}  |  Vol 50d avg: {row['avg_vol_50d']:,}  |  SMA50: ₹{row['sma_50']}")

    print(f"  {'─' * 60}")
    print("\n  Score guide: OBV strength (50pts) + near 20d high (20pts) + 52w wall (15pts) + coil (15pts)")
    print("  Best setup: high score + TIGHT COIL + AT RESISTANCE + NO WALL ABOVE")
    print("=" * 80)


# ── Step 8: Save results ──────────────────────────────────────────────────────
def save_results(filtered_df, all_df):
    today_str = date.today().strftime("%Y-%m-%d")
    filtered_file = f"obv_breakout_{today_str}.csv"
    all_file      = f"obv_all_signals_{today_str}.csv"
    filtered_df.to_csv(filtered_file, index=True)
    all_df.to_csv(all_file, index=False)
    print(f"\nSaved:")
    print(f"  Filtered results → {filtered_file}")
    print(f"  All signals      → {all_file}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Starting OBV Breakout Screener...")
    print("-" * 40)
    symbol_data          = fetch_data(engine, FETCH_DAYS)
    all_df, filtered_df  = run_screener(symbol_data)
    display_results(filtered_df)
    save_results(filtered_df, all_df)
    print("\nDone.")


if __name__ == "__main__":
    main()
