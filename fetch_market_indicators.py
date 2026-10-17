"""
fetch_market_indicators.py
Fetches Nifty 500, Nifty 50, and India VIX into prices table.
These are used by the regime classifier.
"""

import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

load_dotenv()

tickers = {
    'NIFTY500_IDX': '^CRSLDX',
    'NIFTY50_IDX':  '^NSEI',
    'INDIAVIX_IDX': '^INDIAVIX',
}

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()

for symbol, ticker in tickers.items():
    print(f"Fetching {ticker} as {symbol}...")
    df = yf.download(ticker, start='2010-01-01', end='2026-08-31',
                     auto_adjust=True, progress=False)
    if df.empty:
        print(f"  ✗ No data")
        continue

    rows = []
    for dt, row in df.iterrows():
        close = row['Close']
        if hasattr(close, 'iloc'):
            close = close.iloc[0]
        close = float(close)
        if close and close > 0:
            rows.append((symbol, dt.date(), round(close, 4),
                        None, None, None, None, None, None))

    if rows:
        execute_values(cur, """
            INSERT INTO prices
                (symbol, date, close_price, open_price, high_price,
                 low_price, volume, delivery_qty, delivery_pct)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                close_price = EXCLUDED.close_price
        """, rows)
        conn.commit()
        print(f"  ✓ {len(rows)} rows saved")

cur.execute("""
    SELECT symbol, COUNT(*), MIN(date), MAX(date)
    FROM prices
    WHERE symbol IN ('NIFTY500_IDX','NIFTY50_IDX','INDIAVIX_IDX')
    GROUP BY symbol
""")
print("\nVerification:")
for row in cur.fetchall():
    print(' ', row)

cur.close()
conn.close()
print("\n✓ Done")
