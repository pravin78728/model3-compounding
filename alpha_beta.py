"""
alpha_beta.py
Computes model alpha and beta vs Nifty 500 benchmark.
Uses same 4 forward test periods.
"""
import os, psycopg2, pickle, pandas as pd, numpy as np
from dotenv import load_dotenv
from datetime import date, timedelta
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
cur = conn.cursor()

cur.execute('SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials')
financials = {}
for row in cur.fetchall():
    symbol, year = row[0], row[1]
    equity = float(row[6] or 0) + float(row[7] or 0)
    roe = float(row[3])/equity*100 if (row[3] and equity > 0) else None
    financials.setdefault(symbol, []).append({'year': year,
        'sales': float(row[2]) if row[2] else None,
        'net_profit': float(row[3]) if row[3] else None,
        'roe': roe,
        'de': float(row[5])/equity if (row[5] is not None and equity > 0) else None,
        'roce': float(row[8]) if row[8] else None,
        'opm': float(row[9]) if row[9] else None})

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector='Financial Services'")
fin_syms = set(r[0] for r in cur.fetchall())
cur.execute('SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL')
promoter = {}
for sym, qend, pct in cur.fetchall():
    promoter.setdefault(sym, []).append({'qend': qend, 'pct': float(pct)})
cur.close()
conn.close()

with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)
FEATURES = list(model.feature_names_in_)

prices_df['date'] = pd.to_datetime(prices_df['date'])
price_pivot = prices_df.pivot(index='date', columns='symbol', values='close_price').sort_index()

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

def passes_screen1(symbol, rebal_date):
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)
    if not f0['roe'] or f0['roe'] <= 20: return False
    if not f0['opm'] or f0['opm'] <= 10: return False
    if symbol not in fin_syms:
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
    prom_rows = sorted([r for r in promoter.get(symbol, []) if r['qend'] <= rebal_date],
                       key=lambda x: x['qend'], reverse=True)
    if not prom_rows or prom_rows[0]['pct'] <= 25: return False
    return True

periods = [
    (date(2024,6,1),  date(2024,12,1), 'Jun 2024'),
    (date(2024,12,1), date(2025,6,1),  'Dec 2024'),
    (date(2025,6,1),  date(2025,12,1), 'Jun 2025'),
    (date(2025,12,1), date(2026,6,1),  'Dec 2025'),
]

gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])
model_returns = []
bench_returns = []

print("═"*70)
print("  MODEL vs BENCHMARK — FORWARD TEST ANALYSIS")
print("═"*70)
print(f"\n{'Period':<12} {'Model':>8} {'Benchmark':>11} {'Alpha':>8} {'Model Picks'}")
print("─"*70)

for rebal_date, next_date, label in periods:
    period_df = df[df['rebalance_date']==rebal_date].copy()
    excluded, _ = get_exclusions(gov_conn, rebal_date)
    period_df = period_df[~period_df['symbol'].isin(excluded)]
    mask = period_df['symbol'].apply(lambda s: passes_screen1(s, rebal_date))
    period_df = period_df[mask].copy()
    if len(period_df) > 0:
        period_df['score'] = model.predict(period_df[FEATURES])
        top10 = period_df.nlargest(10, 'score')
    else:
        top10 = period_df

    # Model return
    rets = []
    picks = []
    for _, row in top10.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)
        if p0 and p1 and p0 > 0:
            rets.append((p1-p0)/p0)
            picks.append(row['symbol'])
    model_ret = float(np.mean(rets)) if rets else None

    # Benchmark return (Nifty 500)
    p0b = get_price_on('NIFTY500_IDX', rebal_date)
    p1b = get_price_on('NIFTY500_IDX', next_date)
    bench_ret = (p1b-p0b)/p0b if p0b and p1b else None

    if model_ret is not None and bench_ret is not None:
        alpha = model_ret - bench_ret
        model_returns.append(model_ret)
        bench_returns.append(bench_ret)
        print(f"{label:<12} {model_ret*100:>7.1f}% {bench_ret*100:>10.1f}% {alpha*100:>7.1f}% {', '.join(picks[:5])}")
    else:
        print(f"{label:<12} {'N/A':>8} {'N/A':>11}")

gov_conn.close()

if len(model_returns) >= 2:
    # CAGR
    model_total = float(np.prod([1+r for r in model_returns]))
    bench_total = float(np.prod([1+r for r in bench_returns]))
    n_yrs = len(model_returns)/2
    model_cagr = model_total**(1/n_yrs)-1
    bench_cagr = bench_total**(1/n_yrs)-1

    # Beta = cov(model, bench) / var(bench)
    m = np.array(model_returns)
    b = np.array(bench_returns)
    beta = np.cov(m, b)[0][1] / np.var(b) if np.var(b) > 0 else None

    # Jensen's Alpha = model_cagr - (rf + beta*(bench_cagr - rf))
    rf = 0.065  # 6.5% risk free rate
    if beta:
        jensen_alpha = model_cagr - (rf + beta*(bench_cagr - rf))

    print(f"\n{'═'*70}")
    print(f"  SUMMARY")
    print(f"{'═'*70}")
    print(f"  Model CAGR:      {model_cagr*100:.1f}%")
    print(f"  Benchmark CAGR:  {bench_cagr*100:.1f}%")
    print(f"  Raw Alpha:       {(model_cagr-bench_cagr)*100:.1f}% per year")
    if beta:
        print(f"  Beta:            {beta:.2f}")
        print(f"  Jensen's Alpha:  {jensen_alpha*100:.1f}% per year")
    print(f"{'═'*70}")
