"""
fetch_thin_prices.py
Fetches full historical prices for symbols with thin price coverage.
Uses yfinance with NSE suffix (.NS).
"""

import os
import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import time

load_dotenv()

with open('thin_price_symbols.txt') as f:
    symbols = [s.strip() for s in f if s.strip()]
print(f"Fetching prices for {len(symbols)} thin-coverage symbols...")

def fetch_symbol_prices(symbol):
    ticker = f"{symbol}.NS"
    try:
        df = yf.download(ticker, start='2010-01-01', auto_adjust=True, progress=False)
        if df.empty:
            return []
        rows = []
        for dt, row in df.iterrows():
            close = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
            if close and close > 0:
                rows.append((
                    symbol,
                    dt.date(),
                    round(close, 4),
                    None, None, None, None, None, None  # open/high/low/vol/delivery not needed
                ))
        return rows
    except Exception as e:
        return []

BATCH_SIZE = 10
total_saved = 0
errors = []

for batch_start in range(0, len(symbols), BATCH_SIZE):
    batch = symbols[batch_start:batch_start+BATCH_SIZE]
    batch_rows = []

    for symbol in batch:
        rows = fetch_symbol_prices(symbol)
        if rows:
            batch_rows.extend(rows)
        else:
            errors.append(symbol)
        time.sleep(0.5)

    if batch_rows:
        # Deduplicate
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
            print(f"  ✗ DB error: {e}")
        finally:
            cur.close()
            conn.close()

    print(f"  ✓ {batch_start+len(batch)}/{len(symbols)} | saved={total_saved} errors={len(errors)}")

print(f"\n✓ Done. total_saved={total_saved} errors={len(errors)}")
if errors:
    print(f"Failed symbols: {errors}")
