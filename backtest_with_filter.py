"""
backtest_with_filter.py
Top 10 high-conviction picks, strict governance filter, no fill-ins.
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
    WHERE in_validate = TRUE OR in_train = TRUE
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
price_pivot = prices_df.pivot(index='date', columns='symbol', values='close_price').sort_index()

def get_price(symbol, target_date, window=15):
    if symbol not in price_pivot.columns:
        return None
    td = pd.Timestamp(target_date)
    subset = price_pivot.loc[td:td + pd.Timedelta(days=window), symbol].dropna()
    return float(subset.iloc[0]) if len(subset) > 0 else None

rebal_dates = sorted(df['rebalance_date'].unique())
portfolio_returns = []
portfolio_log = []

gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

for rebal_date in rebal_dates:
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['score'] = model.predict(period_df[FEATURES])

    rd_date = pd.Timestamp(rebal_date).date()
    excluded, reasons = get_exclusions(gov_conn, rd_date)
    before = len(period_df)
    period_df = period_df[~period_df['symbol'].isin(excluded)]
    after = len(period_df)

    # Top 10 high-conviction picks
    top10 = period_df.nlargest(10, 'score')

    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year + 1, 6, 1)

    stock_returns = []
    selected = []
    for _, row in top10.iterrows():
        p0 = get_price(row['symbol'], rebal_date)
        p1 = get_price(row['symbol'], next_date)
        if p0 and p1 and p0 > 0:
            ret = (p1 - p0) / p0
            stock_returns.append(ret)
            selected.append((row['symbol'], round(float(row['score']), 2), round(ret*100, 1)))

    if stock_returns:
        port_ret = float(np.mean(stock_returns))
        portfolio_returns.append((rebal_date, port_ret))
        portfolio_log.append({
            'date': rebal_date,
            'excluded': before - after,
            'n_stocks': len(stock_returns),
            'portfolio_return': round(port_ret * 100, 1),
            'top_picks': selected
        })
        print(f"  {rebal_date}: excluded={before-after} | stocks={len(stock_returns)} | return={port_ret*100:.1f}%")

gov_conn.close()

print("\n── Equity curve ──")
equity = 100.0
port_series_data = []
for rd, ret in portfolio_returns:
    equity *= (1 + ret)
    port_series_data.append((rd, ret, equity))
    print(f"  {rd}: period={ret*100:.1f}% | cumulative={equity:.1f}")

port_series = pd.Series(
    [r for _, r, _ in port_series_data],
    index=pd.to_datetime([d for d, _, _ in port_series_data])
)

def cagr(returns, ppyr=2):
    total = float((1 + returns).prod())
    n = len(returns) / ppyr
    return total ** (1/n) - 1

def sharpe(returns, ppyr=2, rf=0.065):
    rf_pp = rf / ppyr
    excess = returns - rf_pp
    return float((excess.mean() / excess.std()) * np.sqrt(ppyr))

def max_dd(returns):
    equity = (1 + returns).cumprod()
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())

pc  = cagr(port_series)
ps  = sharpe(port_series)
pd_ = max_dd(port_series)

vp  = port_series[port_series.index >= '2020-01-01']
vpc = cagr(vp)
vps = sharpe(vp)
vpd = max_dd(vp)

print(f"\n══════════════════════════════════════════")
print(f"  MODEL 3 — TOP 10 HIGH CONVICTION")
print(f"══════════════════════════════════════════")
print(f"\n  FULL PERIOD (2014–2024)")
print(f"  CAGR:          {pc*100:.1f}%   {'✓' if pc>0.28 else '✗'} gate >28%")
print(f"  Sharpe ratio:  {ps:.2f}    {'✓' if ps>2.0 else '✗'} gate >2.0")
print(f"  Max drawdown:  {pd_*100:.1f}%  {'✓' if pd_>-0.30 else '✗'} gate >-30%")
print(f"\n  VALIDATION ONLY (2020–2023)")
print(f"  CAGR:          {vpc*100:.1f}%   {'✓' if vpc>0.28 else '✗'} gate >28%")
print(f"  Sharpe ratio:  {vps:.2f}    {'✓' if vps>2.0 else '✗'} gate >2.0")
print(f"  Max drawdown:  {vpd*100:.1f}%  {'✓' if vpd>-0.30 else '✗'} gate >-30%")
print(f"══════════════════════════════════════════")

print("\n── Picks per period ──")
for entry in portfolio_log:
    print(f"\n  {entry['date']} (return={entry['portfolio_return']}% | n={entry['n_stocks']}):")
    for sym, score, ret in entry['top_picks']:
        print(f"    {sym:<15} score={score}  actual={ret}%")
