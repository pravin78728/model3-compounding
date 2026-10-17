"""
fetch_missing_historical_prices.py
Attempts to fetch 2010-2022 prices for symbols missing from the training period.
Many will be delisted/renamed and return no data — that's expected.
"""

import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values
import os, time
from dotenv import load_dotenv

load_dotenv()

with open('missing_historical_prices.txt') as f:
    symbols = [s.strip() for s in f if s.strip()]
print(f"Attempting to fetch {len(symbols)} symbols...")

def fetch_prices(symbol):
    ticker = f"{symbol}.NS"
    try:
        df = yf.download(ticker, start='2010-01-01', end='2023-01-01',
                        auto_adjust=True, progress=False)
        if df.empty:
            return []
        rows = []
        for dt, row in df.iterrows():
            close = row['Close']
            if hasattr(close, 'iloc'): close = close.iloc[0]
            close = float(close)
            if close > 0:
                rows.append((symbol, dt.date(), round(close, 4),
                            None, None, None, None, None, None))
        return rows
    except:
        return []

BATCH = 20
total_saved = 0
fetched = 0
not_found = []

for batch_start in range(0, len(symbols), BATCH):
    batch = symbols[batch_start:batch_start+BATCH]
    batch_rows = []

    for symbol in batch:
        rows = fetch_prices(symbol)
        if rows:
            batch_rows.extend(rows)
            fetched += 1
        else:
            not_found.append(symbol)
        time.sleep(0.3)

    if batch_rows:
        seen = {}
        for row in batch_rows:
            seen[(row[0], row[1])] = row
        batch_rows = list(seen.values())

        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        try:
            execute_values(cur, """
                INSERT INTO prices
                    (symbol, date, close_price, open_price, high_price,
                     low_price, volume, delivery_qty, delivery_pct)
                VALUES %s
                ON CONFLICT (symbol, date) DO UPDATE SET
                    close_price = EXCLUDED.close_price
            """, batch_rows)
            conn.commit()
            total_saved += len(batch_rows)
        except Exception as e:
            conn.rollback()
            print(f"  DB error: {e}")
        finally:
            cur.close()
            conn.close()

    print(f"  ✓ {batch_start+len(batch)}/{len(symbols)} | fetched={fetched} not_found={len(not_found)} saved={total_saved}")

print(f"\n✓ Done. fetched={fetched} not_found={len(not_found)} saved={total_saved}")
print(f"Not found (likely delisted): {len(not_found)}")
print("Sample not found:", not_found[:15])
