"""
screener_comparison.py — Screen 1 (fundamentals only, actual criteria)
ROE>20, OPM>10, D/E<0.9, Sales 1Y>1%, Profit 1Y>1%,
Sales 3Y>20%, Profit 3Y>25%, Promoter>25%, PEG<1
NO P/E<30. ROCE>20 only for non-financials.
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
cur = conn.cursor()

print("Loading data...")
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

# Financial sector symbols (exempt from ROCE screen)
cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector = 'Financial Services'")
financial_symbols = set(row[0] for row in cur.fetchall())

cur.execute("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))

cur.execute("SELECT DISTINCT symbol FROM model3_training_data WHERE in_forward_test = TRUE")
universe = [row[0] for row in cur.fetchall()]
cur.close()
print(f"  Universe: {len(universe)} symbols")

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices: return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end: return p
    return None

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

def apply_screen1(symbol, rebal_date):
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)

    if not f0['roe'] or f0['roe'] <= 20: return False
    if not f0['opm'] or f0['opm'] <= 10: return False
    if f0['de'] is None or f0['de'] >= 0.9: return False

    # ROCE>20 only for non-financials
    if symbol not in financial_symbols:
        if not f0['roce'] or f0['roce'] <= 20: return False

    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False

    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 20: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 25: return False

    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False

    # PEG check (no P/E<30 filter)
    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if price and eps and eps > 0 and f1 and f1['eps'] and f1['eps'] > 0:
        pe = price / eps
        eps_growth = (eps - f1['eps']) / abs(f1['eps']) * 100
        if eps_growth > 0 and pe / eps_growth >= 1: return False

    return True

# Model setup
with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's7_tam_expansion',
    's8_peg_ratio', 's9_dii_accumulation', 's10_de_improvement',
    's11_roce', 's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE in_forward_test = TRUE
    ORDER BY rebalance_date, symbol
""", conn)

gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

forward_dates = [
    date(2024, 6, 1), date(2024, 12, 1),
    date(2025, 6, 1), date(2025, 12, 1),
]

print("\n" + "═"*65)
print("  SCREEN 1 vs MODEL 3 — FORWARD TEST COMPARISON")
print("  Screen 1: ROE>20, OPM>10, D/E<0.9, Sales/Profit growth,")
print("  Promoter>25%, PEG<1, ROCE>20 (non-financials only), no P/E cap")
print("═"*65)

s1_returns, m3_returns = [], []

for rebal_date in forward_dates:
    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    # Screen 1
    s1_picks = [s for s in universe if apply_screen1(s, rebal_date)]
    s1_rets = []
    s1_detail = []
    for sym in s1_picks:
        p0 = get_price_on(sym, rebal_date)
        p1 = get_price_on(sym, next_date)
        if p0 and p1 and p0 > 0:
            ret = (p1-p0)/p0
            s1_rets.append(ret)
            s1_detail.append((sym, ret*100))
    s1_port = float(np.mean(s1_rets)) if s1_rets else None

    # Model 3
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['score'] = model.predict(period_df[FEATURES])
    excluded, _ = get_exclusions(gov_conn, rebal_date)
    period_df = period_df[~period_df['symbol'].isin(excluded)]
    top10 = period_df.nlargest(10, 'score')
    m3_rets = []
    for _, row in top10.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)
        if p0 and p1 and p0 > 0:
            m3_rets.append((p1-p0)/p0)
    m3_port = float(np.mean(m3_rets)) if m3_rets else None

    if s1_port is not None: s1_returns.append(s1_port)
    if m3_port is not None: m3_returns.append(m3_port)

    s1_str = f"{s1_port*100:.1f}%" if s1_port else "N/A"
    m3_str = f"{m3_port*100:.1f}%" if m3_port else "N/A"

    print(f"\n{'─'*65}")
    print(f"  {rebal_date}")
    print(f"  Screen 1: {len(s1_picks)} picks | return={s1_str}")
    print(f"  Model 3:  10 picks | return={m3_str}")

    s1_detail.sort(key=lambda x: x[1], reverse=True)
    if s1_detail:
        print(f"  Screen 1 picks:")
        for sym, ret in s1_detail:
            print(f"    {sym:<15} {ret:>8.1f}%")

    overlap = set(s1_picks) & set(top10['symbol'].tolist())
    print(f"  Overlap: {sorted(overlap) or 'none'}")

gov_conn.close()

print(f"\n{'═'*65}")
print(f"  SUMMARY")
print(f"{'═'*65}")
if s1_returns:
    s1_total = float((pd.Series(s1_returns)+1).prod())
    s1_cagr  = s1_total**(1/2)-1
    print(f"  Screen 1: avg={np.mean(s1_returns)*100:.1f}%  CAGR={s1_cagr*100:.1f}%  periods={len(s1_returns)}")
if m3_returns:
    m3_total = float((pd.Series(m3_returns)+1).prod())
    m3_cagr  = m3_total**(1/2)-1
    print(f"  Model 3:  avg={np.mean(m3_returns)*100:.1f}%  CAGR={m3_cagr*100:.1f}%  periods={len(m3_returns)}")
print(f"{'═'*65}")
conn.close()
