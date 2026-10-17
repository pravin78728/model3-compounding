import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Create table
cur.execute('''
    CREATE TABLE IF NOT EXISTS macro_indicators (
        id SERIAL PRIMARY KEY,
        indicator TEXT NOT NULL,
        date DATE NOT NULL,
        value NUMERIC,
        notes TEXT,
        CONSTRAINT macro_unique UNIQUE (indicator, date)
    );
''')

# RBI Repo Rate history — MPC decisions only, update after each meeting
# Source: RBI official press releases
repo_rate_history = [
    ('repo_rate', '2010-04-20', 5.25, 'RBI hike'),
    ('repo_rate', '2010-07-02', 5.50, 'RBI hike'),
    ('repo_rate', '2010-09-16', 6.00, 'RBI hike'),
    ('repo_rate', '2010-11-02', 6.25, 'RBI hike'),
    ('repo_rate', '2011-01-25', 6.50, 'RBI hike'),
    ('repo_rate', '2011-03-17', 6.75, 'RBI hike'),
    ('repo_rate', '2011-05-03', 7.25, 'RBI hike'),
    ('repo_rate', '2011-06-16', 7.50, 'RBI hike'),
    ('repo_rate', '2011-07-26', 8.00, 'RBI hike'),
    ('repo_rate', '2011-10-25', 8.50, 'RBI hike'),
    ('repo_rate', '2012-04-17', 8.00, 'RBI cut'),
    ('repo_rate', '2013-05-03', 7.50, 'RBI cut'),
    ('repo_rate', '2013-09-20', 7.50, 'hold'),
    ('repo_rate', '2014-01-28', 8.00, 'RBI hike'),
    ('repo_rate', '2015-01-15', 7.75, 'RBI cut'),
    ('repo_rate', '2015-03-04', 7.50, 'RBI cut'),
    ('repo_rate', '2015-06-02', 7.25, 'RBI cut'),
    ('repo_rate', '2015-09-29', 6.75, 'RBI cut'),
    ('repo_rate', '2016-04-05', 6.50, 'RBI cut'),
    ('repo_rate', '2017-08-02', 6.00, 'RBI cut'),
    ('repo_rate', '2018-06-06', 6.25, 'RBI hike'),
    ('repo_rate', '2018-08-01', 6.50, 'RBI hike'),
    ('repo_rate', '2019-02-07', 6.25, 'RBI cut'),
    ('repo_rate', '2019-04-04', 6.00, 'RBI cut'),
    ('repo_rate', '2019-06-06', 5.75, 'RBI cut'),
    ('repo_rate', '2019-08-07', 5.40, 'RBI cut'),
    ('repo_rate', '2019-10-04', 5.15, 'RBI cut'),
    ('repo_rate', '2020-03-27', 4.40, 'RBI cut - COVID'),
    ('repo_rate', '2020-05-22', 4.00, 'RBI cut - COVID'),
    ('repo_rate', '2022-05-04', 4.40, 'RBI hike'),
    ('repo_rate', '2022-06-08', 4.90, 'RBI hike'),
    ('repo_rate', '2022-08-05', 5.40, 'RBI hike'),
    ('repo_rate', '2022-09-30', 5.90, 'RBI hike'),
    ('repo_rate', '2022-12-07', 6.25, 'RBI hike'),
    ('repo_rate', '2023-02-08', 6.50, 'RBI hike'),
    ('repo_rate', '2025-02-07', 6.25, 'RBI cut - first in 5 years'),
    ('repo_rate', '2025-04-09', 6.00, 'RBI cut'),
    ('repo_rate', '2025-06-06', 5.50, 'RBI cut 50bps'),
    ('repo_rate', '2025-08-06', 5.50, 'RBI hold'),
    ('repo_rate', '2025-12-05', 5.25, 'RBI cut'),
    ('repo_rate', '2026-02-07', 5.25, 'RBI hold'),
]

execute_values(cur, """
    INSERT INTO macro_indicators (indicator, date, value, notes)
    VALUES %s
    ON CONFLICT (indicator, date) DO UPDATE SET
        value = EXCLUDED.value,
        notes = EXCLUDED.notes
""", repo_rate_history)

print(f"Repo rate rows upserted: {cur.rowcount}")

# Rate cycle direction — derived signal
# Cutting cycle = bullish for rate-sensitive sectors
# Hiking cycle = bearish
cycle_data = [
    ('rate_cycle', '2010-04-20', 1,  'hiking'),
    ('rate_cycle', '2012-04-17', -1, 'cutting'),
    ('rate_cycle', '2014-01-28', 1,  'hiking'),
    ('rate_cycle', '2015-01-15', -1, 'cutting'),
    ('rate_cycle', '2018-06-06', 1,  'hiking'),
    ('rate_cycle', '2019-02-07', -1, 'cutting'),
    ('rate_cycle', '2022-05-04', 1,  'hiking'),
    ('rate_cycle', '2025-02-07', -1, 'cutting'),
]

execute_values(cur, """
    INSERT INTO macro_indicators (indicator, date, value, notes)
    VALUES %s
    ON CONFLICT (indicator, date) DO UPDATE SET
        value = EXCLUDED.value,
        notes = EXCLUDED.notes
""", cycle_data)

print(f"Rate cycle rows upserted: {cur.rowcount}")

conn.commit()

# Verify
cur.execute("""
    SELECT indicator, date, value, notes
    FROM macro_indicators
    ORDER BY indicator, date DESC
    LIMIT 10;
""")
print("\nLatest macro data:")
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
print("\nDone.")
