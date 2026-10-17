import requests
import pandas as pd
from io import BytesIO
import zipfile
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

def fetch_bhavcopy(date):
    date_str = date.strftime('%Y%m%d')
    url = f'https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"No data for {date.strftime('%Y-%m-%d')} (status {r.status_code})")
        return None
    z = zipfile.ZipFile(BytesIO(r.content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    # Keep only equity series (EQ)
    df = df[df['SctySrs'] == 'EQ'].copy()
    df = df[['TckrSymb', 'TradDt', 'OpnPric', 'HghPric', 'LwPric', 'ClsPric', 'TtlTradgVol']].copy()
    df.columns = ['symbol', 'date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume']
    df['date'] = pd.to_datetime(df['date']).dt.date
    df = df.dropna()
    return df

# Test: fetch last 5 trading days
all_rows = []
today = datetime.today()
days_checked = 0
days_fetched = 0

for i in range(10):  # check last 10 calendar days to get 5 trading days
    date = today - timedelta(days=i)
    if date.weekday() >= 5:  # skip weekends
        continue
    df = fetch_bhavcopy(date)
    if df is not None:
        all_rows.extend(list(df.itertuples(index=False, name=None)))
        print(f"Fetched {len(df)} stocks for {date.strftime('%Y-%m-%d')}")
        days_fetched += 1
    if days_fetched >= 3:
        break

print(f"Total rows: {len(all_rows)}")

# Insert into database
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO prices (symbol, date, open_price, high_price, low_price, close_price, volume)
    VALUES %s
    ON CONFLICT (symbol, date) DO UPDATE SET
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        volume = EXCLUDED.volume
""", all_rows)

conn.commit()
print(f"Rows upserted: {cur.rowcount}")
cur.close()
conn.close()
print("Done.")
