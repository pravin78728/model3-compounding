"""
fetch_promoter_full.py
Fetches promoter holdings for ALL 951 historical symbols via NSE API.
Saves in batches of 100 to avoid timeout.
"""
import psycopg2
from psycopg2.extras import execute_values
import os, time
from dotenv import load_dotenv
from nse import NSE
from datetime import datetime

load_dotenv()

with open('all_historical_symbols.txt') as f:
    symbols = [s.strip() for s in f if s.strip()]
print(f"Total symbols: {len(symbols)}")

nse = NSE('/tmp')

def fetch_promoter(symbol):
    rows = []
    data = nse.shareholding(symbol)
    for record in data:
        try:
            quarter_date    = datetime.strptime(record['date'], '%d-%b-%Y').date()
            promoter_pct    = float(record.get('pr_and_prgrp', 0) or 0)
            public_pct      = float(record.get('public_val', 0) or 0)
            submission_date = None
            if record.get('submissionDate'):
                submission_date = datetime.strptime(record['submissionDate'], '%d-%b-%Y').date()
            rows.append((symbol, quarter_date, promoter_pct, public_pct, submission_date))
        except Exception:
            continue
    return rows

BATCH_SIZE = 100
errors = []
total_saved = 0

for batch_start in range(0, len(symbols), BATCH_SIZE):
    batch_symbols = symbols[batch_start:batch_start + BATCH_SIZE]
    batch_rows = []

    for symbol in batch_symbols:
        try:
            rows = fetch_promoter(symbol)
            batch_rows.extend(rows)
            time.sleep(0.5)
        except Exception as e:
            errors.append((symbol, str(e)))

    seen = {}
    for row in batch_rows:
        seen[(row[0], row[1])] = row
    batch_rows = list(seen.values())

    if batch_rows:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur  = conn.cursor()
        try:
            execute_values(cur, """
                INSERT INTO promoter_holdings
                    (symbol, quarter_end_date, promoter_pct, public_pct, submission_date)
                VALUES %s
                ON CONFLICT (symbol, quarter_end_date) DO UPDATE SET
                    promoter_pct    = EXCLUDED.promoter_pct,
                    public_pct      = EXCLUDED.public_pct,
                    submission_date = EXCLUDED.submission_date
            """, batch_rows)
            conn.commit()
            total_saved += len(batch_rows)
        except Exception as e:
            conn.rollback()
            print(f"  ✗ DB error: {e}")
        finally:
            cur.close()
            conn.close()

    print(f"  ✓ symbols {batch_start+1}–{batch_start+len(batch_symbols)} | "
          f"saved={total_saved} errors={len(errors)}")

print(f"\n✓ Done. total_saved={total_saved} errors={len(errors)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()
cur.execute("SELECT MIN(quarter_end_date), MAX(quarter_end_date), COUNT(*), COUNT(DISTINCT symbol) FROM promoter_holdings")
print(f"Table summary: {cur.fetchone()}")
cur.close()
conn.close()
