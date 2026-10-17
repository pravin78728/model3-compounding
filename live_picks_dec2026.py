"""
live_picks_dec2026.py
Generates Model 3 hybrid picks for Dec 2026 rebalance.
These are the actual paper trading recommendations.
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions
from regime_classifier import classify_regime

load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE rebalance_date = '2026-12-01'
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

rebal_date = date(2026, 12, 1)

# Regime
regime, signals = classify_regime(rebal_date, conn)

# Score all stocks
df['rf_score'] = model.predict(df[FEATURES])

# Governance filter
gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])
excluded, _ = get_exclusions(gov_conn, rebal_date)
gov_conn.close()
before = len(df)
df = df[~df['symbol'].isin(excluded)]

# Screen 1 quality filter
screen1_mask = df['symbol'].apply(lambda s: passes_screen1(s, rebal_date))
before_s1 = len(df)
df_filtered = df[screen1_mask].copy()

# Rank by RF score
top_picks = df_filtered.nlargest(15, 'rf_score')

# Get current prices
top_picks = top_picks.copy()
top_picks['current_price'] = top_picks['symbol'].apply(
    lambda s: get_price_on(s, rebal_date, window=10))

conn.close()

print("═"*65)
print("  MODEL 3 — DEC 2026 REBALANCE — LIVE PICKS")
print(f"  Market Regime: {regime}")
print(f"  Generated: {date.today()}")
print("═"*65)
print(f"\n  Universe: {before} stocks")
print(f"  After governance filter: {before_s1}")
print(f"  After Screen 1 quality filter: {len(df_filtered)}")
print(f"\n  Top picks ranked by Model 3 score:")
print(f"\n  {'Rank':<5} {'Symbol':<14} {'Score':>7} {'Price':>8} {'S15_RS':>7} {'S11_ROCE':>9} {'S1_ROE':>8}")
print("  " + "─"*60)

for rank, (_, row) in enumerate(top_picks.iterrows(), 1):
    price_str = f"₹{row['current_price']:.0f}" if row['current_price'] else "N/A"
    s15 = f"{row['s15_rs_12m']:.1f}" if pd.notna(row['s15_rs_12m']) else "N/A"
    s11 = f"{row['s11_roce']:.1f}" if pd.notna(row['s11_roce']) else "N/A"
    s1  = f"{row['s1_roe_trend']:.1f}" if pd.notna(row['s1_roe_trend']) else "N/A"
    print(f"  {rank:<5} {row['symbol']:<14} {row['rf_score']:>7.3f} {price_str:>8} {s15:>7} {s11:>9} {s1:>8}")

print(f"\n  Hold period: Dec 2026 → Jun 2027 (semi-annual)")
print(f"  Next rebalance: Jun 2027")
print("═"*65)
