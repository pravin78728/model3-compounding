"""
data_audit.py
Comprehensive data quality audit for Model 3.
Checks every table, every rebalance date, every critical signal
for completeness, accuracy and consistency.
Produces a clear report of what's good, what's missing, what's wrong.
"""

import os
import psycopg2
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from datetime import date

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

REBALANCE_DATES = [
    date(2014, 6, 1), date(2014, 12, 1),
    date(2015, 6, 1), date(2015, 12, 1),
    date(2016, 6, 1), date(2016, 12, 1),
    date(2017, 6, 1), date(2017, 12, 1),
    date(2018, 6, 1), date(2018, 12, 1),
    date(2019, 6, 1), date(2019, 12, 1),
    date(2020, 6, 1), date(2020, 12, 1),
    date(2021, 6, 1), date(2021, 12, 1),
    date(2022, 6, 1), date(2022, 12, 1),
    date(2023, 6, 1), date(2023, 12, 1),
    date(2024, 6, 1), date(2024, 12, 1),
    date(2025, 6, 1), date(2025, 12, 1),
    date(2026, 6, 1),
]

issues = []
warnings = []

def flag(level, table, issue):
    if level == 'ERROR':
        issues.append(f"[ERROR] {table}: {issue}")
    else:
        warnings.append(f"[WARN]  {table}: {issue}")

print("═"*70)
print("  MODEL 3 DATA AUDIT")
print("═"*70)

# ── 1. PRICES ─────────────────────────────────────────────────────────────────
print("\n── 1. PRICES ──")
cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM prices WHERE close_price IS NOT NULL")
total, symbols, min_d, max_d = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | Range: {min_d} → {max_d}")

# Check index prices exist
for idx_sym in ['NIFTY500_IDX', 'NIFTY50_IDX', 'INDIAVIX_IDX']:
    cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM prices WHERE symbol = %s", (idx_sym,))
    cnt, mn, mx = cur.fetchone()
    if cnt < 1000:
        flag('ERROR', 'prices', f"{idx_sym} has only {cnt} rows — expected 3000+")
    else:
        print(f"  {idx_sym}: {cnt} rows ({mn} → {mx}) ✓")

# Check forward return coverage at each rebalance date
print("\n  Forward return coverage by rebalance date:")
print(f"  {'Date':<14} {'Universe':>9} {'Has_Fwd':>9} {'Coverage':>9} {'Status'}")
for rd in REBALANCE_DATES:
    cur.execute("""
        SELECT COUNT(*), COUNT(forward_6m_return)
        FROM model3_training_data
        WHERE rebalance_date = %s
    """, (rd,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        flag('ERROR', 'model3_training_data', f"{rd}: no rows at all")
        print(f"  {str(rd):<14} {'MISSING':>9}")
        continue
    total_stocks, has_fwd = row
    # Forward date
    if rd.month == 6:
        fwd_date = date(rd.year, 12, 1)
    else:
        fwd_date = date(rd.year+1, 6, 1)
    coverage = has_fwd/total_stocks*100 if total_stocks > 0 else 0
    # Forward date in future = ok to have 0 returns
    is_future = fwd_date > date.today()
    status = '✓' if (coverage > 80 or is_future) else '✗ LOW'
    if coverage < 50 and not is_future:
        flag('ERROR', 'model3_training_data', f"{rd}: only {coverage:.0f}% forward returns — prices missing for forward date {fwd_date}")
    print(f"  {str(rd):<14} {total_stocks:>9} {has_fwd:>9} {coverage:>8.0f}% {status}")

# ── 2. FINANCIALS ─────────────────────────────────────────────────────────────
print("\n── 2. FINANCIALS ──")
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(year), MAX(year)
    FROM financials
""")
total, symbols, min_yr, max_yr = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | Years: {min_yr}–{max_yr}")

# Symbols with fewer than 3 years of data
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT symbol FROM financials
        GROUP BY symbol HAVING COUNT(*) < 3
    ) t
""")
thin = cur.fetchone()[0]
if thin > 50:
    flag('WARN', 'financials', f"{thin} symbols have fewer than 3 years of data")
print(f"  Symbols with <3 years: {thin}")

# Check key columns for nulls
for col in ['sales', 'net_profit', 'roce_pct', 'opm_pct']:
    cur.execute(f"SELECT COUNT(*) FROM financials WHERE {col} IS NULL")
    nulls = cur.fetchone()[0]
    pct = nulls/total*100
    if pct > 30:
        flag('WARN', 'financials', f"{col} is NULL in {pct:.0f}% of rows")
    print(f"  {col} null: {nulls:,} ({pct:.0f}%)")

# ── 3. QUARTERLY FINANCIALS ───────────────────────────────────────────────────
print("\n── 3. QUARTERLY FINANCIALS ──")
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol),
           MIN(quarter), MAX(quarter)
    FROM quarterly_financials
""")
total, symbols, min_q, max_q = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | Range: {min_q} → {max_q}")

cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT symbol FROM quarterly_financials
        GROUP BY symbol HAVING COUNT(*) < 8
    ) t
""")
thin = cur.fetchone()[0]
if thin > 200:
    flag('WARN', 'quarterly_financials', f"{thin} symbols have fewer than 8 quarters")
print(f"  Symbols with <8 quarters: {thin}")

# ── 4. CASHFLOW ───────────────────────────────────────────────────────────────
print("\n── 4. CASHFLOW ──")
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(year), MAX(year),
           COUNT(free_cash_flow)
    FROM cashflow
""")
total, symbols, min_yr, max_yr, has_fcf = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | FCF populated: {has_fcf:,}")
if has_fcf < total * 0.7:
    flag('WARN', 'cashflow', f"free_cash_flow only {has_fcf/total*100:.0f}% populated")

# ── 5. PROMOTER HOLDINGS ──────────────────────────────────────────────────────
print("\n── 5. PROMOTER HOLDINGS ──")
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol),
           MIN(quarter_end_date), MAX(quarter_end_date)
    FROM promoter_holdings
""")
total, symbols, min_d, max_d = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | Range: {min_d} → {max_d}")
if min_d > date(2016, 1, 1):
    flag('WARN', 'promoter_holdings', f"History only from {min_d} — pre-2016 data missing (known source limit)")

# Coverage at each rebalance date
print("  Coverage at key training dates:")
for rd in [date(2016,6,1), date(2018,6,1), date(2020,6,1), date(2022,6,1), date(2024,6,1)]:
    cur.execute("""
        SELECT COUNT(DISTINCT symbol) FROM promoter_holdings
        WHERE quarter_end_date <= %s
    """, (rd,))
    cnt = cur.fetchone()[0]
    print(f"    {rd}: {cnt} symbols with promoter data")

# ── 6. INSTITUTIONAL HOLDINGS ─────────────────────────────────────────────────
print("\n── 6. INSTITUTIONAL HOLDINGS ──")
cur.execute("""
    SELECT COUNT(*), COUNT(DISTINCT symbol),
           MIN(period), MAX(period),
           COUNT(dii_pct), COUNT(fii_pct), COUNT(pledge_pct)
    FROM institutional_holdings
""")
total, symbols, min_d, max_d, dii, fii, pledge = cur.fetchone()
print(f"  Total rows: {total:,} | Symbols: {symbols} | Range: {min_d} → {max_d}")
print(f"  DII populated: {dii:,} | FII populated: {fii:,} | Pledge: {pledge:,}")
if pledge == 0:
    flag('WARN', 'institutional_holdings', "pledge_pct is entirely empty — paid source needed")
if min_d > date(2018, 1, 1):
    flag('WARN', 'institutional_holdings', f"DII history only from {min_d} — pre-2018 missing (known source limit)")

# ── 7. SIGNAL COVERAGE IN TRAINING DATA ───────────────────────────────────────
print("\n── 7. SIGNAL COVERAGE IN model3_training_data ──")
signals = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's8_peg_ratio',
    's9_dii_accumulation', 's10_de_improvement', 's11_roce',
    's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

for period, flag_col in [('Train', 'in_train'), ('Validate', 'in_validate'), ('Forward', 'in_forward_test')]:
    cur.execute(f"SELECT COUNT(*) FROM model3_training_data WHERE {flag_col} = TRUE")
    total = cur.fetchone()[0]
    if total == 0:
        continue
    print(f"\n  {period} period ({total} rows):")
    for sig in signals:
        cur.execute(f"""
            SELECT COUNT({sig}), ROUND(100.0*COUNT({sig})/COUNT(*), 1)
            FROM model3_training_data WHERE {flag_col} = TRUE
        """)
        cnt, pct = cur.fetchone()
        status = '✓' if pct >= 50 else ('⚠' if pct >= 20 else '✗')
        if pct < 20 and sig not in ('s4_pli_tailwind', 's5_promoter_trend', 's9_dii_accumulation'):
            flag('ERROR', 'model3_training_data', f"{sig} only {pct}% coverage in {period}")
        print(f"    {sig:<25} {pct:>5}% {status}")

# ── 8. PRICES FOR ALL REBALANCE + FORWARD DATES ───────────────────────────────
print("\n── 8. PRICE AVAILABILITY AT KEY DATES ──")
print(f"  {'Date':<14} {'Forward':<14} {'Symbols_w_price':>16} {'Symbols_w_fwd':>14}")

for rd in REBALANCE_DATES:
    if rd.month == 6:
        fwd = date(rd.year, 12, 1)
    else:
        fwd = date(rd.year+1, 6, 1)

    cur.execute("""
        SELECT COUNT(DISTINCT symbol) FROM prices
        WHERE date BETWEEN %s AND %s
    """, (rd, rd + pd.Timedelta(days=15)))
    has_start = cur.fetchone()[0]

    if fwd <= date.today():
        cur.execute("""
            SELECT COUNT(DISTINCT symbol) FROM prices
            WHERE date BETWEEN %s AND %s
        """, (fwd, fwd + pd.Timedelta(days=15)))
        has_fwd = cur.fetchone()[0]
        if has_fwd < 400:
            flag('ERROR', 'prices', f"Only {has_fwd} symbols have prices at forward date {fwd}")
    else:
        has_fwd = 'future'

    print(f"  {str(rd):<14} {str(fwd):<14} {has_start:>16} {str(has_fwd):>14}")

# ── 9. INDEX MEMBERSHIP COVERAGE ──────────────────────────────────────────────
print("\n── 9. INDEX MEMBERSHIP COVERAGE ──")
for rd in [date(2014,6,1), date(2016,6,1), date(2018,6,1),
           date(2020,6,1), date(2022,6,1), date(2024,6,1)]:
    cur.execute("""
        SELECT COUNT(DISTINCT symbol) FROM index_membership
        WHERE index_name = 'Nifty 500'
        AND valid_from <= %s AND (valid_to >= %s OR valid_to IS NULL)
    """, (rd, rd))
    cnt = cur.fetchone()[0]
    status = '✓' if cnt >= 400 else '✗ LOW'
    if cnt < 400:
        flag('WARN', 'index_membership', f"Only {cnt} symbols in Nifty 500 at {rd}")
    print(f"  {rd}: {cnt} symbols {status}")

# ── 10. MACRO INDICATORS ──────────────────────────────────────────────────────
print("\n── 10. MACRO INDICATORS ──")
cur.execute("""
    SELECT indicator, COUNT(*), MIN(date), MAX(date)
    FROM macro_indicators GROUP BY indicator
""")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} entries ({row[2]} → {row[3]})")

# ── 11. INDUSTRY CLASSIFICATION ───────────────────────────────────────────────
print("\n── 11. INDUSTRY CLASSIFICATION ──")
cur.execute("""
    SELECT COUNT(*), COUNT(industry), COUNT(industry_median_pe)
    FROM industry_classification
""")
total, has_ind, has_pe = cur.fetchone()
print(f"  Total: {total} | With industry: {has_ind} | With median PE: {has_pe}")
if has_ind < 800:
    flag('WARN', 'industry_classification', f"Only {has_ind} symbols classified — {951-has_ind} missing")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n" + "═"*70)
print("  AUDIT SUMMARY")
print("═"*70)

if issues:
    print(f"\n  ERRORS ({len(issues)}) — must fix before retraining:")
    for issue in issues:
        print(f"    {issue}")
else:
    print("\n  No errors found ✓")

if warnings:
    print(f"\n  WARNINGS ({len(warnings)}) — known limits or soft issues:")
    for w in warnings:
        print(f"    {w}")

print("\n" + "═"*70)
cur.close()
conn.close()
