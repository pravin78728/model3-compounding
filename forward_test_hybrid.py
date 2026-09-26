"""
forward_test_hybrid.py
Hybrid: Screen 1 quality pre-filter + Model 3 RF ranking.
Screen 1 filters universe to quality stocks only.
Model 3 ranks within that filtered set.
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions

load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE in_forward_test = TRUE
    ORDER BY rebalance_date, symbol
""", conn)
prices_df = pd.read_sql("""
    SELECT symbol, date, close_price FROM prices
    WHERE close_price IS NOT NULL ORDER BY symbol, date
""", conn)

cur = conn.cursor()
cur.execute("""
    SELECT symbol, year, sales, net_profit, eps,
           borrowings, equity_capital, reserves, roce_pct, opm_pct
    FROM financials
""")
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

cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector = 'Financial Services'")
financial_symbols = set(row[0] for row in cur.fetchall())
cur.close()
conn.close()

with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's7_tam_expansion',
    's8_peg_ratio', 's9_dii_accumulation', 's10_de_improvement',
    's11_roce', 's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

prices_df['date'] = pd.to_datetime(prices_df['date'])
price_pivot = prices_df.pivot(
    index='date', columns='symbol', values='close_price'
).sort_index()

def get_price_on(symbol, target_date, window=15):
    if symbol not in price_pivot.columns: return None
    td = pd.Timestamp(target_date)
    subset = price_pivot.loc[td:td+pd.Timedelta(days=window), symbol].dropna()
    return float(subset.iloc[0]) if len(subset) > 0 else None

def get_fin_year(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)
    return rows[0] if rows else None

def get_fin(symbol, year):
    rows = [r for r in financials.get(symbol, []) if r['year'] == year]
    return rows[0] if rows else None

def get_promoter_pct(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, []) if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)
    return rows[0]['pct'] if rows else None

def passes_screen1(symbol, rebal_date):
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)

    if not f0['roe'] or f0['roe'] <= 20: return False
    if not f0['opm'] or f0['opm'] <= 10: return False
    if symbol not in financial_symbols:
        if f0['de'] is None or f0['de'] >= 0.9: return False
    if symbol not in financial_symbols:
        if not f0['roce'] or f0['roce'] <= 20: return False

    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False

    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False

    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False

    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if price and eps and eps > 0 and f1 and f1['eps'] and f1['eps'] > 0:
        pe = price/eps
        eps_growth = (eps-f1['eps'])/abs(f1['eps'])*100
        if eps_growth > 0 and pe/eps_growth >= 1: return False

    return True

rebal_dates = sorted(df['rebalance_date'].unique())
gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

print("═"*65)
print("  HYBRID: SCREEN 1 QUALITY FILTER + MODEL 3 RANKING")
print("═"*65)

all_results = []

for rebal_date in rebal_dates:
    is_partial = rebal_date >= date(2026, 6, 1)
    period_df = df[df['rebalance_date'] == rebal_date].copy()

    # Step 1: Governance filter
    excluded, _ = get_exclusions(gov_conn, rebal_date)
    before = len(period_df)
    period_df = period_df[~period_df['symbol'].isin(excluded)]

    # Step 2: Screen 1 quality pre-filter
    screen1_mask = period_df['symbol'].apply(lambda s: passes_screen1(s, rebal_date))
    before_s1 = len(period_df)
    period_df = period_df[screen1_mask].copy()
    after_s1 = len(period_df)

    # Step 3: Model 3 ranks within quality survivors
    if len(period_df) > 0:
        period_df['score'] = model.predict(period_df[FEATURES])
        top10 = period_df.nlargest(10, 'score')
    else:
        top10 = period_df

    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    stock_returns = []
    selected = []
    for _, row in top10.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)
        if is_partial and p1 is None:
            p1 = get_price_on(row['symbol'], date(2026, 8, 28), window=5)
        if p0 and p1 and p0 > 0:
            ret = (p1-p0)/p0
            stock_returns.append(ret)
            selected.append((row['symbol'], round(float(row['score']),3), round(ret*100,1)))

    port_ret = float(np.mean(stock_returns)) if stock_returns else None
    all_results.append((rebal_date, port_ret))

    label = "(PARTIAL)" if is_partial else "(FULL)"
    ret_str = f"{port_ret*100:.1f}%" if port_ret else "N/A"
    print(f"\n{'─'*65}")
    print(f"  {rebal_date} {label}")
    print(f"  Filters: gov={before}→{before_s1} | screen1={before_s1}→{after_s1} | picks={len(selected)}")
    print(f"  Return: {ret_str}")
    print(f"  {'Symbol':<14} {'Score':>7} {'Return':>10}")
    for sym, score, ret in selected:
        print(f"  {sym:<14} {score:>7.3f} {ret:>9.1f}%")

gov_conn.close()

complete = [(rd, ret) for rd, ret in all_results
            if ret is not None and rd < date(2026, 6, 1)]

if complete:
    series = pd.Series([r for _, r in complete])
    total  = float((1+series).prod())
    n_yrs  = len(complete)/2
    cagr   = total**(1/n_yrs)-1

    print(f"\n{'═'*65}")
    print(f"  HYBRID FORWARD TEST SUMMARY")
    print(f"{'═'*65}")
    for rd, ret in complete:
        print(f"  {rd}: {ret*100:.1f}%")
    print(f"\n  Total return: {(total-1)*100:.1f}%")
    print(f"  Ann. CAGR:    {cagr*100:.1f}%  {'✓' if cagr>0.28 else '✗'} gate >28%")
    print(f"{'═'*65}")
