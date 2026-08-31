"""
fetch_industry_median_pe.py v2 — correct column index for PE
"""

import requests
from bs4 import BeautifulSoup
import psycopg2
import os, time
from dotenv import load_dotenv

load_dotenv()

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()

cur.execute("""
    ALTER TABLE industry_classification
    ADD COLUMN IF NOT EXISTS industry_median_pe NUMERIC;
""")
conn.commit()

cur.execute("""
    SELECT DISTINCT industry_url
    FROM industry_classification
    WHERE industry_url IS NOT NULL
    ORDER BY industry_url
""")
urls = [row[0] for row in cur.fetchall()]
print(f"Unique industry URLs to fetch: {len(urls)}")

def get_median_pe(industry_url):
    """Fetch industry page, extract PE from column index 3, return median."""
    try:
        r = requests.get(f'https://www.screener.in{industry_url}',
                         headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.content, 'html.parser')
        table = soup.find('table')
        if not table:
            return None
        pe_values = []
        rows = table.find_all('tr')[1:]  # skip header
        for row in rows:
            cols = row.find_all('td')
            # Row format: S.No | Name | CMP | P/E | MarCap | ...
            # PE is at index 3
            if len(cols) >= 4:
                try:
                    pe_text = cols[3].text.strip().replace(',', '')
                    pe = float(pe_text)
                    if 0 < pe < 500:
                        pe_values.append(pe)
                except:
                    pass
        if pe_values:
            pe_values.sort()
            return round(pe_values[len(pe_values)//2], 2)
    except:
        pass
    return None

success = 0
failed  = 0

for i, url in enumerate(urls):
    median_pe = get_median_pe(url)
    if median_pe:
        cur.execute("""
            UPDATE industry_classification
            SET industry_median_pe = %s
            WHERE industry_url = %s
        """, (median_pe, url))
        success += 1
    else:
        failed += 1
    if (i+1) % 10 == 0:
        conn.commit()
        print(f"  ✓ {i+1}/{len(urls)} | success={success} failed={failed}")
    time.sleep(1.0)

conn.commit()

# Verify
cur.execute("""
    SELECT COUNT(*), COUNT(industry_median_pe),
           ROUND(AVG(industry_median_pe)::numeric, 1)
    FROM industry_classification
""")
print('\nTable summary:', cur.fetchone())

cur.execute("""
    SELECT industry, industry_median_pe
    FROM industry_classification
    WHERE industry_median_pe IS NOT NULL
    GROUP BY industry, industry_median_pe
    ORDER BY industry_median_pe DESC
    LIMIT 10
""")
print('\nHighest median PE industries:')
for row in cur.fetchall():
    print(' ', row)

cur.close()
conn.close()
print(f"\n✓ Done. success={success} failed={failed}")
