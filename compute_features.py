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

prices = pd.read_sql("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date", conn)
financials = pd.read_sql("SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials ORDER BY symbol, year", conn)
quarterly = pd.read_sql("SELECT symbol, quarter, sales, net_profit, eps FROM quarterly_financials ORDER BY symbol, quarter", conn)
cashflow = pd.read_sql("SELECT symbol, year, cfo, free_cash_flow FROM cashflow ORDER BY symbol, year", conn)
promoter = pd.read_sql("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings ORDER BY symbol, quarter_end_date", conn)
inst = pd.read_sql("SELECT symbol, period, fii_pct, dii_pct FROM institutional_holdings ORDER BY symbol, period", conn)
macro = pd.read_sql("SELECT indicator, date, value FROM macro_indicators ORDER BY indicator, date", conn)
pli = pd.read_sql("SELECT symbol, pli_sector, estimated_incentive_cr FROM pli_beneficiaries WHERE active = TRUE", conn)
nifty500 = pd.read_sql("SELECT DISTINCT symbol FROM index_membership WHERE index_name = 'Nifty 500' AND valid_to IS NULL", conn)

conn.close()

nifty500_symbols = nifty500['symbol'].tolist()
prices = prices[prices['symbol'].isin(nifty500_symbols)].copy()
prices['date'] = pd.to_datetime(prices['date'])

print(f"Nifty 500 symbols: {len(nifty500_symbols)}")

features = {}

def score(val, low, high):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    return max(0.0, min(100.0, (float(val) - low) / (high - low) * 100))

# ── SIGNAL 1: ROE trend ──────────────────────────────────────────────────────
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

# ── SIGNAL 2: Revenue CAGR ───────────────────────────────────────────────────
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

# ── SIGNAL 3: FCF yield + growth ─────────────────────────────────────────────
print("Signal 3: FCF yield + growth...")
prices_latest = prices.sort_values('date').groupby('symbol').last()['close_price']
for symbol, grp in cashflow.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['free_cash_flow'])
    if len(grp) < 2:
        continue
    latest_fcf = float(grp.iloc[-1]['free_cash_flow'])
    if latest_fcf <= 0:
        continue
    # FCF growth trend
    fcf_growing = grp['free_cash_flow'].iloc[-1] > grp['free_cash_flow'].iloc[0]
    # FCF yield: need market cap proxy — use latest close * shares outstanding approximation
    # Score purely on FCF growth consistency for now
    positive_fcf_pct = (grp['free_cash_flow'] > 0).mean() * 100
    s = score(positive_fcf_pct, 30, 100) * 0.6 + score(latest_fcf, 0, 50000) * 0.4
    if s is None:
        continue
    features.setdefault(symbol, {})['s3_fcf'] = round(min(100, s * (1.2 if fcf_growing else 0.8)), 2)

# ── SIGNAL 4: PLI / sector tailwind ─────────────────────────────────────────
print("Signal 4: PLI tailwind...")
pli_scores = {}
for _, row in pli.iterrows():
    sym = row['symbol']
    incentive = float(row['estimated_incentive_cr']) if row['estimated_incentive_cr'] else 0
    s = score(incentive, 300, 8000)
    if s is not None:
        pli_scores[sym] = round(s, 2)

for sym, s in pli_scores.items():
    features.setdefault(sym, {})['s4_pli_tailwind'] = s

# ── SIGNAL 5: Promoter trend ─────────────────────────────────────────────────
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

# ── SIGNAL 6: Earnings consistency (8 quarters) ──────────────────────────────
print("Signal 6: Earnings consistency...")
for symbol, grp in quarterly.groupby('symbol'):
    grp = grp.sort_values('quarter').tail(8)
    if len(grp) < 4:
        continue
    grp = grp.dropna(subset=['net_profit'])
    if len(grp) < 4:
        continue
    # Consistency: % of quarters with positive profit + YoY growth
    positive_qtrs = (grp['net_profit'] > 0).mean() * 100
    # Check if latest 4 qtrs better than prior 4
    if len(grp) >= 8:
        recent_avg = grp.tail(4)['net_profit'].mean()
        prior_avg = grp.head(4)['net_profit'].mean()
        improving = recent_avg > prior_avg if prior_avg > 0 else False
    else:
        improving = grp.iloc[-1]['net_profit'] > grp.iloc[0]['net_profit']
    s = score(positive_qtrs, 50, 100) * (1.2 if improving else 0.8)
    features.setdefault(symbol, {})['s6_earnings_consistency'] = round(min(100, s), 2)

# ── SIGNAL 8: PEG ratio ──────────────────────────────────────────────────────
print("Signal 8: PEG ratio...")
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
    if symbol not in prices_latest.index:
        continue
    price = float(prices_latest[symbol])
    pe = price / float(eps_now)
    peg = pe / (eps_cagr * 100)
    s = score(1/peg, 0.1, 2)
    if s is None:
        continue
    features.setdefault(symbol, {})['s8_peg_ratio'] = round(s, 2)

# ── SIGNAL 9: DII accumulation trend (MF proxy) ──────────────────────────────
print("Signal 9: DII/MF accumulation...")
for symbol, grp in inst.groupby('symbol'):
    grp = grp.sort_values('period').tail(8).dropna(subset=['dii_pct'])
    if len(grp) < 3:
        continue
    latest_dii = float(grp.iloc[-1]['dii_pct'])
    earliest_dii = float(grp.iloc[0]['dii_pct'])
    change = latest_dii - earliest_dii
    # Rising DII over 8 quarters = institutional accumulation
    s = score(latest_dii, 2, 40) * 0.5 + score(change, -5, 10) * 0.5
    features.setdefault(symbol, {})['s9_dii_accumulation'] = round(min(100, s), 2)

# ── SIGNAL 10: D/E improvement ───────────────────────────────────────────────
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

# ── SIGNAL 11: ROCE sustained ────────────────────────────────────────────────
print("Signal 11: ROCE sustained...")
for symbol, grp in financials.groupby('symbol'):
    grp = grp.sort_values('year').dropna(subset=['roce_pct']).tail(5)
    if len(grp) < 2:
        continue
    avg_roce = float(grp['roce_pct'].mean())
    pct_above_20 = float((grp['roce_pct'] >= 20).mean() * 100)
    s = score(avg_roce, 5, 40) * 0.6 + score(pct_above_20, 0, 100) * 0.4
    features.setdefault(symbol, {})['s11_roce'] = round(min(100, s), 2)

# ── SIGNAL 12: EPS CAGR ──────────────────────────────────────────────────────
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

# ── SIGNAL 14: Macro cycle alignment ─────────────────────────────────────────
print("Signal 14: Macro cycle...")
# Get current rate cycle
rate_cycle = macro[macro['indicator'] == 'rate_cycle'].sort_values('date')
current_cycle = float(rate_cycle.iloc[-1]['value']) if len(rate_cycle) > 0 else 0
# Get current repo rate
repo = macro[macro['indicator'] == 'repo_rate'].sort_values('date')
current_rate = float(repo.iloc[-1]['value']) if len(repo) > 0 else 6.5
# Cutting cycle + low rate = bullish macro = higher score for all stocks
# Rate-sensitive sectors get higher boost — apply uniform macro score for now
macro_score = 75.0 if current_cycle == -1 else 35.0  # cutting = bullish
# Adjust for rate level: lower rate = more bullish
rate_adjustment = score(10 - current_rate, 3, 7)
if rate_adjustment:
    macro_score = macro_score * 0.7 + rate_adjustment * 0.3
for symbol in nifty500_symbols:
    features.setdefault(symbol, {})['s14_macro_cycle'] = round(macro_score, 2)

# ── SIGNAL 15: 12-month RS ───────────────────────────────────────────────────
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

# ── COMPOSITE SCORE ───────────────────────────────────────────────────────────
print("Computing composite scores...")

WEIGHTS = {
    's1_roe_trend':          0.10,
    's2_revenue_cagr':       0.10,
    's3_fcf':                0.09,
    's4_pli_tailwind':       0.09,
    's5_promoter_trend':     0.08,
    's6_earnings_consistency':0.08,
    's8_peg_ratio':          0.06,
    's9_dii_accumulation':   0.06,
    's10_de_improvement':    0.05,
    's11_roce':              0.05,
    's12_eps_cagr':          0.04,
    's14_macro_cycle':       0.04,
    's15_rs_12m':            0.03,
}

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
    composite = round(weighted / weight_used, 2) if weight_used > 0 else None
    rows.append((
        symbol, today,
        sigs.get('s1_roe_trend'),
        sigs.get('s2_revenue_cagr'),
        sigs.get('s3_fcf'),
        sigs.get('s4_pli_tailwind'),
        sigs.get('s5_promoter_trend'),
        sigs.get('s6_earnings_consistency'),
        sigs.get('s8_peg_ratio'),
        sigs.get('s9_dii_accumulation'),
        sigs.get('s10_de_improvement'),
        sigs.get('s11_roce'),
        sigs.get('s12_eps_cagr'),
        sigs.get('s14_macro_cycle'),
        sigs.get('s15_rs_12m'),
        composite
    ))

print(f"Total stocks scored: {len(rows)}")

# Update table schema to add new columns
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

cur.execute("""
    ALTER TABLE model3_features
    ADD COLUMN IF NOT EXISTS s3_fcf NUMERIC,
    ADD COLUMN IF NOT EXISTS s4_pli_tailwind NUMERIC,
    ADD COLUMN IF NOT EXISTS s6_earnings_consistency NUMERIC,
    ADD COLUMN IF NOT EXISTS s9_dii_accumulation NUMERIC,
    ADD COLUMN IF NOT EXISTS s14_macro_cycle NUMERIC;
""")

execute_values(cur, """
    INSERT INTO model3_features
        (symbol, computed_date, s1_roe_trend, s2_revenue_cagr, s3_fcf, s4_pli_tailwind,
         s5_promoter_trend, s6_earnings_consistency, s8_peg_ratio, s9_dii_accumulation,
         s10_de_improvement, s11_roce, s12_eps_cagr, s14_macro_cycle, s15_rs_12m,
         composite_score)
    VALUES %s
    ON CONFLICT (symbol, computed_date) DO UPDATE SET
        s1_roe_trend = EXCLUDED.s1_roe_trend,
        s2_revenue_cagr = EXCLUDED.s2_revenue_cagr,
        s3_fcf = EXCLUDED.s3_fcf,
        s4_pli_tailwind = EXCLUDED.s4_pli_tailwind,
        s5_promoter_trend = EXCLUDED.s5_promoter_trend,
        s6_earnings_consistency = EXCLUDED.s6_earnings_consistency,
        s8_peg_ratio = EXCLUDED.s8_peg_ratio,
        s9_dii_accumulation = EXCLUDED.s9_dii_accumulation,
        s10_de_improvement = EXCLUDED.s10_de_improvement,
        s11_roce = EXCLUDED.s11_roce,
        s12_eps_cagr = EXCLUDED.s12_eps_cagr,
        s14_macro_cycle = EXCLUDED.s14_macro_cycle,
        s15_rs_12m = EXCLUDED.s15_rs_12m,
        composite_score = EXCLUDED.composite_score
""", rows)

conn.commit()
print(f"Rows upserted: {cur.rowcount}")
cur.close()
conn.close()

# Print top 20
df = pd.DataFrame(rows, columns=[
    'symbol','date','s1_roe','s2_rev','s3_fcf','s4_pli','s5_prom',
    's6_earn','s8_peg','s9_dii','s10_de','s11_roce','s12_eps',
    's14_macro','s15_rs','composite'
]).sort_values('composite', ascending=False)

print("\n── TOP 20 MODEL 3 STOCKS TODAY ──────────────────────────────")
print(df[['symbol','s1_roe','s2_rev','s3_fcf','s6_earn','s9_dii','s15_rs','composite']].head(20).to_string(index=False))
