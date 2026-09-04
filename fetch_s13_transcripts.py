"""
fetch_s13_transcripts.py v2
Fetches ALL earnings call transcripts from NSE for each symbol.
Gets multiple quarters per symbol going back to 2022.
"""

import os, requests, io, time, psycopg2
from dotenv import load_dotenv
from datetime import datetime, date
from nse import NSE
import pypdf

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS concall_transcripts (
        id              SERIAL PRIMARY KEY,
        symbol          TEXT,
        transcript_date DATE,
        fiscal_quarter  TEXT,
        pdf_url         TEXT,
        transcript_text TEXT,
        word_count      INTEGER,
        fetched_at      TIMESTAMP DEFAULT NOW(),
        UNIQUE(symbol, transcript_date)
    );
""")
conn.commit()

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
nse = NSE('/tmp')

def extract_pdf_text(url):
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code != 200: return None, 0
        reader = pypdf.PdfReader(io.BytesIO(r.content))
        text = ''.join(page.extract_text() or '' for page in reader.pages)
        return text.strip(), len(text.split())
    except:
        return None, 0

def get_fiscal_quarter(t_date):
    if not t_date: return None
    m, y = t_date.month, t_date.year
    if m in [4,5]:   return f"Q4FY{y}"
    elif m in [7,8]: return f"Q1FY{y+1}"
    elif m in [10,11]: return f"Q2FY{y+1}"
    elif m in [1,2]: return f"Q3FY{y}"
    return f"FY{y}"

def get_all_transcripts(symbol, from_date, to_date):
    """Get ALL transcript URLs for a symbol in date range."""
    found = []
    try:
        announcements = nse.announcements(symbol=symbol, from_date=from_date, to_date=to_date)
        for a in announcements:
            file_url = a.get('attchmntFile', '')
            if file_url and any(w in file_url.lower() for w in
                               ['transcript', 'concall', 'earningcall', 'earningscall']):
                date_str = a.get('sort_date', '')[:10]
                try:
                    t_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    found.append((file_url, t_date))
                except:
                    pass
    except:
        pass
    return found

# Load priority symbols
cur.execute("""
    SELECT DISTINCT symbol FROM model3_training_data
    WHERE in_forward_test=TRUE OR rebalance_date >= '2022-01-01'
""")
symbols = [row[0] for row in cur.fetchall()]
print(f"Fetching all transcripts for {len(symbols)} symbols (2022-2026)")

from_date = datetime(2022, 1, 1)
to_date   = datetime(2026, 8, 28)

saved = 0
skipped = 0
errors = 0

for i, symbol in enumerate(symbols):
    try:
        transcripts = get_all_transcripts(symbol, from_date, to_date)
        if not transcripts:
            skipped += 1
            time.sleep(0.3)
            continue

        for url, t_date in transcripts:
            # Check if already exists
            cur.execute("""
                SELECT COUNT(*) FROM concall_transcripts
                WHERE symbol=%s AND transcript_date=%s
            """, (symbol, t_date))
            if cur.fetchone()[0] > 0:
                continue

            text, wc = extract_pdf_text(url)
            if not text or wc < 200:
                continue

            quarter = get_fiscal_quarter(t_date)
            cur.execute("""
                INSERT INTO concall_transcripts
                    (symbol, transcript_date, fiscal_quarter, pdf_url, transcript_text, word_count)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (symbol, transcript_date) DO NOTHING
            """, (symbol, t_date, quarter, url, text[:50000], wc))
            conn.commit()
            saved += 1
            time.sleep(0.3)

    except Exception as e:
        errors += 1

    if (i+1) % 25 == 0:
        print(f"  {i+1}/{len(symbols)} | saved={saved} skipped={skipped} errors={errors}")

print(f"\n✓ Done. saved={saved} skipped={skipped} errors={errors}")
cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol) FROM concall_transcripts")
print("Table:", cur.fetchone())
cur.close()
conn.close()
