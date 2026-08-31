"""
fetch_industry_pe.py — v2 fresh connection per batch
"""

import requests
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values
import os, time
from dotenv import load_dotenv

load_dotenv()

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

with open('all_historical_symbols.txt') as f:
    symbols = [s.strip() for s in f if s.strip()]
print(f"Total symbols: {len(symbols)}")

# Create table
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS industry_classification (
        id              SERIAL PRIMARY KEY,
        symbol          TEXT UNIQUE,
        broad_sector    TEXT,
        sector          TEXT,
        broad_industry  TEXT,
        industry        TEXT,
        industry_url    TEXT,
        fetched_date    DATE DEFAULT CURRENT_DATE
    );
""")
conn.commit()

# Get already-fetched symbols to allow resume
cur.execute("SELECT symbol FROM industry_classification")
already_done = set(row[0] for row in cur.fetchall())
cur.close()
conn.close()
print(f"Already fetched: {len(already_done)} symbols — resuming from where we left off")

remaining = [s for s in symbols if s not in already_done]
print(f"Remaining: {len(remaining)} symbols")

def fetch_company_industry(symbol):
    for url in [
        f'https://www.screener.in/company/{symbol}/consolidated/',
        f'https://www.screener.in/company/{symbol}/'
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.content, 'html.parser')
            peers = soup.find('section', {'id': 'peers'})
            if not peers:
                return None
            links = peers.find_all('a', title=True)
            data = {}
            for link in links:
                title = link.get('title', '')
                text  = link.text.strip()
                href  = link.get('href', '')
                if title == 'Broad Sector':    data['broad_sector']   = text
                elif title == 'Sector':        data['sector']         = text
                elif title == 'Broad Industry':data['broad_industry'] = text
                elif title == 'Industry':
                    data['industry']     = text
                    data['industry_url'] = href
            return data if data else None
        except:
            continue
    return None

BATCH_SIZE = 50
rows_saved = 0
errors = []

for batch_start in range(0, len(remaining), BATCH_SIZE):
    batch = remaining[batch_start:batch_start+BATCH_SIZE]
    batch_rows = []

    for symbol in batch:
        try:
            data = fetch_company_industry(symbol)
            if data:
                batch_rows.append((
                    symbol,
                    data.get('broad_sector'),
                    data.get('sector'),
                    data.get('broad_industry'),
                    data.get('industry'),
                    data.get('industry_url'),
                ))
            else:
                errors.append(symbol)
            time.sleep(1.0)
        except Exception as e:
            errors.append(symbol)

    if batch_rows:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur  = conn.cursor()
        try:
            execute_values(cur, """
                INSERT INTO industry_classification
                    (symbol, broad_sector, sector, broad_industry, industry, industry_url)
                VALUES %s
                ON CONFLICT (symbol) DO UPDATE SET
                    broad_sector    = EXCLUDED.broad_sector,
                    sector          = EXCLUDED.sector,
                    broad_industry  = EXCLUDED.broad_industry,
                    industry        = EXCLUDED.industry,
                    industry_url    = EXCLUDED.industry_url,
                    fetched_date    = CURRENT_DATE
            """, batch_rows)
            conn.commit()
            rows_saved += len(batch_rows)
        except Exception as e:
            conn.rollback()
            print(f"  ✗ DB error: {e}")
        finally:
            cur.close()
            conn.close()

    print(f"  ✓ {batch_start+len(batch)}/{len(remaining)} | saved={rows_saved} errors={len(errors)}")

print(f"\n✓ Done. saved={rows_saved} errors={len(errors)}")
