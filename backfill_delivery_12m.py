"""
backfill_delivery_12m.py — One-time delivery backfill
======================================================
Fills delivery_pct gaps for the last 12 months.
Checks NSE archives for each missing date and updates the DB.
Re-runnable safely — only fetches dates that are still missing.

Usage:
    python backfill_delivery_12m.py
"""

import requests
import pandas as pd
from io import BytesIO
import psycopg2
from psycopg2.extras import execute_values
import os
import time
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.nseindia.com'
}

def fetch_delivery_for_date(date):
    date_str = date.strftime('%d%m%Y')
    url = f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv'
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        df = pd.read_csv(BytesIO(r.content))
        df.columns = df.columns.str.strip()
        if 'SERIES' not in df.columns:
            return None, "unexpected CSV format"
        df = df[df['SERIES'].str.strip() == 'EQ'].copy()
        df = df[['SYMBOL','DATE1','DELIV_QTY','DELIV_PER']].copy()
        df.columns = ['symbol','date','delivery_qty','delivery_pct']
        df['symbol']       = df['symbol'].str.strip()
        df['date']         = pd.to_datetime(df['date'].str.strip(), format='%d-%b-%Y').dt.date
        df['delivery_qty'] = pd.to_numeric(df['delivery_qty'], errors='coerce')
        df['delivery_pct'] = pd.to_numeric(df['delivery_pct'], errors='coerce')
        df = df.dropna()
        return df, None
    except Exception as e:
        return None, str(e)

def get_missing_dates(conn, start_date, end_date):
    """Get all weekdays with <50% delivery populated between start and end."""
    cur = conn.cursor()
    cur.execute("""
        SELECT date,
               COUNT(*) as total,
               COUNT(delivery_pct) as with_del
        FROM prices
        WHERE date BETWEEN %s AND %s
        AND symbol != 'NIFTY500_IDX'
        GROUP BY date
        HAVING COUNT(delivery_pct) * 2 < COUNT(*)
        ORDER BY date ASC
    """, (start_date, end_date))
    rows = cur.fetchall()
    cur.close()
    # Filter weekdays only, exclude today
    today = datetime.today().date()
    missing = [(r[0], r[1], r[2]) for r in rows
               if r[0].weekday() < 5 and r[0] < today]
    return missing

def main():
    today     = datetime.today().date()
    start     = today - timedelta(days=365)  # 12 months back
    end       = today - timedelta(days=1)    # yesterday

    print(f"Delivery Backfill — 12 months ({start} to {end})")
    print("="*60)

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))

    print("Scanning for missing delivery dates...")
    missing = get_missing_dates(conn, start, end)
    print(f"Found {len(missing)} dates needing delivery data\n")

    if not missing:
        print("All delivery data complete for last 12 months.")
        conn.close()
        return

    cur = conn.cursor()
    success = 0
    not_available = 0
    errors = 0

    for i, (d, total, with_del) in enumerate(missing):
        pct_done = (i+1)/len(missing)*100
        print(f"[{i+1:3d}/{len(missing)}] {d} ({total} stocks, {with_del} have delivery)...",
              end=" ", flush=True)

        df, err = fetch_delivery_for_date(datetime.combine(d, datetime.min.time()))

        if df is None:
            print(f"Not available: {err}")
            not_available += 1
            time.sleep(0.3)
            continue

        rows = list(df.itertuples(index=False, name=None))
        cur.execute("""
            CREATE TEMP TABLE tmp_del (
                symbol TEXT, date DATE,
                delivery_qty BIGINT, delivery_pct NUMERIC
            ) ON COMMIT DROP;
        """)
        execute_values(cur, """
            INSERT INTO tmp_del (symbol,date,delivery_qty,delivery_pct)
            VALUES %s
        """, rows)
        cur.execute("""
            UPDATE prices p
            SET delivery_qty = t.delivery_qty,
                delivery_pct = t.delivery_pct
            FROM tmp_del t
            WHERE p.symbol = t.symbol AND p.date = t.date
            AND (p.delivery_pct IS NULL OR p.delivery_pct != t.delivery_pct)
        """)
        updated = cur.rowcount
        conn.commit()
        print(f"{len(df)} fetched, {updated} updated ✓")
        success += 1
        time.sleep(0.3)  # polite delay to avoid rate limiting

    cur.close()
    conn.close()

    print(f"\n{'='*60}")
    print(f"Backfill complete:")
    print(f"  Dates successfully updated: {success}")
    print(f"  Dates not available on NSE: {not_available}")
    print(f"  Errors: {errors}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
