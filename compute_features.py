import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv
from datetime import date

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))

print("Loading data...")

prices = pd.read_sql("""
    SELECT symbol, date, close_price
    FROM prices
    WHERE close_price IS NOT NULL
    ORDER BY symbol, date
""", conn)

financials = pd.read_sql("""
    SELECT symbol, year, sales, net_profit, eps, borrowings,
           equity_capital, reserves, roce_pct, opm_pct
    FROM financials
    ORDER BY symbol, year
""", conn)

promoter = pd.read_sql("""
    SELECT symbol, quarter_end_date, promoter_pct
    FROM promoter_holdings
    ORDER BY symbol, quarter_end_date
""", conn)

nifty500 = pd.read_sql("""
    SELECT DISTINCT symbol FROM index_membership
    WHERE index_name = 'Nifty 500'
    AND valid_to IS NULL
""", conn)

conn.close()

nifty500_symbols = nifty500['symbol'].tolist()
prices = prices[prices['symbol'].isin(nifty500_symbols)].copy()
prices['date'] = pd.to_datetime(prices['date'])

print(f"Nifty 500 symbols: {len(nifty500_symbols)}")

features = {}

def score(val, low, high):
    if val is None or np.isnan(float(val)):
        return None
    return max(0.0, min(100.0, (float(val) - low) / (high - low) * 100))

# Signal 1: ROE trend
print("Signal 1: ROE trend...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').tail(5).copy()
    if len(grp) < 3:
        continue
    grp['equity'] = grp['equity_capital'] + grp['reserves']
    grp['roe'] = grp['net_profit'] / grp['equity'] * 100
    grp = grp.dropna(subset=['roe'])
    if len(grp) < 3:
        continue
    avg_roe = grp['roe'].mean()
    improving = grp['roe'].iloc[-1] > grp['roe'].iloc[0]
    s = score(avg_roe, 5, 35)
    if s is None:
        continue
    features.setdefault(symbol, {})['s1_roe_trend'] = round(min(100, s * (1.2 if improving else 0.8)), 2)

# Signal 2: Revenue CAGR
print("Signal 2: Revenue CAGR...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['sales'])
    if len(grp) < 4:
        continue
    s_val, e_val = grp.iloc[-4]['sales'], grp.iloc[-1]['sales']
    if s_val <= 0 or e_val <= 0:
        continue
    cagr = (e_val / s_val) ** (1/3) - 1
    accelerating = False
    if len(grp) >= 5:
        mid = grp.iloc[-3]['sales']
        old = grp.iloc[-5]['sales']
        if mid > 0 and old > 0:
            accelerating = (e_val/mid)**0.5 > (mid/old)**0.5
    s = score(cagr * 100, 5, 40)
    if s is None:
        continue
    features.setdefault(symbol, {})['s2_revenue_cagr'] = round(min(100, s * (1.2 if accelerating else 0.9)), 2)

# Signal 5: Promoter trend
print("Signal 5: Promoter trend...")
for symbol, grp in promoter.groupby('symbol'):
    grp = grp.sort_values('quarter_end_date').tail(8)
    if len(grp) < 2:
        continue
    latest = float(grp.iloc[-1]['promoter_pct'])
    earliest = float(grp.iloc[0]['promoter_pct'])
    change = latest - earliest
    s = score(latest, 20, 75) * 0.6 + score(change, -5, 5) * 0.4
    features.setdefault(symbol, {})['s5_promoter_trend'] = round(min(100, s), 2)

# Signal 8: PEG ratio
print("Signal 8: PEG ratio...")
prices_latest = prices.sort_values('date').groupby('symbol').last()['close_price']
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['eps'])
    if len(grp) < 3:
        continue
    eps_now = grp.iloc[-1]['eps']
    eps_old = grp.iloc[-3]['eps']
    if eps_now <= 0 or eps_old <= 0:
        continue
    eps_cagr = (eps_now / eps_old) ** 0.5 - 1
    if eps_cagr <= 0:
        continue
    if symbol not in prices_latest:
        continue
    price = float(prices_latest[symbol])
    pe = price / float(eps_now)
    peg = pe / (eps_cagr * 100)
    s = score(1/peg, 0.1, 2)
    if s is None:
        continue
    features.setdefault(symbol, {})['s8_peg_ratio'] = round(s, 2)

# Signal 10: D/E improvement
print("Signal 10: D/E improvement...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['borrowings','equity_capital','reserves']).copy()
    if len(grp) < 2:
        continue
    grp['equity'] = grp['equity_capital'] + grp['reserves']
    grp['de'] = grp['borrowings'] / grp['equity'].replace(0, np.nan)
    grp = grp.dropna(subset=['de'])
    if len(grp) < 2:
        continue
    latest_de = grp.iloc[-1]['de']
    improving = latest_de < grp.iloc[0]['de']
    s = score(1 / (latest_de + 0.1), 0.1, 5)
    if s is None:
        continue
    features.setdefault(symbol, {})['s10_de_improvement'] = round(min(100, s * (1.2 if improving else 0.8)), 2)

# Signal 11: ROCE sustained
print("Signal 11: ROCE sustained...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['roce_pct']).tail(5)
    if len(grp) < 2:
        continue
    avg_roce = float(grp['roce_pct'].mean())
    pct_above_20 = float((grp['roce_pct'] >= 20).mean() * 100)
    s = score(avg_roce, 5, 40) * 0.6 + score(pct_above_20, 0, 100) * 0.4
    features.setdefault(symbol, {})['s11_roce'] = round(min(100, s), 2)

# Signal 12: EPS CAGR
print("Signal 12: EPS CAGR...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['eps'])
    if len(grp) < 4:
        continue
    eps_old = grp.iloc[-4]['eps']
    eps_new = grp.iloc[-1]['eps']
    if eps_old <= 0 or eps_new <= 0:
        continue
    cagr = (eps_new / eps_old) ** (1/3) - 1
    s = score(cagr * 100, 5, 40)
    if s is None:
        continue
    features.setdefault(symbol, {})['s12_eps_cagr'] = round(min(100, s), 2)

# Signal 15: 12-month relative strength
print("Signal 15: 12-month RS...")
prices_pivot = prices.pivot(index='date', columns='symbol', values='close_price')
latest_date = prices_pivot.index.max()
one_yr_ago = latest_date - pd.DateOffset(months=12)
for symbol in nifty500_symbols:
    if symbol not in prices_pivot.columns:
        continue
    col = prices_pivot[symbol].dropna()
    if len(col) < 200:
        continue
    past = col[col.index <= one_yr_ago]
    if len(past) == 0:
        continue
    ret = (col.iloc[-1] / past.iloc[-1] - 1) * 100
    s = score(ret, -20, 80)
    if s is not None:
        features.setdefault(symbol, {})['s15_rs_12m'] = round(s, 2)

# Composite score — signal weights from CLAUDE_india_models.md
WEIGHTS = {
    's1_roe_trend':      0.10,
    's2_revenue_cagr':   0.10,
    's5_promoter_trend': 0.08,
    's8_peg_ratio':      0.06,
    's10_de_improvement':0.05,
    's11_roce':          0.05,
    's12_eps_cagr':      0.04,
    's15_rs_12m':        0.03,
}
WEIGHT_TOTAL = sum(WEIGHTS.values())

print("Computing composite scores...")
today = date.today()
rows = []
for symbol, sigs in features.items():
    weighted = 0.0
    weight_used = 0.0
    for sig, w in WEIGHTS.items():
        val = sigs.get(sig)
        if val is not None:
            weighted += val * w
            weight_used += w
    composite = round(weighted / weight_used * 100 / 100, 2) if weight_used > 0 else None
    rows.append((
        symbol, today,
        sigs.get('s1_roe_trend'),
        sigs.get('s2_revenue_cagr'),
        sigs.get('s5_promoter_trend'),
        sigs.get('s8_peg_ratio'),
        sigs.get('s10_de_improvement'),
        sigs.get('s11_roce'),
        sigs.get('s12_eps_cagr'),
        sigs.get('s15_rs_12m'),
        composite
    ))

print(f"\nTotal stocks scored: {len(rows)}")

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
execute_values(cur, """
    INSERT INTO model3_features
        (symbol, computed_date, s1_roe_trend, s2_revenue_cagr, s5_promoter_trend,
         s8_peg_ratio, s10_de_improvement, s11_roce, s12_eps_cagr, s15_rs_12m, composite_score)
    VALUES %s
    ON CONFLICT (symbol, computed_date) DO UPDATE SET
        s1_roe_trend = EXCLUDED.s1_roe_trend,
        s2_revenue_cagr = EXCLUDED.s2_revenue_cagr,
        s5_promoter_trend = EXCLUDED.s5_promoter_trend,
        s8_peg_ratio = EXCLUDED.s8_peg_ratio,
        s10_de_improvement = EXCLUDED.s10_de_improvement,
        s11_roce = EXCLUDED.s11_roce,
        s12_eps_cagr = EXCLUDED.s12_eps_cagr,
        s15_rs_12m = EXCLUDED.s15_rs_12m,
        composite_score = EXCLUDED.composite_score
""", rows)
conn.commit()
print(f"Rows upserted: {cur.rowcount}")
cur.close()
conn.close()

# Print top 15 stocks by composite score
df = pd.DataFrame(rows, columns=[
    'symbol','date','s1_roe','s2_rev','s5_prom','s8_peg',
    's10_de','s11_roce','s12_eps','s15_rs','composite'
]).sort_values('composite', ascending=False)

print("\n── TOP 15 MODEL 3 STOCKS TODAY ──────────────────────")
print(df[['symbol','s1_roe','s2_rev','s5_prom','s11_roce','s15_rs','composite']].head(15).to_string(index=False))
