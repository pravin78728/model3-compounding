"""
screener2_comparison.py — Actual Screen 2 criteria
Fundamentals: ROE>20, D/E<0.9, Sales 3Y>25%, Profit 3Y>20%,
Sales 1Y>1%, Profit 1Y>1%, Promoter>25%, PEG<1, no P/E cap
Momentum: >=50% down from 52wk high AND >=10% up from 52wk low
MACD signal line > 0, price > 10
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

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector = 'Financial Services'")
financial_symbols = set(row[0] for row in cur.fetchall())

cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})

print("  Loading prices...")
cur.execute("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))
print(f"  ✓ prices: {len(prices)} symbols")

cur.execute("SELECT DISTINCT symbol FROM model3_training_data WHERE in_forward_test = TRUE")
universe = [row[0] for row in cur.fetchall()]
print(f"  ✓ universe: {len(universe)} symbols")
cur.close()

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices: return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end: return p
    return None

def get_price_series(symbol, start_date, end_date):
    if symbol not in prices: return pd.Series(dtype=float)
    data = [(d, p) for d, p in prices[symbol] if start_date <= d <= end_date]
    if not data: return pd.Series(dtype=float)
    dates, vals = zip(*data)
    return pd.Series(vals, index=pd.to_datetime(dates)).sort_index()

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
    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if price and eps and eps > 0 and f1 and f1['eps'] and f1['eps'] > 0:
        pe = price / eps
        eps_growth = (eps-f1['eps'])/abs(f1['eps'])*100
        if eps_growth > 0 and pe/eps_growth >= 1: return False
    return True

def apply_screen2(symbol, rebal_date):
    """Actual Screen 2: quality fundamentals + rebound momentum"""
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)

    # Fundamentals
    if not f0['roe'] or f0['roe'] <= 20: return False
    if f0['de'] is None or f0['de'] >= 0.9: return False
    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales'] or 0)/f3['sales'])**(1/3)-1 <= 0.25: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit'] or 0)/f3['net_profit'])**(1/3)-1 <= 0.20: return False
    if not f1 or not f1['sales'] or f1['sales'] <= 0: return False
    if (f0['sales'] or 0)/f1['sales']-1 <= 0.01: return False
    if not f1['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit'] or 0)/f1['net_profit']-1 <= 0.01: return False
    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False

    # PEG check
    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if not price or price <= 10: return False
    if eps and eps > 0 and f1 and f1['eps'] and f1['eps'] > 0:
        pe = price/eps
        eps_growth = (eps-f1['eps'])/abs(f1['eps'])*100
        if eps_growth > 0 and pe/eps_growth >= 1: return False

    # Price momentum — rebound pattern
    start_52wk = rebal_date - timedelta(days=365)
    series = get_price_series(symbol, start_52wk, rebal_date)
    if len(series) < 50: return False
    high_52wk = series.max()
    low_52wk  = series.min()
    current   = float(series.iloc[-1])

    # At least 50% down from 52wk high (beaten down stock)
    drawdown = (high_52wk - current) / high_52wk * 100
    if drawdown < 50: return False

    # At least 10% up from 52wk low (on the rebound)
    recovery = (current / low_52wk - 1) * 100
    if recovery < 10: return False

    # MACD signal line > 0 (upward momentum confirmed)
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_signal = (ema12-ema26).ewm(span=9, adjust=False).mean().iloc[-1]
    if macd_signal <= 0: return False

    return True

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

print("\n" + "═"*70)
print("  THREE-WAY: Screen 1 vs Screen 2 vs Model 3")
print("  Screen 2: quality fundamentals + >=50% below 52wk high + >=10% rebound")
print("═"*70)

s1_returns, s2_returns, m3_returns = [], [], []

for rebal_date in forward_dates:
    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    s1_picks = [s for s in universe if apply_screen1(s, rebal_date)]
    s2_picks = [s for s in universe if apply_screen2(s, rebal_date)]

    def calc_port(picks):
        rets = []
        detail = []
        for sym in picks:
            p0 = get_price_on(sym, rebal_date)
            p1 = get_price_on(sym, next_date)
            if p0 and p1 and p0 > 0:
                ret = (p1-p0)/p0
                rets.append(ret)
                detail.append((sym, ret*100))
        return (float(np.mean(rets)) if rets else None,
                sorted(detail, key=lambda x: x[1], reverse=True))

    s1_port, s1_detail = calc_port(s1_picks)
    s2_port, s2_detail = calc_port(s2_picks)

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
    if s2_port is not None: s2_returns.append(s2_port)
    if m3_port is not None: m3_returns.append(m3_port)

    print(f"\n{'─'*70}")
    print(f"  {rebal_date}")
    print(f"  Screen 1: {len(s1_picks):3d} picks | {f'{s1_port*100:.1f}%' if s1_port else 'N/A'}")
    print(f"  Screen 2: {len(s2_picks):3d} picks | {f'{s2_port*100:.1f}%' if s2_port else 'N/A'}")
    print(f"  Model 3:   10 picks | {f'{m3_port*100:.1f}%' if m3_port else 'N/A'}")

    if s2_detail:
        print(f"  Screen 2 picks:")
        for sym, ret in s2_detail:
            print(f"    {sym:<15} {ret:>8.1f}%")

gov_conn.close()

print(f"\n{'═'*70}")
print(f"  SUMMARY")
print(f"{'═'*70}")
for label, rets in [("Screen 1", s1_returns), ("Screen 2", s2_returns), ("Model 3 ", m3_returns)]:
    if rets:
        total = float((pd.Series(rets)+1).prod())
        cagr  = total**(1/2)-1
        print(f"  {label}: avg={np.mean(rets)*100:.1f}%  CAGR={cagr*100:.1f}%  periods={len(rets)}")
    else:
        print(f"  {label}: no data")
print(f"{'═'*70}")
conn.close()
