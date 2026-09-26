"""
build_compounder_features.py - Compounder model signals, no momentum
Loads prices in yearly batches to avoid Supabase timeout.
"""

import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

def get_conn():
    return psycopg2.connect(os.environ['DATABASE_URL'])

conn = get_conn()
cur = conn.cursor()

# Create table
cur.execute("DROP TABLE IF EXISTS model3_training_data")
cur.execute("""
CREATE TABLE model3_training_data (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT,
    rebalance_date      DATE,
    c1_eps_cagr         NUMERIC,
    c2_eps_accel        NUMERIC,
    c3_roe_quality      NUMERIC,
    c4_fcf_quality      NUMERIC,
    c5_rev_cagr         NUMERIC,
    c6_margin_expan     NUMERIC,
    c7_roce_trend       NUMERIC,
    c8_earn_consist     NUMERIC,
    c9_de_improve       NUMERIC,
    c10_peg             NUMERIC,
    c11_promoter        NUMERIC,
    c12_macro           NUMERIC,
    c13_pli             NUMERIC,
    composite_score     NUMERIC,
    forward_6m_return   NUMERIC,
    in_train            BOOLEAN,
    in_validate         BOOLEAN,
    in_forward_test     BOOLEAN
)""")
conn.commit()
print("✓ Table created")

print("Loading reference data...")
cur.execute("SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials")
financials = {}
for symbol, year, sales, np_, eps, borr, eq, res, roce, opm in cur.fetchall():
    equity = float(eq or 0) + float(res or 0)
    roe = float(np_)/equity*100 if (np_ and equity > 0) else None
    de  = float(borr)/equity if (borr is not None and equity > 0) else None
    financials.setdefault(symbol, []).append({
        'year': year, 'sales': float(sales) if sales else None,
        'net_profit': float(np_) if np_ else None,
        'eps': float(eps) if eps else None,
        'roe': roe, 'de': de,
        'roce': float(roce) if roce else None,
        'opm': float(opm) if opm else None,
    })
print(f"  ✓ financials: {len(financials)} symbols")

cur.execute("SELECT symbol, year, free_cash_flow FROM cashflow WHERE free_cash_flow IS NOT NULL")
cashflow = {}
for symbol, year, fcf in cur.fetchall():
    cashflow.setdefault(symbol, []).append({'year': year, 'fcf': float(fcf)})
print(f"  ✓ cashflow: {len(cashflow)} symbols")

cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})
print(f"  ✓ promoter: {len(promoter)} symbols")

cur.execute("SELECT symbol FROM pli_beneficiaries WHERE active = TRUE")
pli_symbols = set(row[0] for row in cur.fetchall())

cur.execute("SELECT date, value FROM macro_indicators WHERE indicator = 'repo_rate' AND value IS NOT NULL ORDER BY date")
macro_data = [(d, float(v)) for d, v in cur.fetchall()]

cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name = 'Nifty 500'")
membership_rows = cur.fetchall()
print(f"  ✓ index_membership: {len(membership_rows)} intervals")

# Load prices in yearly batches
print("  Loading prices by year...")
prices = {}
for year in range(2013, 2027):
    try:
        c = get_conn()
        cr = c.cursor()
        cr.execute("""
            SELECT symbol, date, close_price FROM prices
            WHERE close_price IS NOT NULL
            AND date >= %s AND date < %s
            ORDER BY symbol, date
        """, (date(year, 1, 1), date(year+1, 1, 1)))
        rows = cr.fetchall()
        for symbol, d, price in rows:
            prices.setdefault(symbol, []).append((d, float(price)))
        cr.close()
        c.close()
        print(f"    {year}: {len(rows):,} rows")
    except Exception as e:
        print(f"    {year}: error — {e}")
print(f"  ✓ prices: {len(prices)} symbols")
cur.close()
conn.close()
print("✓ All data loaded\n")

# Rebalance dates
rebalance_dates = []
for year in range(2014, 2027):
    rebalance_dates.append(date(year, 6, 1))
    rebalance_dates.append(date(year, 12, 1))
rebalance_dates = [d for d in rebalance_dates if d <= date.today()]

def get_universe(rebal_date):
    seen = set()
    result = []
    for symbol, valid_from, valid_to in membership_rows:
        if symbol not in seen and valid_from <= rebal_date and (valid_to is None or valid_to >= rebal_date):
            seen.add(symbol)
            result.append(symbol)
    return result

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices: return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end: return p
    return None

def get_last_price_before(symbol, before_date):
    if symbol not in prices: return None
    past = [(d, p) for d, p in prices[symbol] if d <= before_date]
    return past[-1][1] if past else None

def get_fin_rows(symbol, cutoff_year, n=6):
    rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff_year],
                  key=lambda x: x['year'], reverse=True)
    return rows[:n]

def c1_eps_cagr(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 4)
    rows = [r for r in rows if r['eps'] is not None and r['eps'] > 0]
    if len(rows) < 2: return None
    latest, oldest = rows[0], rows[-1]
    n = latest['year'] - oldest['year']
    if n <= 0: return None
    cagr = (latest['eps']/oldest['eps'])**(1/n) - 1
    return round(min(100, max(0, 50 + cagr * 167)), 2)

def c2_eps_accel(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 7)
    rows = [r for r in rows if r['eps'] is not None and r['eps'] > 0]
    if len(rows) < 6: return None
    recent = rows[:4]
    if recent[-1]['eps'] <= 0: return None
    cagr_recent = (recent[0]['eps']/recent[-1]['eps'])**(1/3) - 1
    prior = rows[3:]
    if len(prior) < 2 or prior[-1]['eps'] <= 0: return None
    n = prior[0]['year'] - prior[-1]['year']
    if n <= 0: return None
    cagr_prior = (prior[0]['eps']/prior[-1]['eps'])**(1/n) - 1
    acceleration = cagr_recent - cagr_prior
    return round(min(100, max(0, 50 + acceleration * 250)), 2)

def c3_roe_quality(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 5)
    rows = [r for r in rows if r['roe'] is not None]
    if len(rows) < 2: return None
    weights = [5, 4, 3, 2, 1][:len(rows)]
    weighted_roe = sum(r['roe']*w for r, w in zip(rows, weights)) / sum(weights)
    trend = rows[0]['roe'] - rows[-1]['roe']
    return round(min(100, max(0, weighted_roe * 2.5 + trend * 2)), 2)

def c4_fcf_quality(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = sorted([r for r in cashflow.get(symbol, []) if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)[:5]
    if len(rows) < 2: return None
    fcf_vals = [r['fcf'] for r in rows]
    positive_pct = sum(1 for v in fcf_vals if v > 0) / len(fcf_vals)
    fcf_growth = (fcf_vals[0] - fcf_vals[-1]) / abs(fcf_vals[-1]) if fcf_vals[-1] != 0 else 0
    return round(positive_pct * 70 + min(30, max(0, fcf_growth * 30)), 2)

def c5_rev_cagr(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 4)
    rows = [r for r in rows if r['sales'] is not None and r['sales'] > 0]
    if len(rows) < 2: return None
    latest, oldest = rows[0], rows[-1]
    n = latest['year'] - oldest['year']
    if n <= 0: return None
    cagr = (latest['sales']/oldest['sales'])**(1/n) - 1
    return round(min(100, max(0, 50 + cagr * 167)), 2)

def c6_margin_expan(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 4)
    rows = [r for r in rows if r['opm'] is not None]
    if len(rows) < 2: return None
    expansion = rows[0]['opm'] - rows[-1]['opm']
    avg_opm = sum(r['opm'] for r in rows) / len(rows)
    return round(min(100, max(0, avg_opm * 3 + expansion * 5)), 2)

def c7_roce_trend(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 4)
    rows = [r for r in rows if r['roce'] is not None]
    if len(rows) < 1: return None
    avg_roce = sum(r['roce'] for r in rows) / len(rows)
    trend = rows[0]['roce'] - rows[-1]['roce'] if len(rows) >= 2 else 0
    return round(min(100, max(0, avg_roce * 2.5 + trend * 3)), 2)

def c8_earn_consist(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 5)
    rows = [r for r in rows if r['net_profit'] is not None]
    if len(rows) < 2: return None
    positive = sum(1 for r in rows if r['net_profit'] > 0)
    return round(positive / len(rows) * 100, 2)

def c9_de_improve(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 4)
    rows = [r for r in rows if r['de'] is not None]
    if len(rows) < 2: return None
    improvement = rows[-1]['de'] - rows[0]['de']
    avg_de = sum(r['de'] for r in rows) / len(rows)
    return round(min(100, max(0, 80 - avg_de * 30 + improvement * 20)), 2)

def c10_peg(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = get_fin_rows(symbol, cutoff, 3)
    rows = [r for r in rows if r['eps'] is not None and r['eps'] > 0]
    if len(rows) < 2: return None
    price = get_price_on(symbol, rebal_date, window=10)
    if not price: return None
    pe = price / rows[0]['eps']
    eps_growth = (rows[0]['eps']/rows[1]['eps'] - 1) * 100 if rows[1]['eps'] > 0 else None
    if not eps_growth or eps_growth <= 0: return None
    peg = pe / eps_growth
    return round(min(100, max(0, 100 - peg * 33)), 2)

def c11_promoter(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, []) if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)[:4]
    if len(rows) < 2: return None
    trend = rows[0]['pct'] - rows[-1]['pct']
    level = rows[0]['pct']
    return round(min(100, max(0, level * 1.5 + trend * 10)), 2)

def c12_macro(rebal_date):
    past = [(d, v) for d, v in macro_data if d <= rebal_date]
    if len(past) < 2: return 50.0
    r1, r2 = past[-1][1], past[-2][1]
    return 75.0 if r1 < r2 else (25.0 if r1 > r2 else 50.0)

def c13_pli(symbol):
    return 80.0 if symbol in pli_symbols else None

def forward_return(symbol, rebal_date):
    p0 = get_price_on(symbol, rebal_date, window=10)
    if not p0: return None
    future = date(rebal_date.year+(1 if rebal_date.month==6 else 0),
                  12 if rebal_date.month==6 else 6, 1)
    p1 = get_price_on(symbol, future, window=15)
    if p1: return round((p1-p0)/p0, 4)
    p_last = get_last_price_before(symbol, future)
    if p_last: return round((p_last-p0)/p0, 4)
    return None

total_rows = 0
for rebal_date in rebalance_dates:
    universe = get_universe(rebal_date)
    if not universe: continue
    c12 = c12_macro(rebal_date)
    in_train    = rebal_date < date(2020, 1, 1)
    in_validate = date(2020, 1, 1) <= rebal_date < date(2024, 1, 1)
    in_fwd      = rebal_date >= date(2024, 1, 1)

    batch = []
    for symbol in universe:
        try:
            sig = [
                c1_eps_cagr(symbol, rebal_date),
                c2_eps_accel(symbol, rebal_date),
                c3_roe_quality(symbol, rebal_date),
                c4_fcf_quality(symbol, rebal_date),
                c5_rev_cagr(symbol, rebal_date),
                c6_margin_expan(symbol, rebal_date),
                c7_roce_trend(symbol, rebal_date),
                c8_earn_consist(symbol, rebal_date),
                c9_de_improve(symbol, rebal_date),
                c10_peg(symbol, rebal_date),
                c11_promoter(symbol, rebal_date),
                c12,
                c13_pli(symbol),
            ]
            fwd = forward_return(symbol, rebal_date)
            available = [x for x in sig if x is not None]
            composite = round(sum(available)/len(available), 2) if available else None
            batch.append((symbol, rebal_date,
                          sig[0], sig[1], sig[2], sig[3], sig[4], sig[5],
                          sig[6], sig[7], sig[8], sig[9], sig[10], sig[11],
                          sig[12], composite, fwd,
                          in_train, in_validate, in_fwd))
        except Exception:
            pass

    if batch:
        conn2 = get_conn()
        cur2 = conn2.cursor()
        execute_values(cur2, """
            INSERT INTO model3_training_data (
                symbol, rebalance_date,
                c1_eps_cagr, c2_eps_accel, c3_roe_quality, c4_fcf_quality,
                c5_rev_cagr, c6_margin_expan, c7_roce_trend, c8_earn_consist,
                c9_de_improve, c10_peg, c11_promoter, c12_macro, c13_pli,
                composite_score, forward_6m_return,
                in_train, in_validate, in_forward_test
            ) VALUES %s
        """, batch)
        conn2.commit()
        cur2.close()
        conn2.close()
        print(f"  ✓ {rebal_date}: {len(batch)} stocks")
        total_rows += len(batch)

print(f"\n✓ Done. {total_rows} total rows")
