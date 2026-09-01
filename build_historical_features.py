"""
build_historical_features.py  v4 — all column names verified against live schema
"""

import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# ── Create output table ───────────────────────────────────────────────────────
cur.execute("""
DROP TABLE IF EXISTS model3_training_data;
CREATE TABLE model3_training_data (
    id                  SERIAL PRIMARY KEY,
    symbol              TEXT,
    rebalance_date      DATE,
    s1_roe_trend        NUMERIC,
    s2_revenue_cagr     NUMERIC,
    s3_fcf              NUMERIC,
    s4_pli_tailwind     NUMERIC,
s7_tam_expansion    NUMERIC,
    s5_promoter_trend   NUMERIC,
    s6_earnings_consist NUMERIC,
    s8_peg_ratio        NUMERIC,
    s9_dii_accumulation NUMERIC,
    s10_de_improvement  NUMERIC,
    s11_roce            NUMERIC,
    s12_eps_cagr        NUMERIC,
    s14_macro_cycle     NUMERIC,
    s15_rs_12m          NUMERIC,
    composite_score     NUMERIC,
    forward_6m_return   NUMERIC,
    in_train            BOOLEAN,
    in_validate         BOOLEAN,
    in_forward_test     BOOLEAN
);
""")
conn.commit()
print("✓ Created model3_training_data table")

# ── Rebalance dates ───────────────────────────────────────────────────────────
rebalance_dates = []
for year in range(2014, 2025):
    rebalance_dates.append(date(year, 6, 1))
    rebalance_dates.append(date(year, 12, 1))
rebalance_dates = [d for d in rebalance_dates if d <= date.today()]
print(f"✓ {len(rebalance_dates)} rebalance dates: {rebalance_dates[0]} → {rebalance_dates[-1]}")

# ── Bulk load all data into memory ────────────────────────────────────────────
print("Loading reference data into memory...")

# financials — ROE and D/E derived from raw columns
cur.execute("""
    SELECT symbol, year, sales, net_profit, eps,
           borrowings, equity_capital, reserves, roce_pct
    FROM financials
""")
financials = {}
for symbol, year, sales, net_profit, eps, borrowings, eq_cap, reserves, roce in cur.fetchall():
    equity = float(eq_cap or 0) + float(reserves or 0)
    roe = (float(net_profit) / equity * 100) if (net_profit and equity > 0) else None
    de  = (float(borrowings) / equity) if (borrowings is not None and equity > 0) else None
    financials.setdefault(symbol, []).append({
        'year':       year,
        'sales':      float(sales) if sales else None,
        'net_profit': float(net_profit) if net_profit else None,
        'eps':        float(eps) if eps else None,
        'roe':        roe,
        'de':         de,
        'roce':       float(roce) if roce else None,
    })
print(f"  ✓ financials: {len(financials)} symbols")

# cashflow — free_cash_flow column
cur.execute("SELECT symbol, year, free_cash_flow FROM cashflow WHERE free_cash_flow IS NOT NULL")
cashflow = {}
for symbol, year, fcf in cur.fetchall():
    cashflow.setdefault(symbol, []).append({'year': year, 'fcf': float(fcf)})
print(f"  ✓ cashflow: {len(cashflow)} symbols")

# quarterly_financials — quarter is text e.g. "Jun 2019"
MONTH_MAP = {'Mar': 3, 'Jun': 6, 'Sep': 9, 'Dec': 12}
cur.execute("SELECT symbol, quarter, eps FROM quarterly_financials WHERE eps IS NOT NULL")
quarterly = {}
for symbol, quarter, eps in cur.fetchall():
    try:
        parts = quarter.strip().split()
        m = MONTH_MAP.get(parts[0])
        y = int(parts[1])
        if m:
            quarterly.setdefault(symbol, []).append({
                'qend': date(y, m, 1),
                'eps':  float(eps)
            })
    except Exception:
        pass
print(f"  ✓ quarterly_financials: {len(quarterly)} symbols")

# promoter_holdings — date column is quarter_end_date
cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})
print(f"  ✓ promoter_holdings: {len(promoter)} symbols")

# institutional_holdings — date column is period, DII column is dii_pct
cur.execute("SELECT symbol, period, dii_pct FROM institutional_holdings WHERE dii_pct IS NOT NULL")
institutional = {}
for symbol, period, pct in cur.fetchall():
    institutional.setdefault(symbol, []).append({'period': period, 'pct': float(pct)})
print(f"  ✓ institutional_holdings: {len(institutional)} symbols")

# pli_beneficiaries
cur.execute("SELECT symbol FROM pli_beneficiaries WHERE active = TRUE")
pli_symbols = set(row[0] for row in cur.fetchall())
# TAM expansion (S7)
cur.execute("SELECT symbol, s7_score FROM tam_expansion")
tam_scores = {row[0]: float(row[1]) for row in cur.fetchall()}
print(f"  ✓ tam_expansion: {len(tam_scores)} symbols")
print(f"  ✓ pli_beneficiaries: {len(pli_symbols)} symbols")

# macro_indicators — long format, filter by indicator name
cur.execute("""
    SELECT date, value FROM macro_indicators
    WHERE indicator = 'repo_rate' AND value IS NOT NULL
    ORDER BY date
""")
macro_data = [(d, float(v)) for d, v in cur.fetchall()]
print(f"  ✓ macro_indicators: {len(macro_data)} repo rate entries")

# prices
print("  Loading prices (may take 30s)...")
cur.execute("SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date")
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))
print(f"  ✓ prices: {len(prices)} symbols")

# index_membership
cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name = 'Nifty 500'")
membership_rows = cur.fetchall()
print(f"  ✓ index_membership: {len(membership_rows)} intervals")
print("✓ All reference data loaded\n")

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_universe(rebal_date):
    seen = set()
    result = []
    for symbol, valid_from, valid_to in membership_rows:
        if symbol not in seen and valid_from <= rebal_date and (valid_to is None or valid_to >= rebal_date):
            seen.add(symbol)
            result.append(symbol)
    return result

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices:
        return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end:
            return p
    return None

# ── Signal functions ──────────────────────────────────────────────────────────
def s1_roe_trend(symbol, rebal_date):
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= rebal_date.year and r['roe'] is not None],
                  key=lambda x: x['year'], reverse=True)[:4]
    if len(rows) < 2: return None
    roes = [r['roe'] for r in rows]
    score = min(100, max(0, sum(roes)/len(roes) * 2 + (roes[0]-roes[-1]) * 2))
    return round(score, 2)

def s2_revenue_cagr(symbol, rebal_date):
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= rebal_date.year and r['sales'] is not None],
                  key=lambda x: x['year'], reverse=True)[:4]
    if len(rows) < 2: return None
    latest, oldest = rows[0]['sales'], rows[-1]['sales']
    n = rows[0]['year'] - rows[-1]['year']
    if oldest <= 0 or n == 0: return None
    cagr = (latest/oldest)**(1/n) - 1
    return round(min(100, max(0, cagr * 200)), 2)

def s3_fcf(symbol, rebal_date):
    rows = sorted([r for r in cashflow.get(symbol, [])
                   if r['year'] <= rebal_date.year],
                  key=lambda x: x['year'], reverse=True)[:3]
    if not rows: return None
    vals = [r['fcf'] for r in rows]
    pos = sum(1 for v in vals if v > 0)
    score = (pos/len(vals)) * 100
    if len(vals) >= 2 and vals[1] != 0:
        score = min(100, score + (vals[0]-vals[1])/abs(vals[1]) * 20)
    return round(max(0, score), 2)

def s4_pli(symbol):
    return 80.0 if symbol in pli_symbols else None
def s7_tam(symbol):
    score = tam_scores.get(symbol, 0.0)
    return score if score > 0 else None
def s5_promoter_trend(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, [])
                   if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)[:4]
    if len(rows) < 2: return None
    vals = [r['pct'] for r in rows]
    return round(min(100, max(0, 50 + (vals[0]-vals[-1]) * 10)), 2)

def s6_earnings_consistency(symbol, rebal_date):
    # Try quarterly first (last 8 quarters before rebal_date)
    q_rows = sorted([r for r in quarterly.get(symbol, [])
                     if r['qend'] <= rebal_date],
                    key=lambda x: x['qend'], reverse=True)[:8]
    if len(q_rows) >= 4:
        pos = sum(1 for r in q_rows if r['eps'] > 0)
        return round((pos / len(q_rows)) * 100, 2)

    # Fall back to annual EPS consistency from financials table
    a_rows = sorted([r for r in financials.get(symbol, [])
                     if r['year'] <= rebal_date.year and r['net_profit'] is not None],
                    key=lambda x: x['year'], reverse=True)[:5]
    if len(a_rows) < 2: return None
    pos = sum(1 for r in a_rows if r['net_profit'] > 0)
    return round((pos / len(a_rows)) * 100, 2)

def s8_peg(symbol, rebal_date):
    eps_rows = sorted([r for r in financials.get(symbol, [])
                       if r['year'] <= rebal_date.year
                       and r['eps'] is not None and r['eps'] > 0],
                      key=lambda x: x['year'], reverse=True)[:2]
    if len(eps_rows) < 2: return None
    price = get_price_on(symbol, date(eps_rows[0]['year'], 3, 31), window=60)
    if not price: return None
    pe = price / eps_rows[0]['eps']
    growth = (eps_rows[0]['eps'] - eps_rows[1]['eps']) / abs(eps_rows[1]['eps']) * 100
    if growth <= 0: return None
    peg = pe / growth
    return round(min(100, max(0, (2-peg)*50)), 2)

def s9_dii_accumulation(symbol, rebal_date):
    rows = sorted([r for r in institutional.get(symbol, [])
                   if r['period'] <= rebal_date],
                  key=lambda x: x['period'], reverse=True)[:4]
    if len(rows) < 2: return None
    vals = [r['pct'] for r in rows]
    return round(min(100, max(0, 50 + (vals[0]-vals[-1]) * 5)), 2)

def s10_de_improvement(symbol, rebal_date):
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= rebal_date.year and r['de'] is not None],
                  key=lambda x: x['year'], reverse=True)[:3]
    if len(rows) < 2: return None
    vals = [r['de'] for r in rows]
    return round(min(100, max(0, 50 + (vals[-1]-vals[0]) * 20)), 2)

def s11_roce(symbol, rebal_date):
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= rebal_date.year and r['roce'] is not None],
                  key=lambda x: x['year'], reverse=True)[:3]
    if not rows: return None
    avg = sum(r['roce'] for r in rows) / len(rows)
    return round(min(100, max(0, avg * 3)), 2)

def s12_eps_cagr(symbol, rebal_date):
    rows = sorted([r for r in financials.get(symbol, [])
                   if r['year'] <= rebal_date.year
                   and r['eps'] is not None and r['eps'] > 0],
                  key=lambda x: x['year'], reverse=True)[:4]
    if len(rows) < 2: return None
    latest, oldest = rows[0]['eps'], rows[-1]['eps']
    n = rows[0]['year'] - rows[-1]['year']
    if oldest <= 0 or n == 0: return None
    cagr = (latest/oldest)**(1/n) - 1
    return round(min(100, max(0, cagr * 150)), 2)

def s14_macro_cycle(rebal_date):
    past = [(d, v) for d, v in macro_data if d <= rebal_date]
    if len(past) < 2: return 50.0
    r1, r2 = past[-1][1], past[-2][1]
    if r1 < r2: return 75.0
    elif r1 > r2: return 25.0
    return 50.0

def s15_rs_12m(symbol, rebal_date):
    p_end   = get_price_on(symbol, rebal_date, window=10)
    p_start = get_price_on(symbol, rebal_date - timedelta(days=365), window=15)
    if not p_start or not p_end or p_start == 0: return None
    rs = (p_end - p_start) / p_start * 100
    return round(min(100, max(0, 50 + rs * 0.5)), 2)

def forward_return(symbol, rebal_date):
    p_start = get_price_on(symbol, rebal_date, window=10)
    future  = date(rebal_date.year + (1 if rebal_date.month == 6 else 0),
                   12 if rebal_date.month == 6 else 6, 1)
    p_end   = get_price_on(symbol, future, window=15)
    if not p_start or not p_end or p_start == 0: return None
    return round((p_end - p_start) / p_start, 4)

# ── Main loop ─────────────────────────────────────────────────────────────────
total_rows = 0

for rebal_date in rebalance_dates:
    universe = get_universe(rebal_date)
    if not universe:
        print(f"  ⚠ {rebal_date}: no universe found, skipping")
        continue

    s14 = s14_macro_cycle(rebal_date)
    in_train    = rebal_date < date(2020, 1, 1)
    in_validate = date(2020, 1, 1) <= rebal_date < date(2024, 1, 1)
    in_fwd      = rebal_date >= date(2024, 1, 1)

    batch = []
    for symbol in universe:
        try:
            sig = [
                s1_roe_trend(symbol, rebal_date),
                s2_revenue_cagr(symbol, rebal_date),
                s3_fcf(symbol, rebal_date),
                s4_pli(symbol),
s7_tam(symbol),
                s5_promoter_trend(symbol, rebal_date),
                s6_earnings_consistency(symbol, rebal_date),
                s8_peg(symbol, rebal_date),
                s9_dii_accumulation(symbol, rebal_date),
                s10_de_improvement(symbol, rebal_date),
                s11_roce(symbol, rebal_date),
                s12_eps_cagr(symbol, rebal_date),
                s14,
                s15_rs_12m(symbol, rebal_date),
            ]
            fwd = forward_return(symbol, rebal_date)
            available = [x for x in sig if x is not None]
            composite = round(sum(available)/len(available), 2) if available else None
            batch.append((symbol, rebal_date, *sig, composite, fwd,
                          in_train, in_validate, in_fwd))
        except Exception:
            pass

    if batch:
        execute_values(cur, """
            INSERT INTO model3_training_data (
                symbol, rebalance_date,
                s1_roe_trend, s2_revenue_cagr, s3_fcf, s4_pli_tailwind,
               s7_tam_expansion, s5_promoter_trend, s6_earnings_consist, s8_peg_ratio,
                s9_dii_accumulation, s10_de_improvement, s11_roce,
                s12_eps_cagr, s14_macro_cycle, s15_rs_12m,
                composite_score, forward_6m_return,
                in_train, in_validate, in_forward_test
            ) VALUES %s
        """, batch)
        conn.commit()
        print(f"  ✓ {rebal_date}: {len(batch)} stocks | s14={s14} | universe={len(universe)}")
        total_rows += len(batch)

print(f"\n✓ Done. {total_rows} total rows in model3_training_data.")
conn.close()
