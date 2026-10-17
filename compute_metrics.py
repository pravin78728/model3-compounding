import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
import yfinance as yf
from dotenv import load_dotenv
from datetime import date

load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
df = pd.read_sql("SELECT * FROM model3_training_data WHERE in_validate = TRUE OR in_train = TRUE ORDER BY rebalance_date, symbol", conn)
prices_df = pd.read_sql("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date", conn)
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

for rebal_date in rebal_dates:
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['score'] = model.predict(period_df[FEATURES])
    top25 = period_df.nlargest(25, 'score')
    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year + 1, 6, 1)
    stock_returns = []
    for _, row in top25.iterrows():
        p0 = get_price(row['symbol'], rebal_date)
        p1 = get_price(row['symbol'], next_date)
        if p0 and p1 and p0 > 0:
            stock_returns.append((p1 - p0) / p0)
    if stock_returns:
        portfolio_returns.append((rebal_date, float(np.mean(stock_returns))))

port_df = pd.DataFrame(portfolio_returns, columns=['date', 'return'])
port_df['date'] = pd.to_datetime(port_df['date'])
port_df = port_df.set_index('date')
port_series = port_df['return']

# Benchmark
print("Downloading Nifty 500 benchmark...")
start = port_df.index[0].strftime('%Y-%m-%d')
bench = yf.download('^CRSLDX', start=start, end='2024-06-01', auto_adjust=True, progress=False)
if bench.empty:
    bench = yf.download('^NSEI', start=start, end='2024-06-01', auto_adjust=True, progress=False)

bench_prices = bench['Close'].resample('6ME').last()
bench_rets = bench_prices.pct_change().dropna()
bench_rets = bench_rets.reindex(port_series.index, method='nearest', tolerance='90D').dropna()
bench_rets = bench_rets.astype(float)
aligned_port = port_series.reindex(bench_rets.index).dropna()

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

# Full period
pc  = cagr(port_series)
ps  = sharpe(port_series)
pd_ = max_dd(port_series)
bc  = cagr(bench_rets)
al  = pc - bc

# Validation only
vp = port_series[port_series.index >= '2020-01-01']
vb = bench_rets[bench_rets.index >= '2020-01-01']
vpc = cagr(vp)
vps = sharpe(vp)
vpd = max_dd(vp)
vbc = cagr(vb) if len(vb) > 0 else None
val = vpc - vbc if vbc is not None else None

print("\n══════════════════════════════════════════")
print("  MODEL 3 — PERFORMANCE REPORT")
print("══════════════════════════════════════════")
print(f"\n  FULL PERIOD (2014–2024)")
print(f"  CAGR:           {pc*100:.1f}%   {'✓' if pc>0.28 else '✗'} gate >28%")
print(f"  Sharpe ratio:   {ps:.2f}    {'✓' if ps>2.0 else '✗'} gate >2.0")
print(f"  Max drawdown:   {pd_*100:.1f}%  {'✓' if pd_>-0.30 else '✗'} gate >-30%")
print(f"  Benchmark CAGR: {bc*100:.1f}%")
print(f"  Alpha:          {al*100:.1f}%   {'✓' if al>0.08 else '✗'} gate >8%")
print(f"\n  VALIDATION ONLY (2020–2023)")
print(f"  CAGR:           {vpc*100:.1f}%   {'✓' if vpc>0.28 else '✗'} gate >28%")
print(f"  Sharpe ratio:   {vps:.2f}    {'✓' if vps>2.0 else '✗'} gate >2.0")
print(f"  Max drawdown:   {vpd*100:.1f}%  {'✓' if vpd>-0.30 else '✗'} gate >-30%")
if val is not None:
    print(f"  Alpha vs bench: {val*100:.1f}%   {'✓' if val>0.08 else '✗'} gate >8%")
print("\n══════════════════════════════════════════")
