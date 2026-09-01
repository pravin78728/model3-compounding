"""
screener2_comparison.py
Applies Pravin's Screen 2 (fundamentals + momentum hybrid) to the 4 forward test dates.
Compares all three: Screen 1, Screen 2, Model 3.

Screen 2 criteria (price-based computed from prices table):
  52wk drawdown from high < 50% AND > 0%  (stock below ATH but not too far)
  Recovery from 52wk low > 50%             (stock bouncing from low)
  Price > 10
  ROE > 20, D/E < 0.9
  Sales growth 3yr > 25%, Profit growth 3yr > 20%
  Sales growth 1yr > 1%, Profit growth 1yr > 1%
  Promoter > 25%, PEG < 1, P/E < 30
  MACD Signal > 1 (12/26/9 standard MACD, signal line positive)

Skipped (not in DB): Market cap>500, Pledged%<1, P/E<Industry PE
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

# Financials
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
        'year': year,
        'sales': float(sales) if sales else None,
        'net_profit': float(np_) if np_ else None,
        'eps': float(eps) if eps else None,
        'roe': roe, 'de': de,
        'roce': float(roce) if roce else None,
        'opm': float(opm) if opm else None,
    })

# Promoter holdings
cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})

# Prices — full history needed for MACD + 52wk calculations
print("  Loading prices...")
cur.execute("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))
print(f"  ✓ prices: {len(prices)} symbols")

cur.execute("SELECT DISTINCT symbol FROM model3_training_data WHERE in_forward_test = TRUE")
universe = [row[0] for row in cur.fetchall()]
cur.close()
print(f"  ✓ universe: {len(universe)} symbols")

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_price_on(symbol, target_date, window=15):
    if symbol not in prices:
        return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end:
            return p
    return None

def get_price_series(symbol, start_date, end_date):
    if symbol not in prices:
        return pd.Series(dtype=float)
    data = [(d, p) for d, p in prices[symbol] if start_date <= d <= end_date]
    if not data:
        return pd.Series(dtype=float)
    dates, vals = zip(*data)
    return pd.Series(vals, index=pd.to_datetime(dates)).sort_index()

def compute_macd(series):
    """Standard MACD: 12/26 EMA difference, 9-period signal line."""
    if len(series) < 35:
        return None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    return float(signal.iloc[-1])

def get_fin_year(symbol, rebal_date):
    cutoff = rebal_date.year - (0 if rebal_date.month >= 4 else 1)
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)
    return rows[0] if rows else None

def get_fin(symbol, year):
    rows = [r for r in financials.get(symbol, []) if r['year'] == year]
    return rows[0] if rows else None

def get_promoter_pct(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, [])
                   if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)
    return rows[0]['pct'] if rows else None

# ── Screen 1 (fundamentals only) ──────────────────────────────────────────────
def apply_screen1(symbol, rebal_date):
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)

    if not f0['roe'] or f0['roe'] <= 20: return False
    if not f0['opm'] or f0['opm'] <= 10: return False
    if not f0['roce'] or f0['roce'] <= 20: return False
    if f0['de'] is None or f0['de'] >= 0.9: return False

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
    if not price or not eps or eps <= 0: return False
    pe = price / eps
    if pe >= 30: return False

    if f1 and f1['eps'] and f1['eps'] > 0:
        eps_growth = (eps-f1['eps'])/f1['eps']*100
        if eps_growth > 0 and pe/eps_growth >= 1: return False

    return True

# ── Screen 2 (fundamentals + momentum) ───────────────────────────────────────
def apply_screen2(symbol, rebal_date):
    # Fundamental checks (subset of Screen 1)
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)

    if not f0['roe'] or f0['roe'] <= 20: return False
    if f0['de'] is None or f0['de'] >= 0.9: return False

    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 25: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False

    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False

    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False

    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if not price or not eps or eps <= 0: return False
    if price <= 10: return False
    pe = price / eps
    if pe >= 50: return False

    if f1 and f1['eps'] and f1['eps'] > 0:
        eps_growth = (eps-f1['eps'])/f1['eps']*100
        if eps_growth > 0 and pe/eps_growth >= 1: return False

    # Price-based momentum checks
    start_52wk = rebal_date - timedelta(days=365)
    series = get_price_series(symbol, start_52wk, rebal_date)
    if len(series) < 50: return False

    high_52wk = series.max()
    low_52wk  = series.min()
    current   = float(series.iloc[-1])

    # Drawdown from high: 0% < drawdown < 50%
    drawdown = (high_52wk - current) / high_52wk * 100
    if drawdown <= 0 or drawdown >= 50: return False

    # Recovery from low > 50%
    recovery = (current / low_52wk - 1) * 100
    if recovery <= 50: return False

    # MACD signal > 1
    macd_signal = compute_macd(series)
    if macd_signal is None or macd_signal <= 0: return False

    return True

# ── Model 3 setup ─────────────────────────────────────────────────────────────
with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's8_peg_ratio',
    's9_dii_accumulation', 's10_de_improvement', 's11_roce',
    's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE in_forward_test = TRUE
    ORDER BY rebalance_date, symbol
""", conn)

gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])

forward_dates = [
    date(2024, 6, 1),
    date(2024, 12, 1),
    date(2025, 6, 1),
    date(2025, 12, 1),
]

print("\n" + "═"*70)
print("  THREE-WAY COMPARISON: Screen 1 vs Screen 2 vs Model 3")
print("═"*70)

s1_returns, s2_returns, m3_returns = [], [], []

for rebal_date in forward_dates:
    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    # Screen 1 picks
    s1_picks = [s for s in universe if apply_screen1(s, rebal_date)]
    s1_rets = []
    for sym in s1_picks:
        p0 = get_price_on(sym, rebal_date)
        p1 = get_price_on(sym, next_date)
        if p0 and p1 and p0 > 0:
            s1_rets.append((p1-p0)/p0)
    s1_port = float(np.mean(s1_rets)) if s1_rets else None

    # Screen 2 picks
    s2_picks = [s for s in universe if apply_screen2(s, rebal_date)]
    s2_rets = []
    s2_pick_detail = []
    for sym in s2_picks:
        p0 = get_price_on(sym, rebal_date)
        p1 = get_price_on(sym, next_date)
        if p0 and p1 and p0 > 0:
            ret = (p1-p0)/p0
            s2_rets.append(ret)
            s2_pick_detail.append((sym, ret*100))
    s2_port = float(np.mean(s2_rets)) if s2_rets else None

    # Model 3 picks
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

    s1_str = f"{s1_port*100:.1f}%" if s1_port is not None else "N/A"
    s2_str = f"{s2_port*100:.1f}%" if s2_port is not None else "N/A"
    m3_str = f"{m3_port*100:.1f}%" if m3_port is not None else "N/A"

    print(f"\n{'─'*70}")
    print(f"  {rebal_date}")
    print(f"  Screen 1 (fundamentals):      {len(s1_picks):3d} picks | return={s1_str}")
    print(f"  Screen 2 (fundamentals+mom):  {len(s2_picks):3d} picks | return={s2_str}")
    print(f"  Model 3 (RF):                  10 picks | return={m3_str}")

    # Screen 2 picks detail
    if s2_pick_detail:
        s2_pick_detail.sort(key=lambda x: x[1], reverse=True)
        print(f"\n  Screen 2 picks:")
        for sym, ret in s2_pick_detail:
            print(f"    {sym:<15} {ret:>8.1f}%")

    # Overlap
    s1_set = set(s1_picks)
    s2_set = set(s2_picks)
    m3_set = set(top10['symbol'].tolist())
    print(f"\n  Overlap S1∩S2: {sorted(s1_set & s2_set) or 'none'}")
    print(f"  Overlap S2∩M3: {sorted(s2_set & m3_set) or 'none'}")
    print(f"  Overlap S1∩M3: {sorted(s1_set & m3_set) or 'none'}")

gov_conn.close()

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'═'*70}")
print(f"  OVERALL SUMMARY (4 forward test periods, Jun 2024 – Jun 2026)")
print(f"{'═'*70}")

for label, rets in [("Screen 1 (fundamentals)", s1_returns),
                     ("Screen 2 (fund+momentum)", s2_returns),
                     ("Model 3 RF (top 10)    ", m3_returns)]:
    if rets:
        avg  = np.mean(rets)*100
        total = float((pd.Series(rets)+1).prod())
        cagr  = (total**(1/2)-1)*100
        print(f"  {label}: avg={avg:.1f}%  CAGR={cagr:.1f}%  periods={len(rets)}")
    else:
        print(f"  {label}: no data")

print(f"{'═'*70}")
conn.close()
