import yfinance as yf
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']
nse_symbols = [s + '.NS' for s in symbols]

print("Downloading price data...")
df = yf.download(nse_symbols, start='2010-01-01', end=datetime.today().strftime('%Y-%m-%d'), auto_adjust=True)

close_df = df['Close'].copy()
close_df.columns = [c.replace('.NS', '') for c in close_df.columns]
close_df = close_df.reset_index()
close_df = close_df.melt(id_vars='Date', var_name='symbol', value_name='close_price')
close_df = close_df.dropna()
close_df['date'] = close_df['Date'].dt.date
close_df = close_df[['symbol', 'date', 'close_price']]

print(f"Rows to insert: {len(close_df)}")

rows = list(close_df.itertuples(index=False, name=None))

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO prices (symbol, date, close_price)
    VALUES %s
    ON CONFLICT (symbol, date) DO NOTHING
""", rows)

conn.commit()
inserted = cur.rowcount
cur.close()
conn.close()

print(f"Done. Rows inserted: {inserted}")
