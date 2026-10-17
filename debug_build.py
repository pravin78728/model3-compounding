import os, psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta
load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

cur.execute("""SELECT symbol, period, fii_pct, dii_pct 
    FROM institutional_holdings 
    WHERE fii_pct IS NOT NULL 
    ORDER BY symbol, period LIMIT 1000""")
institutional = {}
for symbol, period, fii, dii in cur.fetchall():
    institutional.setdefault(symbol, []).append({
        'period': period, 
        'fii': float(fii) if fii else None, 
        'dii': float(dii) if dii else None
    })
print(f'Loaded {len(institutional)} symbols')

cur.execute("""SELECT symbol, date, close_price FROM prices 
    WHERE close_price IS NOT NULL AND date >= '2022-01-01' 
    LIMIT 5000""")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))
print(f'Loaded prices for {len(prices)} symbols')
cur.close()
conn.close()

def s15_rs_12m(symbol, rebal_date):
    if symbol not in prices: return None
    end = rebal_date + timedelta(days=10)
    start_d = rebal_date - timedelta(days=365)
    end_p = [(d,p) for d,p in prices[symbol] if rebal_date <= d <= end]
    start_p = [(d,p) for d,p in prices[symbol] if start_d <= d <= start_d+timedelta(days=15)]
    if not end_p or not start_p: return None
    rs = (end_p[0][1]-start_p[0][1])/start_p[0][1]*100
    return round(min(100, max(0, 50+rs*0.5)), 2)

def s_fii_trend(symbol, rebal_date):
    rows = sorted([r for r in institutional.get(symbol, [])
                   if r['period'] <= rebal_date and r['fii'] is not None],
                  key=lambda x: x['period'], reverse=True)[:4]
    if len(rows) < 2: return None
    vals = [r['fii'] for r in rows]
    return round(min(100, max(0, 50 + (vals[0]-vals[-1]) * 10)), 2)

# Test
for sym in ['INFY', 'RELIANCE', 'TRENT']:
    rd = date(2022, 6, 1)
    try:
        s15 = s15_rs_12m(sym, rd)
        fii = s_fii_trend(sym, rd)
        print(f'{sym}: s15={s15} fii={fii}')
    except Exception as e:
        print(f'{sym} ERROR: {e}')
        import traceback
        traceback.print_exc()
