"""
backtest_model3.py
Simulates Model 3 portfolio using trained Random Forest scores.
Semi-annual rebalance, 25 stock portfolio, equal weight.
Compares vs Nifty 500 benchmark using QuantStats.
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
import quantstats as qs
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

# ── Load model and data ───────────────────────────────────────────────────────
print("Loading model and data...")
with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

conn = psycopg2.connect(os.environ['DATABASE_URL'])

df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE in_validate = TRUE OR in_train = TRUE
    ORDER BY rebalance_date, symbol
""", conn)

# Load prices for portfolio return calculation
prices_df = pd.read_sql("""
    SELECT symbol, date, close_price
    FROM prices
    WHERE close_price IS NOT NULL
    ORDER BY symbol, date
""", conn)
conn.close()

print(f"  Training+Validate rows: {len(df)}")
print(f"  Price rows: {len(prices_df)}")

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's8_peg_ratio',
    's9_dii_accumulation', 's10_de_improvement', 's11_roce',
    's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

# ── Build price lookup ────────────────────────────────────────────────────────
prices_df['date'] = pd.to_datetime(prices_df['date'])
price_pivot = prices_df.pivot(index='date', columns='symbol', values='close_price')
price_pivot = price_pivot.sort_index()

def get_price(symbol, target_date, window=15):
    if symbol not in price_pivot.columns:
        return None
    td = pd.Timestamp(target_date)
    end = td + pd.Timedelta(days=window)
    subset = price_pivot.loc[td:end, symbol].dropna()
    return float(subset.iloc[0]) if len(subset) > 0 else None

# ── Score all stocks at each rebalance date ───────────────────────────────────
print("\nScoring stocks at each rebalance date...")
rebal_dates = sorted(df['rebalance_date'].unique())

portfolio_returns = []  # list of (date, portfolio_return)
portfolio_log = []      # detailed log per period

for i, rebal_date in enumerate(rebal_dates):
    # Score stocks at this date
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    X = period_df[FEATURES]
    period_df['score'] = model.predict(X)

    # Select top 25 stocks by score
    top25 = period_df.nlargest(25, 'score')

    # Calculate next period end date
    rd = pd.Timestamp(rebal_date)
    if rd.month == 6:
        next_date = date(rd.year, 12, 1)
    else:
        next_date = date(rd.year + 1, 6, 1)

    # Calculate equal-weight portfolio return
    stock_returns = []
    selected = []
    for _, row in top25.iterrows():
        p_start = get_price(row['symbol'], rebal_date)
        p_end   = get_price(row['symbol'], next_date)
        if p_start and p_end and p_start > 0:
            ret = (p_end - p_start) / p_start
            stock_returns.append(ret)
            selected.append((row['symbol'], round(row['score'], 2), round(ret*100, 1)))

    if stock_returns:
        port_ret = np.mean(stock_returns)
        portfolio_returns.append((rebal_date, port_ret))
        portfolio_log.append({
            'date': rebal_date,
            'n_stocks': len(stock_returns),
            'portfolio_return': round(port_ret * 100, 1),
            'top_picks': selected[:5]  # show top 5
        })
        print(f"  {rebal_date}: {len(stock_returns)} stocks | period return={port_ret*100:.1f}%")

# ── Build equity curve ────────────────────────────────────────────────────────
print("\n── Portfolio equity curve ──")
equity = 100.0
equity_curve = []
for rd, ret in portfolio_returns:
    equity *= (1 + ret)
    equity_curve.append((rd, equity))
    print(f"  {rd}: period={ret*100:.1f}% | cumulative={equity:.1f}")

# ── Compute CAGR ─────────────────────────────────────────────────────────────
first_date = pd.Timestamp(portfolio_returns[0][0])
last_date  = pd.Timestamp(portfolio_returns[-1][0])
years = (last_date - first_date).days / 365.25
final_equity = equity_curve[-1][1]
cagr = (final_equity / 100) ** (1 / years) - 1

print(f"\n── Summary ──")
print(f"  Period:        {first_date.date()} → {last_date.date()}")
print(f"  Years:         {years:.1f}")
print(f"  Final equity:  {final_equity:.1f} (started at 100)")
print(f"  CAGR:          {cagr*100:.1f}%")
print(f"  Success gate:  >28% CAGR {'✓ PASS' if cagr > 0.28 else '✗ FAIL'}")

# ── Validate-only CAGR ────────────────────────────────────────────────────────
val_returns = [(rd, ret) for rd, ret in portfolio_returns
               if pd.Timestamp(rd) >= pd.Timestamp('2020-01-01')]
if val_returns:
    val_equity = 100.0
    for _, ret in val_returns:
        val_equity *= (1 + ret)
    val_years = len(val_returns) / 2  # semi-annual periods
    val_cagr = (val_equity / 100) ** (1 / val_years) - 1
    print(f"\n── Validation period only (2020–2023) ──")
    print(f"  CAGR: {val_cagr*100:.1f}%")
    print(f"  Success gate >28%: {'✓ PASS' if val_cagr > 0.28 else '✗ FAIL'}")

# ── Top picks log ─────────────────────────────────────────────────────────────
print("\n── Top 5 picks per period ──")
for entry in portfolio_log:
    print(f"\n  {entry['date']} (return={entry['portfolio_return']}%):")
    for sym, score, ret in entry['top_picks']:
        print(f"    {sym:<15} score={score}  actual={ret}%")

print("\n✓ Backtest complete. Next: python3 shap_analysis.py")
