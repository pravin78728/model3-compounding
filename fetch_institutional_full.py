import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from io import StringIO

load_dotenv()

with open('all_historical_symbols.txt') as f:
    all_symbols = set(s.strip() for s in f if s.strip())
print(f"Total symbols to include: {len(all_symbols)}")

print("Downloading shareholding history CSV...")
url = 'https://raw.githubusercontent.com/aditya-jha/nse-historical-membership/main/shareholding_history/data/parsed/_flat.csv'
r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=60)
print(f"Downloaded: {len(r.content):,} bytes")

df = pd.read_csv(StringIO(r.text))
print(f"Total rows in CSV: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

# Rename and parse dates FIRST, then show range
df = df.rename(columns={'ticker': 'symbol'})
df['period'] = pd.to_datetime(df['period'], format='%Y-%m', errors='coerce') + pd.offsets.MonthEnd(0)
df = df.dropna(subset=['symbol', 'period'])
print(f"Date range: {df['period'].min().date()} → {df['period'].max().date()}")

# Filter to all 951 historical symbols
df = df[df['symbol'].isin(all_symbols)].copy()
print(f"Rows after historical symbol filter: {len(df)}")

for col in ['promoter_pct', 'fii_pct', 'dii_pct', 'public_pct']:
    df[col] = pd.to_numeric(df[col], errors='coerce')

df = df.sort_values(['symbol', 'period']).drop_duplicates(subset=['symbol', 'period'], keep='last')

rows = []
for _, row in df.iterrows():
    rows.append((
        row['symbol'],
        row['period'].date(),
        float(row['promoter_pct']) if pd.notna(row['promoter_pct']) else None,
        float(row['fii_pct'])      if pd.notna(row['fii_pct'])      else None,
        float(row['dii_pct'])      if pd.notna(row['dii_pct'])      else None,
        float(row['public_pct'])   if pd.notna(row['public_pct'])   else None,
        None,
    ))

print(f"Rows to upsert: {len(rows)}")

BATCH = 2000
total = 0
for i in range(0, len(rows), BATCH):
    batch = rows[i:i+BATCH]
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur  = conn.cursor()
    execute_values(cur, """
        INSERT INTO institutional_holdings
            (symbol, period, promoter_pct, fii_pct, dii_pct, public_pct, pledge_pct)
        VALUES %s
        ON CONFLICT (symbol, period) DO UPDATE SET
            promoter_pct = EXCLUDED.promoter_pct,
            fii_pct      = EXCLUDED.fii_pct,
            dii_pct      = EXCLUDED.dii_pct,
            public_pct   = EXCLUDED.public_pct
    """, batch)
    conn.commit()
    total += len(batch)
    cur.close()
    conn.close()
    print(f"  ✓ {total}/{len(rows)} rows saved")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()
cur.execute("SELECT MIN(period), MAX(period), COUNT(*), COUNT(DISTINCT symbol) FROM institutional_holdings")
print(f"\nTable summary: {cur.fetchone()}")
cur.close()
conn.close()
print("✓ Done")
