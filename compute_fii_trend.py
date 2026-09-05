"""
compute_fii_trend.py
Computes S_FII (FII trend signal) and S_DII (DII trend signal) 
for all symbols at each rebalance date.
Uses point-in-time institutional holdings data.
Score 0-100:
  FII increasing trend = bullish (higher score)
  FII decreasing trend = bearish (lower score)
"""

import os
import psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# Load all institutional holdings into memory
cur.execute("""
    SELECT symbol, period, fii_pct, dii_pct
    FROM institutional_holdings
    WHERE fii_pct IS NOT NULL
    ORDER BY symbol, period
""")
rows = cur.fetchall()

holdings = {}
for symbol, period, fii, dii in rows:
    holdings.setdefault(symbol, []).append({
        'period': period,
        'fii': float(fii) if fii else None,
        'dii': float(dii) if dii else None
    })
print(f'Loaded institutional holdings for {len(holdings)} symbols')

def compute_fii_score(symbol, rebal_date):
    """
    FII trend score at rebal_date using last 4 quarters of data.
    Looks back up to 15 months to get point-in-time data.
    """
    if symbol not in holdings:
        return None, None

    # Get all data available before rebal_date (point-in-time)
    past = sorted([h for h in holdings[symbol]
                   if h['period'] <= rebal_date],
                  key=lambda x: x['period'], reverse=True)

    if len(past) < 2:
        return None, None

    # Use last 4 quarters (1 year trend)
    recent = past[:4]
    latest = recent[0]
    oldest = recent[-1]

    fii_now = latest['fii']
    fii_old = oldest['fii']
    dii_now = latest['dii']
    dii_old = oldest['dii']

    if fii_now is None or fii_old is None:
        return None, None

    # FII change over period
    fii_change = fii_now - fii_old

    # FII score: 50 = neutral, >50 = accumulating, <50 = distributing
    # Cap at reasonable range: +/-5% change maps to 0-100
    fii_score = round(min(100, max(0, 50 + fii_change * 10)), 1)

    # DII score
    if dii_now is not None and dii_old is not None:
        dii_change = dii_now - dii_old
        dii_score = round(min(100, max(0, 50 + dii_change * 10)), 1)
    else:
        dii_score = None

    return fii_score, dii_score

# Test on sample symbols
test_symbols = ['TRENT', 'WAAREEENER', 'MAZDOCK', 'BEL', 'INFY', 'HDFCAMC']
test_date = date(2026, 6, 1)
print(f'\nSample FII/DII scores at {test_date}:')
print(f'{"Symbol":<14} {"FII Score":>10} {"DII Score":>10}')
print('-'*36)
for sym in test_symbols:
    f, d = compute_fii_score(sym, test_date)
    print(f'{sym:<14} {str(f) if f else "N/A":>10} {str(d) if d else "N/A":>10}')

# Check coverage at key rebalance dates
print('\nFII signal coverage at rebalance dates:')
rebal_dates = [
    date(2022,6,1), date(2022,12,1),
    date(2023,6,1), date(2023,12,1),
    date(2024,6,1), date(2024,12,1),
    date(2025,6,1), date(2025,12,1),
    date(2026,6,1),
]

cur.execute("""
    SELECT DISTINCT symbol FROM model3_training_data
    WHERE rebalance_date >= '2022-01-01'
""")
universe = [row[0] for row in cur.fetchall()]

for rd in rebal_dates:
    covered = sum(1 for s in universe
                  if compute_fii_score(s, rd)[0] is not None)
    print(f'  {rd}: {covered}/{len(universe)} ({covered/len(universe)*100:.0f}%)')

cur.close()
conn.close()
print('\n✓ FII trend signal ready to integrate')
