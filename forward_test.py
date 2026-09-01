"""
forward_test.py
Scores the 4 missed rebalance dates as genuine out-of-sample forward test.
Dec 2024, Jun 2025, Dec 2025 = full 6-month returns available.
Jun 2026 = partial (~2 months available).
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date
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
conn.close()

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

rebal_dates = sorted(df['rebalance_date'].unique())
gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

print("═" * 65)
print("  MODEL 3 — GENUINE FORWARD TEST (OUT-OF-SAMPLE)")
print("  Model trained on 2014–2019, validated 2020–2023")
print("  These dates were NEVER seen by the model in any form")
print("═" * 65)

all_results = []

for rebal_date in rebal_dates:
    rd = pd.Timestamp(rebal_date)
    is_partial = rebal_date >= date(2026, 6, 1)

    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['score'] = model.predict(period_df[FEATURES])

    # Apply governance filter
    excluded, reasons = get_exclusions(gov_conn, rebal_date)
    before = len(period_df)
    period_df = period_df[~period_df['symbol'].isin(excluded)]

    # Top 10 high-conviction picks
    top10 = period_df.nlargest(10, 'score')

    # Calculate actual returns
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    picks = []
    returns = []
    for _, row in top10.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)

        # For Jun 2026, use latest available price
        if is_partial and p1 is None:
            p1 = get_price_on(row['symbol'], date(2026, 8, 28), window=5)

        if p0 and p1 and p0 > 0:
            ret = (p1 - p0) / p0
            returns.append(ret)
            picks.append({
                'symbol': row['symbol'],
                'score': round(float(row['score']), 3),
                'return': round(ret*100, 1),
                'fwd_return_db': round(float(row['forward_6m_return'])*100, 1)
                    if row['forward_6m_return'] is not None else None
            })
        else:
            picks.append({
                'symbol': row['symbol'],
                'score': round(float(row['score']), 3),
                'return': None,
                'fwd_return_db': None
            })

    port_ret = float(np.mean(returns)) if returns else None
    all_results.append((rebal_date, port_ret, picks))

    label = "(PARTIAL ~2mo)" if is_partial else "(FULL 6mo)"
    ret_str = f"{port_ret*100:.1f}%" if port_ret is not None else "N/A"

    print(f"\n{'─'*65}")
    print(f"  {rebal_date}  {label}")
    print(f"  Universe: {before} → {len(period_df)} after filter | excluded: {before-len(period_df)}")
    print(f"  Portfolio return: {ret_str}")
    print(f"{'─'*65}")
    print(f"  {'Symbol':<14} {'Score':>7} {'Actual Return':>14}")
    for p in picks:
        ret_disp = f"{p['return']}%" if p['return'] is not None else "pending"
        print(f"  {p['symbol']:<14} {p['score']:>7.3f} {ret_disp:>14}")

gov_conn.close()

# Summary across complete periods only
complete = [(rd, ret) for rd, ret, _ in all_results
            if ret is not None and rd < date(2026, 6, 1)]

if complete:
    series = pd.Series([r for _, r in complete])
    total = float((1+series).prod())
    n_years = len(complete) / 2
    cagr = total**(1/n_years) - 1 if n_years > 0 else None

    print(f"\n{'═'*65}")
    print(f"  FORWARD TEST SUMMARY (complete periods only)")
    print(f"{'═'*65}")
    for rd, ret in complete:
        print(f"  {rd}: {ret*100:.1f}%")
    print(f"\n  Periods:      {len(complete)} semi-annual")
    print(f"  Total return: {(total-1)*100:.1f}%")
    if cagr:
        print(f"  Ann. CAGR:    {cagr*100:.1f}%  {'✓' if cagr>0.28 else '✗'} gate >28%")
    print(f"{'═'*65}")
