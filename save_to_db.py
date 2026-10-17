"""
save_to_db.py
Re-runs fetch_financials_full.py fetch but saves in batches of 100 symbols
to avoid Supabase connection timeout on large inserts.
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

def get_row(section, label):
    if not section:
        return []
    for row in section.find_all('tr'):
        cols = row.find_all('td')
        if cols and label.lower() in cols[0].text.lower():
            return [c.text.strip().replace(',','').replace('%','')
                    .replace('\xa0','').replace('+','').strip() for c in cols[1:]]
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

def fetch_symbol(symbol):
    fin_rows, q_rows, cf_rows = [], [], []
    for url in [
        f'https://www.screener.in/company/{symbol}/consolidated/',
        f'https://www.screener.in/company/{symbol}/'
    ]:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                break
        except:
            continue
    else:
        return fin_rows, q_rows, cf_rows

    soup = BeautifulSoup(r.content, 'html.parser')
    pl     = soup.find('section', {'id': 'profit-loss'})
    bs_sec = soup.find('section', {'id': 'balance-sheet'})
    ratios = soup.find('section', {'id': 'ratios'})
    qr     = soup.find('section', {'id': 'quarters'})
    cf     = soup.find('section', {'id': 'cash-flow'})

    years = []
    if pl:
        header_row = pl.find('tr')
        if header_row:
            for th in header_row.find_all('th')[1:]:
                yr = parse_year(th.text.strip())
                years.append(yr)

    if years:
        sales      = get_row(pl, 'Sales')
        net_profit = get_row(pl, 'Net Profit')
        eps        = get_row(pl, 'EPS')
        opm        = get_row(pl, 'OPM')
        borrowings = get_row(bs_sec, 'Borrowings')
        equity     = get_row(bs_sec, 'Equity Capital')
        reserves   = get_row(bs_sec, 'Reserves')
        roce       = get_row(ratios, 'ROCE')

        for i, yr in enumerate(years):
            if not yr:
                continue
            fin_rows.append((
                symbol, yr,
                parse_num(sales[i])      if i < len(sales)      else None,
                parse_num(net_profit[i]) if i < len(net_profit) else None,
                parse_num(eps[i])        if i < len(eps)        else None,
                parse_num(borrowings[i]) if i < len(borrowings) else None,
                parse_num(equity[i])     if i < len(equity)     else None,
                parse_num(reserves[i])   if i < len(reserves)   else None,
                parse_num(roce[i])       if i < len(roce)       else None,
                parse_num(opm[i])        if i < len(opm)        else None,
            ))

    if qr:
        quarters = get_headers(qr)
        sales_q  = get_row(qr, 'Sales')
        profit_q = get_row(qr, 'Net Profit')
        eps_q    = get_row(qr, 'EPS')
        opm_q    = get_row(qr, 'OPM')
        for i, q in enumerate(quarters):
            if not q or q == 'TTM':
                continue
            q_rows.append((
                symbol, q,
                parse_num(sales_q[i])  if i < len(sales_q)  else None,
                parse_num(profit_q[i]) if i < len(profit_q) else None,
                parse_num(eps_q[i])    if i < len(eps_q)    else None,
                parse_num(opm_q[i])    if i < len(opm_q)    else None,
            ))

    if cf:
        cf_years = get_headers(cf)
        cfo = get_row(cf, 'Cash from Opera')
        cfi = get_row(cf, 'Cash from Inves')
        cff = get_row(cf, 'Cash from Finan')
        fcf = get_row(cf, 'Free Cash Flow')
        for i, y in enumerate(cf_years):
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

    return fin_rows, q_rows, cf_rows

def dedup(rows, key_cols):
    seen = {}
    for row in rows:
        key = tuple(row[i] for i in key_cols)
        seen[key] = row
    return list(seen.values())

def save_batch(cur, fin, q, cf):
    if fin:
        execute_values(cur, """
            INSERT INTO financials
                (symbol, year, sales, net_profit, eps, borrowings,
                 equity_capital, reserves, roce_pct, opm_pct)
            VALUES %s
            ON CONFLICT (symbol, year) DO UPDATE SET
                sales=EXCLUDED.sales, net_profit=EXCLUDED.net_profit,
                eps=EXCLUDED.eps, borrowings=EXCLUDED.borrowings,
                equity_capital=EXCLUDED.equity_capital,
                reserves=EXCLUDED.reserves, roce_pct=EXCLUDED.roce_pct,
                opm_pct=EXCLUDED.opm_pct
        """, fin)
    if q:
        execute_values(cur, """
            INSERT INTO quarterly_financials
                (symbol, quarter, sales, net_profit, eps, opm_pct)
            VALUES %s
            ON CONFLICT (symbol, quarter) DO UPDATE SET
                sales=EXCLUDED.sales, net_profit=EXCLUDED.net_profit,
                eps=EXCLUDED.eps, opm_pct=EXCLUDED.opm_pct
        """, q)
    if cf:
        execute_values(cur, """
            INSERT INTO cashflow
                (symbol, year, cfo, cfi, cff, free_cash_flow)
            VALUES %s
            ON CONFLICT (symbol, year) DO UPDATE SET
                cfo=EXCLUDED.cfo, cfi=EXCLUDED.cfi,
                cff=EXCLUDED.cff, free_cash_flow=EXCLUDED.free_cash_flow
        """, cf)

# ── Main loop — fetch and save every 50 symbols ───────────────────────────────
BATCH_SIZE = 50
errors = []
total_fin = total_q = total_cf = 0

for batch_start in range(0, len(symbols), BATCH_SIZE):
    batch_symbols = symbols[batch_start:batch_start + BATCH_SIZE]
    batch_fin, batch_q, batch_cf = [], [], []

    for symbol in batch_symbols:
        try:
            fin, q, cf = fetch_symbol(symbol)
            batch_fin.extend(fin)
            batch_q.extend(q)
            batch_cf.extend(cf)
            time.sleep(1.2)
        except Exception as e:
            errors.append((symbol, str(e)))

    # Dedup within batch
    batch_fin = dedup(batch_fin, [0, 1])
    batch_q   = dedup(batch_q,   [0, 1])
    batch_cf  = dedup(batch_cf,  [0, 1])

    # Fresh connection per batch to avoid timeout
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur  = conn.cursor()
    try:
        save_batch(cur, batch_fin, batch_q, batch_cf)
        conn.commit()
        total_fin += len(batch_fin)
        total_q   += len(batch_q)
        total_cf  += len(batch_cf)
        print(f"  ✓ symbols {batch_start+1}–{batch_start+len(batch_symbols)} saved | "
              f"fin={total_fin} q={total_q} cf={total_cf} errors={len(errors)}")
    except Exception as e:
        conn.rollback()
        print(f"  ✗ DB error on batch {batch_start}: {e}")
    finally:
        cur.close()
        conn.close()

print(f"\n✓ All done. fin={total_fin} q={total_q} cf={total_cf} errors={len(errors)}")
if errors:
    for sym, err in errors[:10]:
        print(f"  {sym}: {err}")
