import requests
from bs4 import BeautifulSoup
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
import time

load_dotenv()

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

def get_row(section, label):
    if not section:
        return []
    for row in section.find_all('tr'):
        cols = row.find_all('td')
        if cols and label.lower() in cols[0].text.lower():
            return [c.text.strip().replace(',','').replace('%','').replace('\xa0','').replace('+','').strip() for c in cols[1:]]
    return []

def get_headers(section):
    if not section:
        return []
    header_row = section.find('tr')
    if not header_row:
        return []
    return [th.text.strip() for th in header_row.find_all('th')[1:]]

def parse_num(val):
    try:
        return float(val)
    except:
        return None

def parse_year(label):
    try:
        return int(label.strip().split()[-1])
    except:
        return None

def fetch_data(symbol):
    for url in [
        f'https://www.screener.in/company/{symbol}/consolidated/',
        f'https://www.screener.in/company/{symbol}/'
    ]:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            break
    else:
        return [], []

    soup = BeautifulSoup(r.content, 'html.parser')
    qr = soup.find('section', {'id': 'quarters'})
    cf = soup.find('section', {'id': 'cash-flow'})

    # Quarterly financials
    q_rows = []
    if qr:
        quarters = get_headers(qr)
        sales = get_row(qr, 'Sales')
        profit = get_row(qr, 'Net Profit')
        eps = get_row(qr, 'EPS')
        opm = get_row(qr, 'OPM')
        for i, q in enumerate(quarters):
            if not q or q == 'TTM':
                continue
            q_rows.append((
                symbol, q,
                parse_num(sales[i]) if i < len(sales) else None,
                parse_num(profit[i]) if i < len(profit) else None,
                parse_num(eps[i]) if i < len(eps) else None,
                parse_num(opm[i]) if i < len(opm) else None,
            ))

    # Cash flow
    cf_rows = []
    if cf:
        years = get_headers(cf)
        cfo = get_row(cf, 'Cash from Opera')
        cfi = get_row(cf, 'Cash from Inves')
        cff = get_row(cf, 'Cash from Finan')
        fcf = get_row(cf, 'Free Cash Flow')
        for i, y in enumerate(years):
            yr = parse_year(y)
            if not yr:
                continue
            cf_rows.append((
                symbol, yr,
                parse_num(cfo[i]) if i < len(cfo) else None,
                parse_num(cfi[i]) if i < len(cfi) else None,
                parse_num(cff[i]) if i < len(cff) else None,
                parse_num(fcf[i]) if i < len(fcf) else None,
            ))

    return q_rows, cf_rows

# Load Nifty 500
nifty500 = pd.read_csv('nifty500.csv')
symbols = nifty500['Symbol'].tolist()

print(f"Fetching quarterly + cashflow data for {len(symbols)} stocks...")

all_q_rows = []
all_cf_rows = []
errors = []

for i, symbol in enumerate(symbols):
    try:
        q_rows, cf_rows = fetch_data(symbol)
        all_q_rows.extend(q_rows)
        all_cf_rows.extend(cf_rows)
        if (i + 1) % 50 == 0:
            print(f"Progress: {i+1}/{len(symbols)} | Q rows: {len(all_q_rows)} | CF rows: {len(all_cf_rows)}")
        time.sleep(1)
    except Exception as e:
        errors.append(symbol)
        continue

# Deduplicate
seen_q = {}
for row in all_q_rows:
    seen_q[(row[0], row[1])] = row
deduped_q = list(seen_q.values())

seen_cf = {}
for row in all_cf_rows:
    seen_cf[(row[0], row[1])] = row
deduped_cf = list(seen_cf.values())

print(f"Quarterly rows: {len(deduped_q)}")
print(f"Cashflow rows: {len(deduped_cf)}")
print(f"Errors: {len(errors)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO quarterly_financials (symbol, quarter, sales, net_profit, eps, opm_pct)
    VALUES %s
    ON CONFLICT (symbol, quarter) DO UPDATE SET
        sales = EXCLUDED.sales,
        net_profit = EXCLUDED.net_profit,
        eps = EXCLUDED.eps,
        opm_pct = EXCLUDED.opm_pct
""", deduped_q)
print(f"Quarterly rows upserted: {cur.rowcount}")

execute_values(cur, """
    INSERT INTO cashflow (symbol, year, cfo, cfi, cff, free_cash_flow)
    VALUES %s
    ON CONFLICT (symbol, year) DO UPDATE SET
        cfo = EXCLUDED.cfo,
        cfi = EXCLUDED.cfi,
        cff = EXCLUDED.cff,
        free_cash_flow = EXCLUDED.free_cash_flow
""", deduped_cf)
print(f"Cashflow rows upserted: {cur.rowcount}")

conn.commit()
cur.close()
conn.close()
print("Done.")
