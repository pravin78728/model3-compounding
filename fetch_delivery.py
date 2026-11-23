"""
fetch_delivery.py — Delivery % updater
=======================================
Fetches NSE delivery data for any date in the last 30 days
where delivery_pct is NULL in the prices table.
Self-healing: automatically backfills any gaps.

Cron: runs at 8:30 PM Mon-Fri (after bhavcopy loads)
"""

import requests
import pandas as pd
from io import BytesIO
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.nseindia.com'
}

def fetch_delivery_for_date(date):
    """Fetch NSE delivery CSV for a given date. Returns DataFrame or None."""
    date_str = date.strftime('%d%m%Y')
    url = f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv'
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"  {date.strftime('%Y-%m-%d')}: HTTP {r.status_code} — skipping")
            return None
        df = pd.read_csv(BytesIO(r.content))
        df.columns = df.columns.str.strip()
        if 'SERIES' not in df.columns:
            print(f"  {date.strftime('%Y-%m-%d')}: unexpected CSV format — skipping")
            return None
        df = df[df['SERIES'].str.strip() == 'EQ'].copy()
        df = df[['SYMBOL', 'DATE1', 'DELIV_QTY', 'DELIV_PER']].copy()
        df.columns = ['symbol', 'date', 'delivery_qty', 'delivery_pct']
        df['symbol']       = df['symbol'].str.strip()
        df['date']         = pd.to_datetime(df['date'].str.strip(), format='%d-%b-%Y').dt.date
        df['delivery_qty'] = pd.to_numeric(df['delivery_qty'], errors='coerce')
        df['delivery_pct'] = pd.to_numeric(df['delivery_pct'], errors='coerce')
        df = df.dropna()
        return df
    except Exception as e:
        print(f"  {date.strftime('%Y-%m-%d')}: ERROR — {e}")
        return None


def get_dates_missing_delivery(conn, lookback_days=30):
    """
    Returns list of dates in the last lookback_days that have:
    - At least some price rows (the date exists in prices table)
    - But delivery_pct is NULL for most rows on that date
    - And it's a weekday
    """
    cutoff = (datetime.today() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    today  = datetime.today().strftime('%Y-%m-%d')
    cur = conn.cursor()
    cur.execute("""
        SELECT date,
               COUNT(*) as total_rows,
               COUNT(delivery_pct) as rows_with_delivery,
               COUNT(*) - COUNT(delivery_pct) as rows_missing
        FROM prices
        WHERE date BETWEEN %s AND %s
        AND symbol != 'NIFTY500_IDX'
        GROUP BY date
        HAVING COUNT(delivery_pct) * 2 < COUNT(*)
        ORDER BY date DESC
    """, (cutoff, today))
    rows = cur.fetchall()
    cur.close()
    print(f"  Raw query returned {len(rows)} date(s) with missing delivery")
    if rows:
        print(f"  Sample row: {rows[0]}")
    # Filter to weekdays only
    missing = []
    for row in rows:
        try:
            d        = row[0]
            total    = row[1]
            with_del = row[2]
            miss     = row[3]
            if hasattr(d, 'weekday') and d.weekday() < 5:
                missing.append((d, total, with_del, miss))
        except (IndexError, TypeError):
            continue
    return missing


def main():
    today = datetime.today()
    print(f"Fetch Delivery — {today.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)

    conn = psycopg2.connect(os.getenv('DATABASE_URL'))

    # Find dates with missing delivery
    print("Checking for dates with missing delivery data...")
    missing_dates = get_dates_missing_delivery(conn, lookback_days=30)

    if not missing_dates:
        print("All delivery data is current. Nothing to fetch.")
        conn.close()
        return

    print(f"Found {len(missing_dates)} date(s) with missing delivery:\n")
    for d, total, with_del, missing in missing_dates:
        print(f"  {d}: {missing}/{total} rows missing delivery%")

    print()
    cur = conn.cursor()
    total_updated = 0

    for d, total, with_del, missing in missing_dates:
        date_dt = datetime.combine(d, datetime.min.time())

        # Skip today — NSE delivery data not available until after market close
        if d == today.date():
            print(f"  {d}: Today — delivery data not yet published, skipping")
            continue

        print(f"  Fetching {d}...", end=" ")
        df = fetch_delivery_for_date(date_dt)

        if df is None or df.empty:
            print(f"No data available from NSE")
            continue

        print(f"{len(df)} stocks fetched — updating DB...", end=" ")

        # Upsert into temp table then update prices
        cur.execute("""
            CREATE TEMP TABLE tmp_delivery (
                symbol TEXT,
                date DATE,
                delivery_qty BIGINT,
                delivery_pct NUMERIC
            ) ON COMMIT DROP;
        """)
        rows = list(df.itertuples(index=False, name=None))
        execute_values(cur, """
            INSERT INTO tmp_delivery (symbol, date, delivery_qty, delivery_pct)
            VALUES %s
        """, rows)
        cur.execute("""
            UPDATE prices p
            SET delivery_qty = t.delivery_qty,
                delivery_pct = t.delivery_pct
            FROM tmp_delivery t
            WHERE p.symbol = t.symbol
            AND p.date = t.date
            AND (p.delivery_pct IS NULL OR p.delivery_pct != t.delivery_pct)
        """)
        updated = cur.rowcount
        conn.commit()
        total_updated += updated
        print(f"{updated} rows updated")

    cur.close()
    conn.close()
    print(f"\nDone. Total rows updated: {total_updated}")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
