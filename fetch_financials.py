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
            return [c.text.strip().replace(',', '').replace('%', '').replace('\xa0', '').replace('+', '').strip() for c in cols[1:]]
    return []

def parse_num(val):
    try:
        return float(val)
    except:
        return None

def parse_year(label):
    # "Mar 2015" -> 2015, skip "TTM"
    try:
        parts = label.strip().split()
        return int(parts[-1])
    except:
        return None

def fetch_financials(symbol):
    url = f'https://www.screener.in/company/{symbol}/consolidated/'
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        url = f'https://www.screener.in/company/{symbol}/'
        r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.content, 'html.parser')

    pl = soup.find('section', {'id': 'profit-loss'})
    bs = soup.find('section', {'id': 'balance-sheet'})
    ratios = soup.find('section', {'id': 'ratios'})

    # Get years from th tags, skip empty first th and TTM
    years = []
    if pl:
        header_row = pl.find('tr')
        if header_row:
            for th in header_row.find_all('th')[1:]:
                label = th.text.strip()
                yr = parse_year(label)
                years.append(yr)  # None for TTM

    if not years:
        return []

    sales = get_row(pl, 'Sales')
    net_profit = get_row(pl, 'Net Profit')
    eps = get_row(pl, 'EPS')
    opm = get_row(pl, 'OPM')
    borrowings = get_row(bs, 'Borrowings')
    equity = get_row(bs, 'Equity Capital')
    reserves = get_row(bs, 'Reserves')
    roce = get_row(ratios, 'ROCE')

    rows = []
    for i, yr in enumerate(years):
        if not yr:  # skip TTM
            continue
        rows.append((
            symbol,
            yr,
            parse_num(sales[i]) if i < len(sales) else None,
            parse_num(net_profit[i]) if i < len(net_profit) else None,
            parse_num(eps[i]) if i < len(eps) else None,
            parse_num(borrowings[i]) if i < len(borrowings) else None,
            parse_num(equity[i]) if i < len(equity) else None,
            parse_num(reserves[i]) if i < len(reserves) else None,
            parse_num(roce[i]) if i < len(roce) else None,
            parse_num(opm[i]) if i < len(opm) else None,
        ))
    return rows

# Test on single stock first
print("Testing on RELIANCE...")
rows = fetch_financials('RELIANCE')
print(f"Rows found: {len(rows)}")
for r in rows[-3:]:
    print(r)

# Full run - all 500 stocks
nifty500 = pd.read_csv('nifty500.csv')
symbols = nifty500['Symbol'].tolist()

print(f"\nFetching financials for {len(symbols)} stocks...")

all_rows = []
errors = []

for i, symbol in enumerate(symbols):
    try:
        rows = fetch_financials(symbol)
        all_rows.extend(rows)
        if (i + 1) % 50 == 0:
            print(f"Progress: {i+1}/{len(symbols)} | Rows so far: {len(all_rows)}")
        time.sleep(1)
    except Exception as e:
        errors.append(symbol)
        continue

# Deduplicate
seen = {}
for row in all_rows:
    key = (row[0], row[1])
    seen[key] = row
deduped = list(seen.values())

print(f"Total rows after dedup: {len(deduped)}")
print(f"Errors: {len(errors)} stocks")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

execute_values(cur, """
    INSERT INTO financials (symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct)
    VALUES %s
    ON CONFLICT (symbol, year) DO UPDATE SET
        sales = EXCLUDED.sales,
        net_profit = EXCLUDED.net_profit,
        eps = EXCLUDED.eps,
        borrowings = EXCLUDED.borrowings,
        equity_capital = EXCLUDED.equity_capital,
        reserves = EXCLUDED.reserves,
        roce_pct = EXCLUDED.roce_pct,
        opm_pct = EXCLUDED.opm_pct
""", deduped)

conn.commit()
print(f"Rows upserted: {cur.rowcount}")
cur.close()
conn.close()
print("Done.")
