import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from io import StringIO

load_dotenv()

print("Downloading shareholding history from NSE historical membership repo...")
url = 'https://raw.githubusercontent.com/aditya-jha/nse-historical-membership/main/shareholding_history/data/parsed/_flat.csv'
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, headers=headers, timeout=60)
print(f"Downloaded: {len(r.content)} bytes")

df = pd.read_csv(StringIO(r.text))
print(f"Total rows: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

# Clean up
df = df.rename(columns={'ticker': 'symbol'})
df['period'] = pd.to_datetime(df['period'], format='%Y-%m', errors='coerce') + pd.offsets.MonthEnd(0)
df = df.dropna(subset=['symbol', 'period'])

# Keep only Nifty 500 symbols to keep table focused
nifty500 = pd.read_csv('nifty500.csv')
nifty500_symbols = nifty500['Symbol'].tolist()
df = df[df['symbol'].isin(nifty500_symbols)].copy()
print(f"Rows after Nifty 500 filter: {len(df)}")

# Parse numeric columns safely
for col in ['promoter_pct', 'fii_pct', 'dii_pct', 'public_pct']:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Deduplicate
df = df.sort_values(['symbol', 'period']).drop_duplicates(subset=['symbol', 'period'], keep='last')

# Build rows
rows = []
for _, row in df.iterrows():
    rows.append((
        row['symbol'],
        row['period'].date(),
        row['promoter_pct'] if pd.notna(row['promoter_pct']) else None,
        row['fii_pct'] if pd.notna(row['fii_pct']) else None,
        row['dii_pct'] if pd.notna(row['dii_pct']) else None,
        row['public_pct'] if pd.notna(row['public_pct']) else None,
        None,  # pledge_pct not in this file
    ))

print(f"Rows to insert: {len(rows)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO institutional_holdings
        (symbol, period, promoter_pct, fii_pct, dii_pct, public_pct, pledge_pct)
    VALUES %s
    ON CONFLICT (symbol, period) DO UPDATE SET
        promoter_pct = EXCLUDED.promoter_pct,
        fii_pct = EXCLUDED.fii_pct,
        dii_pct = EXCLUDED.dii_pct,
        public_pct = EXCLUDED.public_pct
""", rows)

conn.commit()
print(f"Rows upserted: {cur.rowcount}")

# Verify
cur.execute("SELECT COUNT(*) FROM institutional_holdings;")
print(f"Total rows in table: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(DISTINCT symbol) FROM institutional_holdings;")
print(f"Total symbols: {cur.fetchone()[0]}")
cur.execute("""
    SELECT symbol, period, promoter_pct, fii_pct, dii_pct
    FROM institutional_holdings
    WHERE symbol = 'INFY'
    ORDER BY period DESC LIMIT 5;
""")
print("\nINFY institutional holdings:")
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
print("\nDone.")
