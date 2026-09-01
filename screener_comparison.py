"""
screener_comparison.py
Applies Pravin's manual Screener.in screen to the same 4 forward test dates.
Compares picks and returns vs Model 3 RF output.

Screen criteria (applied point-in-time):
  ROE > 20
  OPM > 10
  ROCE > 20
  D/E < 0.9
  Sales growth 1yr > 1%
  Profit growth 1yr > 1%
  Sales growth 3yr > 20%
  Profit growth 3yr > 25%
  Promoter holding > 25%
  PEG < 1
  P/E < 30
  Market cap > 500 Cr  -- SKIPPED (not in DB)
  Pledged % < 1        -- SKIPPED (not in DB)
  P/E < Industry PE    -- SKIPPED (no industry classification)
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

# Load all reference data
print("Loading data...")

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
        'year': year,
        'sales': float(sales) if sales else None,
        'net_profit': float(np_) if np_ else None,
        'eps': float(eps) if eps else None,
        'roe': roe, 'de': de,
        'roce': float(roce) if roce else None,
        'opm': float(opm) if opm else None,
    })

cur.execute("""
    SELECT symbol, quarter_end_date, promoter_pct
    FROM promoter_holdings WHERE promoter_pct IS NOT NULL
""")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})

cur.execute("""
    SELECT symbol, date, close_price FROM prices
    WHERE close_price IS NOT NULL ORDER BY symbol, date
""")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))

cur.execute("""
    SELECT DISTINCT symbol FROM model3_training_data
    WHERE in_forward_test = TRUE
""")
universe = [row[0] for row in cur.fetchall()]
print(f"  Universe: {len(universe)} symbols")

cur.close()

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_price_on(symbol, target_date, window=15):
    if symbol not in prices:
        return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end:
            return p
    return None

def get_fin(symbol, year):
    rows = [r for r in financials.get(symbol, []) if r['year'] == year]
    return rows[0] if rows else None

def get_fin_year(symbol, rebal_date):
    """Get most recent completed fiscal year before rebalance date."""
    cutoff = rebal_date.year - (0 if rebal_date.month >= 4 else 1)
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)
    return rows[0] if rows else None

def get_promoter_pct(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, [])
                   if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)
    return rows[0]['pct'] if rows else None

def apply_screen(symbol, rebal_date):
    """Returns (passes, reason_failed) tuple."""
    f0 = get_fin_year(symbol, rebal_date)
    if not f0:
        return False, 'no_financials'

    yr = f0['year']
    f1 = get_fin(symbol, yr - 1)  # prior year
    f3 = get_fin(symbol, yr - 3)  # 3 years ago

    # ROE > 20
    if f0['roe'] is None or f0['roe'] <= 20:
        return False, f"ROE={f0['roe']:.1f}" if f0['roe'] else 'ROE=None'

    # OPM > 10
    if f0['opm'] is None or f0['opm'] <= 10:
        return False, f"OPM={f0['opm']:.1f}" if f0['opm'] else 'OPM=None'

    # ROCE > 20
    if f0['roce'] is None or f0['roce'] <= 20:
        return False, f"ROCE={f0['roce']:.1f}" if f0['roce'] else 'ROCE=None'

    # D/E < 0.9
    if f0['de'] is None or f0['de'] >= 0.9:
        return False, f"DE={f0['de']:.2f}" if f0['de'] is not None else 'DE=None'

    # Sales growth 1yr > 1%
    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0:
        return False, 'no_sales_1yr'
    sg1 = (f0['sales'] - f1['sales']) / f1['sales'] * 100
    if sg1 <= 1:
        return False, f"SalesG1yr={sg1:.1f}%"

    # Profit growth 1yr > 1%
    if not f1 or not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0:
        return False, 'no_profit_1yr'
    pg1 = (f0['net_profit'] - f1['net_profit']) / f1['net_profit'] * 100
    if pg1 <= 1:
        return False, f"ProfitG1yr={pg1:.1f}%"

    # Sales growth 3yr > 20% CAGR
    if f3 and f3['sales'] and f3['sales'] > 0:
        sg3 = (f0['sales']/f3['sales'])**(1/3) - 1
        if sg3 * 100 <= 20:
            return False, f"SalesG3yr={sg3*100:.1f}%"
    else:
        return False, 'no_sales_3yr'

    # Profit growth 3yr > 25% CAGR
    if f3 and f3['net_profit'] and f3['net_profit'] > 0:
        pg3 = (f0['net_profit']/f3['net_profit'])**(1/3) - 1
        if pg3 * 100 <= 25:
            return False, f"ProfitG3yr={pg3*100:.1f}%"
    else:
        return False, 'no_profit_3yr'

    # Promoter holding > 25%
    prom = get_promoter_pct(symbol, rebal_date)
    if prom is None or prom <= 25:
        return False, f"Promoter={prom:.1f}%" if prom else 'Promoter=None'

    # P/E < 30
    price = get_price_on(symbol, rebal_date, window=10)
    eps = f0['eps']
    if price and eps and eps > 0:
        pe = price / eps
        if pe >= 30:
            return False, f"PE={pe:.1f}"
    else:
        return False, 'no_PE'

    # PEG < 1 (use 1yr profit growth as EPS growth proxy)
    if price and eps and eps > 0 and f1 and f1['eps'] and f1['eps'] > 0:
        pe = price / eps
        eps_growth = (eps - f1['eps']) / f1['eps'] * 100
        if eps_growth > 0:
            peg = pe / eps_growth
            if peg >= 1:
                return False, f"PEG={peg:.2f}"

    return True, 'passed'

# ── Run screen on each forward test date ──────────────────────────────────────
forward_dates = [
    date(2024, 6, 1),
    date(2024, 12, 1),
    date(2025, 6, 1),
    date(2025, 12, 1),
]

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

print("\n" + "═"*65)
print("  SCREENER.IN SCREEN vs MODEL 3 — FORWARD TEST COMPARISON")
print("═"*65)

screen_returns_all = []
model_returns_all  = []

for rebal_date in forward_dates:
    # ── Screener screen picks ─────────────────────────────────────────────────
    passed = []
    for symbol in universe:
        ok, reason = apply_screen(symbol, rebal_date)
        if ok:
            passed.append(symbol)

    # Calculate returns for screen picks
    rd = pd.Timestamp(rebal_date)
    next_date = date(rd.year, 12, 1) if rd.month == 6 else date(rd.year+1, 6, 1)

    screen_rets = []
    for symbol in passed:
        p0 = get_price_on(symbol, rebal_date)
        p1 = get_price_on(symbol, next_date)
        if p0 and p1 and p0 > 0:
            screen_rets.append((p1-p0)/p0)

    screen_port = float(np.mean(screen_rets)) if screen_rets else None

    # ── Model 3 picks ─────────────────────────────────────────────────────────
    period_df = df[df['rebalance_date'] == rebal_date].copy()
    period_df['score'] = model.predict(period_df[FEATURES])
    excluded, _ = get_exclusions(gov_conn, rebal_date)
    period_df = period_df[~period_df['symbol'].isin(excluded)]
    top10 = period_df.nlargest(10, 'score')

    model_rets = []
    for _, row in top10.iterrows():
        p0 = get_price_on(row['symbol'], rebal_date)
        p1 = get_price_on(row['symbol'], next_date)
        if p0 and p1 and p0 > 0:
            model_rets.append((p1-p0)/p0)

    model_port = float(np.mean(model_rets)) if model_rets else None

    if screen_port is not None:
        screen_returns_all.append(screen_port)
    if model_port is not None:
        model_returns_all.append(model_port)

    # ── Overlap analysis ──────────────────────────────────────────────────────
    model_symbols = set(top10['symbol'].tolist())
    screen_symbols = set(passed)
    overlap = model_symbols & screen_symbols
    only_screen = screen_symbols - model_symbols
    only_model  = model_symbols - screen_symbols

    print(f"\n{'─'*65}")
    print(f"  {rebal_date}")
    print(f"  Screen picks: {len(passed)} stocks | Model picks: 10 stocks")
    s_str = f"{screen_port*100:.1f}%" if screen_port else "N/A"
    m_str = f"{model_port*100:.1f}%" if model_port else "N/A"
    print(f"  Screen return: {s_str}  |  Model return: {m_str}")
    print(f"  Overlap (in both): {sorted(overlap) if overlap else 'none'}")
    print(f"\n  Screen-only top picks (not in model):")
    # Show screen-only picks with returns
    screen_only_rets = []
    for sym in sorted(only_screen)[:8]:
        p0 = get_price_on(sym, rebal_date)
        p1 = get_price_on(sym, next_date)
        if p0 and p1 and p0 > 0:
            ret = (p1-p0)/p0*100
            screen_only_rets.append((sym, ret))
    screen_only_rets.sort(key=lambda x: x[1], reverse=True)
    for sym, ret in screen_only_rets[:8]:
        print(f"    {sym:<15} {ret:>8.1f}%")

    print(f"\n  Model-only picks (not in screen):")
    for _, row in top10.iterrows():
        if row['symbol'] in only_model:
            p0 = get_price_on(row['symbol'], rebal_date)
            p1 = get_price_on(row['symbol'], next_date)
            ret_str = f"{(p1-p0)/p0*100:.1f}%" if p0 and p1 and p0>0 else "N/A"
            print(f"    {row['symbol']:<15} score={row['score']:.3f}  actual={ret_str}")

gov_conn.close()

# ── Overall summary ───────────────────────────────────────────────────────────
print(f"\n{'═'*65}")
print(f"  OVERALL SUMMARY (4 forward test periods)")
print(f"{'═'*65}")
if screen_returns_all:
    s_total = float((pd.Series(screen_returns_all)+1).prod())
    s_cagr  = s_total**(1/2) - 1
    print(f"  Screener screen:  avg={np.mean(screen_returns_all)*100:.1f}%  CAGR={s_cagr*100:.1f}%")
if model_returns_all:
    m_total = float((pd.Series(model_returns_all)+1).prod())
    m_cagr  = m_total**(1/2) - 1
    print(f"  Model 3 (RF):     avg={np.mean(model_returns_all)*100:.1f}%  CAGR={m_cagr*100:.1f}%")
print(f"{'═'*65}")
conn.close()
