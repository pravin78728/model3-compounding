import os, psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta
load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

cur.execute("SELECT symbol, period, fii_pct, dii_pct FROM institutional_holdings WHERE fii_pct IS NOT NULL OR dii_pct IS NOT NULL ORDER BY symbol, period")
institutional = {}
for symbol, period, fii, dii in cur.fetchall():
    institutional.setdefault(symbol, []).append({'period': period, 'fii': float(fii) if fii else None, 'dii': float(dii) if dii else None})

cur.execute("SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials")
financials = {}
for row in cur.fetchall():
    symbol, year = row[0], row[1]
    equity = float(row[6] or 0) + float(row[7] or 0)
    financials.setdefault(symbol, []).append({'year': year, 'sales': float(row[2]) if row[2] else None})

cur.execute("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))

cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name = 'Nifty 500'")
membership_rows = cur.fetchall()
cur.close()
conn.close()

def get_universe(rebal_date):
    seen = set()
    result = []
    for symbol, valid_from, valid_to in membership_rows:
        if symbol not in seen and valid_from <= rebal_date and (valid_to is None or valid_to >= rebal_date):
            seen.add(symbol)
            result.append(symbol)
    return result

def s_fii_trend(symbol, rebal_date):
    rows = sorted([r for r in institutional.get(symbol, [])
                   if r['period'] <= rebal_date and r['fii'] is not None],
                  key=lambda x: x['period'], reverse=True)[:4]
    if len(rows) < 2: return None
    vals = [r['fii'] for r in rows]
    return round(min(100, max(0, 50 + (vals[0]-vals[-1]) * 10)), 2)

def s_dii_trend(symbol, rebal_date):
    rows = sorted([r for r in institutional.get(symbol, [])
                   if r['period'] <= rebal_date and r['dii'] is not None],
                  key=lambda x: x['period'], reverse=True)[:4]
    if len(rows) < 2: return None
    vals = [r['dii'] for r in rows]
    return round(min(100, max(0, 50 + (vals[0]-vals[-1]) * 10)), 2)

def s15_rs_12m(symbol, rebal_date):
    if symbol not in prices: return None
    end = rebal_date + timedelta(days=15)
    start_d = rebal_date - timedelta(days=365)
    end_p = [(d,p) for d,p in prices[symbol] if rebal_date <= d <= end]
    start_p = [(d,p) for d,p in prices[symbol] if start_d <= d <= start_d+timedelta(days=15)]
    if not end_p or not start_p: return None
    rs = (end_p[0][1]-start_p[0][1])/start_p[0][1]*100
    return round(min(100, max(0, 50+rs*0.5)), 2)

# Test at 2022-06-01
rd = date(2022, 6, 1)
universe = get_universe(rd)
print(f'Universe at {rd}: {len(universe)} symbols')

errors = {}
success = 0
for symbol in universe[:20]:
    try:
        sig = [
            s15_rs_12m(symbol, rd),
            s_fii_trend(symbol, rd),
            s_dii_trend(symbol, rd),
        ]
        success += 1
    except Exception as e:
        errors[type(e).__name__] = errors.get(type(e).__name__, 0) + 1
        print(f'{symbol} ERROR: {e}')
        import traceback
        traceback.print_exc()
        break

print(f'Success: {success}, Errors: {errors}')
