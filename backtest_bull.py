"""
Tests composite scorer on 2020-2023 bull market period.
"""
import os, psycopg2, pandas as pd, numpy as np
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions

load_dotenv()

def get_conn():
    return psycopg2.connect(os.environ['DATABASE_URL'])

conn = get_conn()
cur = conn.cursor()

cur.execute("SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials")
financials = {}
for symbol, year, sales, np_, eps, borr, eq, res, roce, opm in cur.fetchall():
    equity = float(eq or 0) + float(res or 0)
    roe = float(np_)/equity*100 if (np_ and equity > 0) else None
    de  = float(borr)/equity if (borr is not None and equity > 0) else None
    financials.setdefault(symbol, []).append({
        'year': year, 'sales': float(sales) if sales else None,
        'net_profit': float(np_) if np_ else None,
        'eps': float(eps) if eps else None,
        'roe': roe, 'de': de,
        'roce': float(roce) if roce else None,
        'opm': float(opm) if opm else None,
    })

cur.execute("SELECT symbol, year, free_cash_flow FROM cashflow WHERE free_cash_flow IS NOT NULL")
cashflow = {}
for symbol, year, fcf in cur.fetchall():
    cashflow.setdefault(symbol, []).append({'year': year, 'fcf': float(fcf)})

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector='Financial Services'")
fin_syms = set(r[0] for r in cur.fetchall())

cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name='Nifty 500'")
membership = cur.fetchall()
cur.close()
conn.close()

print("Loading prices 2019-2024...")
prices = {}
for year in range(2019, 2025):
    c = get_conn()
    cr = c.cursor()
    cr.execute("""SELECT symbol, date, close_price FROM prices
        WHERE close_price IS NOT NULL AND date >= %s AND date < %s
        ORDER BY symbol, date""",
        (date(year,1,1), date(year+1,1,1)))
    for symbol, d, price in cr.fetchall():
        prices.setdefault(symbol, []).append((d, float(price)))
    cr.close(); c.close()
    print(f"  {year}: loaded")

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices: return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end: return p
    return None

def get_universe(rebal_date):
    return list(set(s for s, vf, vt in membership
        if vf <= rebal_date and (vt is None or vt >= rebal_date)))

def score_stock(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)
    if len(rows) < 2: return None
    f0, f1 = rows[0], rows[1]
    f3 = rows[3] if len(rows) > 3 else None

    if not f0['roe'] or f0['roe'] < 15: return None
    if not f0['opm'] or f0['opm'] < 8: return None
    if symbol not in fin_syms:
        if f0['de'] is None or f0['de'] > 1.0: return None
        if not f0['roce'] or f0['roce'] < 15: return None
    if not f0['net_profit'] or f0['net_profit'] <= 0: return None
    if not f1['net_profit'] or f1['net_profit'] <= 0: return None
    if (f0['net_profit']-f1['net_profit'])/abs(f1['net_profit']) < -0.10: return None

    scores = {}
    if f0['eps'] and f3 and f3['eps'] and f0['eps'] > 0 and f3['eps'] > 0:
        eps_cagr = (f0['eps']/f3['eps'])**(1/3) - 1
        scores['eps_cagr'] = min(100, max(0, 50 + eps_cagr * 167))
    scores['roe'] = min(100, max(0, f0['roe'] * 2.5))
    if f0['sales'] and f3 and f3['sales'] and f0['sales'] > 0 and f3['sales'] > 0:
        rev_cagr = (f0['sales']/f3['sales'])**(1/3) - 1
        scores['rev_cagr'] = min(100, max(0, 50 + rev_cagr * 167))
    if f0['roce']:
        scores['roce'] = min(100, max(0, f0['roce'] * 2.5))
    cf_rows = sorted([r for r in cashflow.get(symbol, []) if r['year'] <= cutoff],
                     key=lambda x: x['year'], reverse=True)[:3]
    if cf_rows:
        scores['fcf'] = sum(1 for r in cf_rows if r['fcf'] > 0)/len(cf_rows)*100
    scores['opm'] = min(100, max(0, f0['opm'] * 4))
    if symbol not in fin_syms and f0['de'] is not None:
        scores['de'] = min(100, max(0, 100 - f0['de'] * 60))
    if len(scores) < 3: return None

    weights = {'eps_cagr':0.25,'roe':0.20,'rev_cagr':0.15,'roce':0.15,'fcf':0.10,'opm':0.10,'de':0.05}
    total_w = sum(weights.get(k,0) for k in scores)
    return sum(scores[k]*weights.get(k,0) for k in scores) / total_w

# All periods 2020-2023
periods = [
    (date(2020,6,1),  date(2020,12,1)),
    (date(2020,12,1), date(2021,6,1)),
    (date(2021,6,1),  date(2021,12,1)),
    (date(2021,12,1), date(2022,6,1)),
    (date(2022,6,1),  date(2022,12,1)),
    (date(2022,12,1), date(2023,6,1)),
    (date(2023,6,1),  date(2023,12,1)),
    (date(2023,12,1), date(2024,6,1)),
]

print(f"\n{'═'*75}")
print(f"  COMPOSITE SCORER — 2020-2023 BULL PERIOD BACKTEST")
print(f"{'═'*75}")
print(f"  {'Period':<12} {'Model':>8} {'Benchmark':>11} {'Alpha':>8} {'N':>4} Top picks")
print(f"  {'─'*75}")

model_rets, bench_rets = [], []
gov_conn = get_conn()

for rebal_date, next_date in periods:
    universe = get_universe(rebal_date)
    excluded, _ = get_exclusions(gov_conn, rebal_date)

    scored = []
    for sym in universe:
        if sym in excluded: continue
        s = score_stock(sym, rebal_date)
        if s: scored.append((sym, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    top10 = scored[:10]

    rets = []
    for sym, _ in top10:
        p0 = get_price_on(sym, rebal_date)
        p1 = get_price_on(sym, next_date)
        if p0 and p1 and p0 > 0:
            rets.append((p1-p0)/p0)

    model_ret = float(np.mean(rets)) if rets else None
    p0b = get_price_on('NIFTY500_IDX', rebal_date)
    p1b = get_price_on('NIFTY500_IDX', next_date)
    bench_ret = (p1b-p0b)/p0b if p0b and p1b else None

    if model_ret is not None and bench_ret is not None:
        model_rets.append(model_ret)
        bench_rets.append(bench_ret)
        alpha = model_ret - bench_ret
        picks_str = ', '.join([s for s,_ in top10[:3]])
        print(f"  {str(rebal_date):<12} {model_ret*100:>7.1f}% {bench_ret*100:>10.1f}% {alpha*100:>7.1f}% {len(rets):>4} {picks_str}")

gov_conn.close()

if len(model_rets) >= 2:
    model_total = float(np.prod([1+r for r in model_rets]))
    bench_total = float(np.prod([1+r for r in bench_rets]))
    n_yrs = len(model_rets)/2
    model_cagr = model_total**(1/n_yrs)-1
    bench_cagr = bench_total**(1/n_yrs)-1
    m, b = np.array(model_rets), np.array(bench_rets)
    beta = np.cov(m,b)[0][1]/np.var(b) if np.var(b) > 0 else None
    rf = 0.065
    jensen = model_cagr-(rf+beta*(bench_cagr-rf)) if beta else None

    print(f"\n  {'═'*75}")
    print(f"  Model CAGR:      {model_cagr*100:.1f}%")
    print(f"  Benchmark CAGR:  {bench_cagr*100:.1f}%")
    print(f"  Raw Alpha:       {(model_cagr-bench_cagr)*100:.1f}% per year")
    if beta: print(f"  Beta:            {beta:.2f}")
    if jensen: print(f"  Jensen Alpha:    {jensen*100:.1f}% per year")
    print(f"  {'═'*75}")
