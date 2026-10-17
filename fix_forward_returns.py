"""
fix_forward_returns.py
Recomputes missing forward returns for all training dates.
For delisted stocks: uses last available price as exit price.
Fresh connection per date to avoid timeout.
"""

import os
import psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

# Load all prices once into memory
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
print('Loading prices...')
cur.execute('SELECT symbol, date, close_price FROM prices WHERE close_price IS NOT NULL ORDER BY symbol, date')
prices = {}
for symbol, d, price in cur.fetchall():
    prices.setdefault(symbol, []).append((d, float(price)))
print(f'Loaded {len(prices)} symbols')

cur.execute("""
    SELECT DISTINCT rebalance_date FROM model3_training_data
    WHERE forward_6m_return IS NULL
    ORDER BY rebalance_date
""")
all_dates = [row[0] for row in cur.fetchall()]
cur.close()
conn.close()
print(f'Dates with missing forward returns: {len(all_dates)}')

def get_price_on(symbol, target_date, window=15):
    if symbol not in prices: return None
    end = target_date + timedelta(days=window)
    for d, p in prices[symbol]:
        if target_date <= d <= end:
            return p
    return None

def get_last_price_before(symbol, before_date):
    """Last available price before given date — for delisted stocks."""
    if symbol not in prices: return None
    past = [(d, p) for d, p in prices[symbol] if d <= before_date]
    return past[-1][1] if past else None

for rebal_date in all_dates:
    if rebal_date.month == 6:
        fwd_date = date(rebal_date.year, 12, 1)
    else:
        fwd_date = date(rebal_date.year + 1, 6, 1)

    if fwd_date > date.today():
        print(f'  {rebal_date} → {fwd_date}: future — skipping')
        continue

    # Fresh connection per date
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()

    cur.execute("""
        SELECT symbol FROM model3_training_data
        WHERE rebalance_date = %s AND forward_6m_return IS NULL
    """, (rebal_date,))
    symbols = [row[0] for row in cur.fetchall()]

    updated = 0
    used_last = 0

    for symbol in symbols:
        p0 = get_price_on(symbol, rebal_date, window=10)
        if not p0:
            continue

        p1 = get_price_on(symbol, fwd_date, window=15)
        if p1:
            fwd_ret = round((p1 - p0) / p0, 4)
        else:
            # Delisted/suspended — use last available price
            p1_last = get_last_price_before(symbol, fwd_date)
            if p1_last:
                fwd_ret = round((p1_last - p0) / p0, 4)
                used_last += 1
            else:
                continue

        cur.execute("""
            UPDATE model3_training_data
            SET forward_6m_return = %s
            WHERE rebalance_date = %s AND symbol = %s
        """, (fwd_ret, rebal_date, symbol))
        updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f'  {rebal_date} → {fwd_date}: updated={updated}/{len(symbols)} (last_price_used={used_last})')

# Final summary with fresh connection
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
print('\nFinal coverage:')
cur.execute("""
    SELECT rebalance_date,
           COUNT(*) as total,
           COUNT(forward_6m_return) as has_fwd,
           ROUND(100.0*COUNT(forward_6m_return)/COUNT(*),0) as pct
    FROM model3_training_data
    GROUP BY rebalance_date
    ORDER BY rebalance_date
""")
for row in cur.fetchall():
    status = '✓' if row[3] >= 80 else '⚠'
    print(f'  {row[0]}: {row[2]}/{row[1]} ({row[3]}%) {status}')
cur.close()
conn.close()
print('\n✓ Done')
