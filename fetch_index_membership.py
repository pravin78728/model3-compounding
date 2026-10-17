import requests
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

load_dotenv()

print("Downloading index membership history...")
url = 'https://raw.githubusercontent.com/aditya-jha/nse-historical-membership/main/index_history/data/index_membership_history.csv'
headers = {'User-Agent': 'Mozilla/5.0'}
r = requests.get(url, headers=headers)

# Parse CSV
from io import StringIO
df = pd.read_csv(StringIO(r.text))
print(f"Total rows downloaded: {len(df)}")
print(f"Indices available: {df['index_name'].unique().tolist()[:10]}")

# Filter to only Nifty 500
nifty500 = df[df['index_name'] == 'Nifty 500'].copy()
print(f"Nifty 500 rows: {len(nifty500)}")

# Clean up dates
nifty500['valid_from'] = pd.to_datetime(nifty500['valid_from']).dt.date
nifty500['valid_to'] = pd.to_datetime(nifty500['valid_to'], errors='coerce').dt.date

# Prepare rows
rows = []
for _, row in nifty500.iterrows():
    rows.append((
        row['index_name'],
        row['symbol'],
        row['valid_from'],
        row['valid_to'] if pd.notna(row['valid_to']) else None,
        row['source']
    ))

print(f"Rows to insert: {len(rows)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO index_membership (index_name, symbol, valid_from, valid_to, source)
    VALUES %s
    ON CONFLICT (index_name, symbol, valid_from) DO NOTHING
""", rows)

conn.commit()
print(f"Rows inserted: {cur.rowcount}")
cur.close()
conn.close()
print("Done.")
