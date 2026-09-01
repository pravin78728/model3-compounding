"""
backtest_regime_aware.py — Option B
RF model scores stocks (learned signal interactions).
Regime classifier sets quality floor thresholds.
Quality pre-filter eliminates stocks below floor.
Top picks ranked by RF score.
Governance filter as final check.
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions
from regime_classifier import classify_regime, QUALITY_FLOORS

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

# Load financials for quality pre-filter
cur = conn.cursor()
cur.execute("""
    SELECT symbol, year, sales, net_profit, eps,
           borrowings, equity_capital, reserves, roce_pct, opm_pct
    FROM financials
""")
financials = {}
for symbol, year, sales, np_, eps, borr, eq, res, roce, opm in cur.fetchall():
    equity = float(eq or 0) + float(res or 0)
    roe  = float(np_)/equity*100 if (np_ and equity > 0) else None
    de   = float(borr)/equity if (borr is not None and equity > 0) else None
    financials.setdefault(symbol, []).append({
        'year': year, 'roe': roe, 'de': de,
        'roce': float(roce) if roce else None,
        'opm':  float(opm)  if opm  else None,
    })
cur.close()

with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's8_peg_ratio',
    's9_dii_accumulation', 's10_de_improvement', 's11_roce',
    's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

prices_df['date'] = pd.to_datetime(prices_df['date'])
price_pivot = prices_df.pivot(
    index='date', columns='symbol', values='close_price'
).sort_index()

def get_price_on(symbol, target_date, window=15):
    if symbol not in price_pivot.columns:
        return None
    td = pd.Timestamp(target_date)
    subset = price_pivot.loc[td:td+pd.Timedelta(days=window), symbol].dropna()
    return float(subset.iloc[0]) if len(subset) > 0 else None

def passes_quality_floor(symbol, rebal_date, floors):
    # Point-in-time: fiscal year ending before rebalance date
    # Indian fiscal year ends March. Jun rebalance uses FY ending Mar same year.
    # Dec rebalance uses FY ending Mar same year.
    cutoff_year = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= cutoff_year],
                  key=lambda x: x['year'], reverse=True)
    if not rows:
        return False
    f = rows[0]
    # Must be recent enough — within 2 years of rebalance date
    if rebal_date.year - f['year'] > 2:
        return False
    if f['roe']  is None or f['roe']  < floors['roe']:  return False
    if f['roce'] is None or f['roce'] < floors['roce']: return False
    if f['de']   is None or f['de']   > floors['de']:   return False
    if f['opm']  is None or f['opm']  < floors['opm']:  return False
    # Also check trend — if ROE declining sharply, flag it
    if len(rows) >= 2 and rows[1]['roe'] is not None and f['roe'] is not None:
        roe_decline = rows[1]['roe'] - f['roe']  # positive = declining
        if roe_decline > 10:  # ROE fell more than 10 points in one year
            return False
    return True

rebal_dates = sorted(df['rebalance_date'].unique())
gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

print("═"*65)
print("  MODEL 3 — OPTION B: RF SCORES + REGIME QUALITY GATE")
print("═"*65)

all_results = []

for rebal_date in rebal_dates:
    # Step 1: Classify regime
    regime, signals = classify_regime(rebal_date, conn)

    # Use CHOPPY floors for WEAK_BULL if that regime exists
    floor_key = regime if regime in QUALITY_FLOORS else 'CHOPPY'
    floors = QUALITY_FLOORS[floor_key]

    # Crisis: reduce to top 5 picks only
    max_picks = 5 if regime == 'CRISIS' else 10

    # Step 2: Score all stocks with RF model
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['rf_score'] = model.predict(period_df[FEATURES])

    # Step 3: Governance filter
    excluded, _ = get_exclusions(gov_conn, rebal_date)
    before_gov = len(period_df)
    period_df = period_df[~period_df['symbol'].isin(excluded)]

    # Step 4: Quality pre-filter (regime-specific floors)
    quality_mask = period_df['symbol'].apply(
        lambda s: passes_quality_floor(s, rebal_date, floors)
    )
    before_quality = len(period_df)
    period_df = period_df[quality_mask]
    after_quality = len(period_df)

    # Step 5: Rank by RF score, pick top N by conviction
    top_all = period_df.nlargest(max_picks * 2, 'rf_score')
    if len(top_all) > 0:
        top_score = float(top_all['rf_score'].iloc[0])
        # Conviction threshold: within 15% of top score
        threshold = top_score * 0.85
        top_picks = top_all[top_all['rf_score'] >= threshold].head(max_picks)
    else:
        top_picks = top_all

    # Step 6: Calculate returns
    rd = pd.Timestamp(rebal_date)
    is_partial = rebal_date >= date(2026, 6, 1)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    stock_returns = []
    selected = []
    for _, row in top_picks.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)
        if is_partial and p1 is None:
            p1 = get_price_on(row['symbol'], date(2026, 8, 28), window=5)
        if p0 and p1 and p0 > 0:
            ret = (p1-p0)/p0
            stock_returns.append(ret)
            selected.append((
                row['symbol'],
                round(float(row['rf_score']), 3),
                round(ret*100, 1)
            ))

    port_ret = float(np.mean(stock_returns)) if stock_returns else None
    all_results.append((rebal_date, port_ret, regime))

    label = "(PARTIAL)" if is_partial else "(FULL)"
    ret_str = f"{port_ret*100:.1f}%" if port_ret is not None else "N/A"

    print(f"\n{'─'*65}")
    print(f"  {rebal_date} {label} | Regime: {regime}")
    print(f"  Filters: gov={before_gov}→{before_quality} | quality={before_quality}→{after_quality} | picks={len(selected)}")
    print(f"  Portfolio return: {ret_str}")
    print(f"  {'Symbol':<14} {'RF Score':>9} {'Return':>10}")
    for sym, score, ret in selected:
        print(f"  {sym:<14} {score:>9.3f} {ret:>9.1f}%")

gov_conn.close()

# Summary
complete = [(rd, ret, reg) for rd, ret, reg in all_results
            if ret is not None and rd < date(2026, 6, 1)]

if complete:
    series = pd.Series([r for _, r, _ in complete])
    total  = float((1+series).prod())
    n_yrs  = len(complete) / 2
    cagr   = total**(1/n_yrs) - 1

    print(f"\n{'═'*65}")
    print(f"  FORWARD TEST SUMMARY — RF + REGIME QUALITY GATE")
    print(f"{'═'*65}")
    for rd, ret, reg in complete:
        print(f"  {rd} [{reg:<7}]: {ret*100:.1f}%")
    print(f"\n  Total return: {(total-1)*100:.1f}%")
    print(f"  Ann. CAGR:    {cagr*100:.1f}%  {'✓' if cagr>0.28 else '✗'} gate >28%")
    print(f"{'═'*65}")

conn.close()
