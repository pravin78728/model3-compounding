"""
Historical Volume Backfill — NSE Bhavcopy
==========================================
Fetches OHLCV data from NSE bhavcopy archives for Jan 2022 to today
and updates existing rows in the prices table with volume, high, low, open.

Uses two URL formats:
  - Old format (pre Jul 2024): /content/historical/EQUITIES/YYYY/MON/cmDDMONYYYYbhav.csv.zip
  - New format (Jul 2024+):    /content/cm/BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip

Only updates symbols already in your prices table.
Safe to re-run: skips dates that already have volume populated.

Estimated runtime: 30-45 minutes for 4+ years of data.

Usage:
    python backfill_historical_volume.py
"""

import os
import time
import requests
import pandas as pd
from io import BytesIO
import zipfile
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import datetime, timedelta, date

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
START_DATE      = date(2022, 1, 1)
END_DATE        = date.today()
SLEEP_SECONDS   = 1.0
BATCH_SIZE      = 20
NEW_FORMAT_DATE = date(2024, 7, 6)  # new URL format starts around here

MONTH_MAP = {
    1:"JAN", 2:"FEB", 3:"MAR", 4:"APR", 5:"MAY", 6:"JUN",
    7:"JUL", 8:"AUG", 9:"SEP", 10:"OCT", 11:"NOV", 12:"DEC"
}

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer":    "https://www.nseindia.com"
}

# ── Connect ───────────────────────────────────────────────────────────────────
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur  = conn.cursor()

# ── Get existing symbols ──────────────────────────────────────────────────────
cur.execute("SELECT DISTINCT symbol FROM prices")
existing_symbols = set(row[0] for row in cur.fetchall())
print(f"Found {len(existing_symbols)} existing symbols in database.")

# ── Check already-filled dates ────────────────────────────────────────────────
cur.execute("""
    SELECT DISTINCT date FROM prices
    WHERE volume IS NOT NULL
    AND date >= %s
    ORDER BY date
""", (START_DATE,))
already_filled = set(row[0] for row in cur.fetchall())
print(f"Already have volume for {len(already_filled)} dates since {START_DATE}.")


# ── Fetch one day — old format ────────────────────────────────────────────────
def fetch_old_format(d):
    """Pre Jul 2024: cm03JUL2023bhav.csv.zip"""
    mon      = MONTH_MAP[d.month]
    day_str  = f"{d.day:02d}"
    year_str = str(d.year)
    url = (f"https://nsearchives.nseindia.com/content/historical/EQUITIES/"
           f"{year_str}/{mon}/cm{day_str}{mon}{year_str}bhav.csv.zip")
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            return None
        z   = zipfile.ZipFile(BytesIO(r.content))
        df  = pd.read_csv(z.open(z.namelist()[0]))
        # Old format columns
        df  = df[df["SERIES"] == "EQ"].copy()
        df  = df[["SYMBOL","TIMESTAMP","OPEN","HIGH","LOW","CLOSE","TOTTRDQTY"]].copy()
        df.columns = ["symbol","date","open_price","high_price","low_price","close_price","volume"]
        df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y").dt.date
        df  = df.dropna()
        df  = df[df["symbol"].isin(existing_symbols)]
        return df
    except Exception as e:
        print(f"  Error (old format) {d}: {e}")
        return None


# ── Fetch one day — new format ────────────────────────────────────────────────
def fetch_new_format(d):
    """Jul 2024+: BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip"""
    date_str = d.strftime("%Y%m%d")
    url = (f"https://nsearchives.nseindia.com/content/cm/"
           f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip")
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            return None
        z   = zipfile.ZipFile(BytesIO(r.content))
        df  = pd.read_csv(z.open(z.namelist()[0]))
        # New format columns
        df  = df[df["SctySrs"] == "EQ"].copy()
        df  = df[["TckrSymb","TradDt","OpnPric","HghPric","LwPric","ClsPric","TtlTradgVol"]].copy()
        df.columns = ["symbol","date","open_price","high_price","low_price","close_price","volume"]
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df  = df.dropna()
        df  = df[df["symbol"].isin(existing_symbols)]
        return df
    except Exception as e:
        print(f"  Error (new format) {d}: {e}")
        return None


# ── Fetch dispatcher ──────────────────────────────────────────────────────────
def fetch_bhavcopy(d):
    if d >= NEW_FORMAT_DATE:
        return fetch_new_format(d)
    else:
        return fetch_old_format(d)


# ── Main backfill loop ────────────────────────────────────────────────────────
current     = START_DATE
total_days  = 0
total_rows  = 0
batch_rows  = []
batch_dates = 0

print(f"\nStarting backfill from {START_DATE} to {END_DATE}...")
print("Commits every 20 trading days. Re-runnable safely.\n")

while current <= END_DATE:
    if current.weekday() >= 5:          # skip weekends
        current += timedelta(days=1)
        continue

    if current in already_filled:       # skip already done
        current += timedelta(days=1)
        continue

    df = fetch_bhavcopy(current)

    if df is not None and len(df) > 0:
        rows = list(df.itertuples(index=False, name=None))
        batch_rows.extend(rows)
        total_rows  += len(rows)
        total_days  += 1
        batch_dates += 1
        print(f"  {current.strftime('%Y-%m-%d')} — {len(df)} stocks")
    else:
        print(f"  {current.strftime('%Y-%m-%d')} — no data (holiday or missing)")

    # Commit every BATCH_SIZE days
    if batch_dates >= BATCH_SIZE and batch_rows:
        execute_values(cur, """
            INSERT INTO prices
                (symbol, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                open_price  = EXCLUDED.open_price,
                high_price  = EXCLUDED.high_price,
                low_price   = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume      = EXCLUDED.volume
        """, batch_rows)
        conn.commit()
        print(f"\n  ✓ Committed {len(batch_rows):,} rows "
              f"({total_days} trading days so far)\n")
        batch_rows  = []
        batch_dates = 0

    time.sleep(SLEEP_SECONDS)
    current += timedelta(days=1)

# Final commit
if batch_rows:
    execute_values(cur, """
        INSERT INTO prices
            (symbol, date, open_price, high_price, low_price, close_price, volume)
        VALUES %s
        ON CONFLICT (symbol, date) DO UPDATE SET
            open_price  = EXCLUDED.open_price,
            high_price  = EXCLUDED.high_price,
            low_price   = EXCLUDED.low_price,
            close_price = EXCLUDED.close_price,
            volume      = EXCLUDED.volume
    """, batch_rows)
    conn.commit()
    print(f"\n  ✓ Final commit: {len(batch_rows):,} rows")

cur.close()
conn.close()

print(f"\n{'='*50}")
print(f"Backfill complete.")
print(f"  Trading days processed: {total_days}")
print(f"  Total rows upserted:    {total_rows:,}")
print(f"  Date range:             {START_DATE} to {END_DATE}")
print(f"{'='*50}")
print("\nNow run the backtest:")
print("  python backtest_obv_screeners.py")
