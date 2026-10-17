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

def fetch_delivery(date):
    date_str = date.strftime('%d%m%Y')
    url = f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"No delivery data for {date.strftime('%Y-%m-%d')} (status {r.status_code})")
        return None
    df = pd.read_csv(BytesIO(r.content))
    df.columns = df.columns.str.strip()
    df = df[df['SERIES'].str.strip() == 'EQ'].copy()
    df = df[['SYMBOL', 'DATE1', 'DELIV_QTY', 'DELIV_PER']].copy()
    df.columns = ['symbol', 'date', 'delivery_qty', 'delivery_pct']
    df['symbol'] = df['symbol'].str.strip()
    df['date'] = pd.to_datetime(df['date'].str.strip(), format='%d-%b-%Y').dt.date
    df = df.dropna()
    return df

today = datetime.today()
days_fetched = 0

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

for i in range(10):
    date = today - timedelta(days=i)
    if date.weekday() >= 5:
        continue
    df = fetch_delivery(date)
    if df is not None:
        print(f"Fetched delivery data for {date.strftime('%Y-%m-%d')}: {len(df)} stocks")
        rows = list(df.itertuples(index=False, name=None))
        # Use temp table to do a safe bulk update — only updates existing rows
        cur.execute("""
            CREATE TEMP TABLE tmp_delivery (
                symbol TEXT,
                date DATE,
                delivery_qty BIGINT,
                delivery_pct NUMERIC
            ) ON COMMIT DROP;
        """)
        execute_values(cur, """
            INSERT INTO tmp_delivery (symbol, date, delivery_qty, delivery_pct)
            VALUES %s
        """, rows)
        cur.execute("""
            UPDATE prices p
            SET delivery_qty = t.delivery_qty,
                delivery_pct = t.delivery_pct
            FROM tmp_delivery t
            WHERE p.symbol = t.symbol AND p.date = t.date;
        """)
        updated = cur.rowcount
        conn.commit()
        print(f"Updated {updated} rows for {date.strftime('%Y-%m-%d')}")
        days_fetched += 1
    if days_fetched >= 3:
        break

cur.close()
conn.close()
print("Done.")
