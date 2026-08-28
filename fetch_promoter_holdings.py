import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from nse import NSE
from datetime import datetime
import time

load_dotenv()

nse = NSE('/tmp')

nifty500 = pd.read_csv('nifty500.csv')
symbols = nifty500['Symbol'].tolist()

print(f"Fetching promoter holdings for {len(symbols)} stocks...")

all_rows = []
errors = []

for i, symbol in enumerate(symbols):
    try:
        data = nse.shareholding(symbol)
        for record in data:
            try:
                quarter_date = datetime.strptime(record['date'], '%d-%b-%Y').date()
                promoter_pct = float(record.get('pr_and_prgrp', 0) or 0)
                public_pct = float(record.get('public_val', 0) or 0)
                submission_date = datetime.strptime(record['submissionDate'], '%d-%b-%Y').date() if record.get('submissionDate') else None
                all_rows.append((symbol, quarter_date, promoter_pct, public_pct, submission_date))
            except Exception:
                continue
        if (i + 1) % 50 == 0:
            print(f"Progress: {i+1}/{len(symbols)} stocks fetched...")
        time.sleep(0.5)
    except Exception as e:
        errors.append(symbol)
        continue

# Deduplicate — keep last occurrence per symbol+date
seen = {}
for row in all_rows:
    key = (row[0], row[1])
    seen[key] = row
deduped_rows = list(seen.values())

print(f"Total rows after dedup: {len(deduped_rows)}")
print(f"Errors (skipped): {len(errors)} stocks")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO promoter_holdings (symbol, quarter_end_date, promoter_pct, public_pct, submission_date)
    VALUES %s
    ON CONFLICT (symbol, quarter_end_date) DO UPDATE SET
        promoter_pct = EXCLUDED.promoter_pct,
        public_pct = EXCLUDED.public_pct,
        submission_date = EXCLUDED.submission_date
""", deduped_rows)

conn.commit()
print(f"Rows upserted: {cur.rowcount}")
cur.close()
conn.close()
print(f"Done. Errors on: {errors[:10]}")
