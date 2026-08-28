import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

# Load Nifty 500 symbols
nifty500 = pd.read_csv('nifty500.csv')
symbols = nifty500['Symbol'].tolist()
nse_symbols = [s + '.NS' for s in symbols]

# Only fetch last 5 days (catches any missed days)
start_date = (datetime.today() - timedelta(days=5)).strftime('%Y-%m-%d')
end_date = datetime.today().strftime('%Y-%m-%d')

print(f"Updating prices from {start_date} to {end_date}...")

batch_size = 50
all_rows = []

for i in range(0, len(nse_symbols), batch_size):
    batch = nse_symbols[i:i+batch_size]
    df = yf.download(batch, start=start_date, end=end_date, auto_adjust=True, progress=False)
    
    if df.empty:
        continue

    close_df = df['Close'].copy()
    close_df.columns = [c.replace('.NS', '') for c in close_df.columns]
    close_df = close_df.reset_index()
    close_df = close_df.melt(id_vars='Date', var_name='symbol', value_name='close_price')
    close_df = close_df.dropna()
    close_df['date'] = close_df['Date'].dt.date
    close_df = close_df[['symbol', 'date', 'close_price']]
    all_rows.extend(list(close_df.itertuples(index=False, name=None)))

print(f"Rows to insert: {len(all_rows)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO prices (symbol, date, close_price)
    VALUES %s
    ON CONFLICT (symbol, date) DO NOTHING
""", all_rows)

conn.commit()
inserted = cur.rowcount
cur.close()
conn.close()

print(f"Done. New rows inserted: {inserted}")
print(f"Run completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
