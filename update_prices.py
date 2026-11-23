"""
update_prices.py — Daily price updater
=======================================
Updates close_price for Nifty 500 stocks via yfinance.
Updates NIFTY500_IDX via yfinance ticker ^CRSLDX (replaces broken NSE library).

Cron: runs at 8:00 PM Mon-Fri
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values

load_dotenv()

# ── Nifty 500 stocks via yfinance ─────────────────────────────────────────────
nifty500   = pd.read_csv('nifty500.csv')
symbols    = nifty500['Symbol'].tolist()
nse_symbols = [s + '.NS' for s in symbols]

start_date = (datetime.today() - timedelta(days=5)).strftime('%Y-%m-%d')
end_date   = datetime.today().strftime('%Y-%m-%d')

print(f"Updating prices from {start_date} to {end_date}...")

batch_size = 50
all_rows   = []

for i in range(0, len(nse_symbols), batch_size):
    batch = nse_symbols[i:i+batch_size]
    df    = yf.download(batch, start=start_date, end=end_date,
                        auto_adjust=True, progress=False)
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
cur  = conn.cursor()
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

# ── NIFTY500_IDX via yfinance ^CRSLDX ────────────────────────────────────────
# Replaces broken NSE library (NSE redirected .com → .in breaking the nse package)
print("Updating NIFTY500_IDX...")
try:
    conn2 = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur2  = conn2.cursor()

    # Get last date in DB
    cur2.execute("SELECT MAX(date) FROM prices WHERE symbol='NIFTY500_IDX'")
    last_date = cur2.fetchone()[0]
    from_date = (last_date + timedelta(days=1)) if last_date else datetime(2024, 1, 1).date()
    to_date   = datetime.today().date()

    if from_date > to_date:
        print(f"NIFTY500_IDX already current to {last_date}")
    else:
        idx_df = yf.download(
            '^CRSLDX',
            start=from_date.strftime('%Y-%m-%d'),
            end=(to_date + timedelta(days=1)).strftime('%Y-%m-%d'),
            auto_adjust=True, progress=False
        )
        if idx_df.empty:
            print("NIFTY500_IDX: no data returned from yfinance")
        else:
            idx_df = idx_df.reset_index()[['Date', 'Close']]
            idx_df.columns = ['date', 'close_price']
            idx_df['symbol'] = 'NIFTY500_IDX'
            idx_df['date']   = idx_df['date'].dt.date
            idx_df = idx_df.dropna()
            idx_rows = [(r.symbol, r.date, float(r.close_price))
                        for r in idx_df.itertuples(index=False)]
            if idx_rows:
                execute_values(cur2, """
                    INSERT INTO prices (symbol, date, close_price)
                    VALUES %s
                    ON CONFLICT (symbol, date)
                    DO UPDATE SET close_price = EXCLUDED.close_price
                """, idx_rows)
                conn2.commit()
                print(f"NIFTY500_IDX: {len(idx_rows)} rows added/updated "
                      f"({idx_rows[0][1]} to {idx_rows[-1][1]})")
            else:
                print("NIFTY500_IDX: no rows to insert")

    cur2.close()
    conn2.close()

except Exception as e:
    print(f"NIFTY500_IDX update failed: {e}")

print(f"All done at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
