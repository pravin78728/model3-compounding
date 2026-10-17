import os, psycopg2, pandas as pd, pickle, shutil, time
from dotenv import load_dotenv
from psycopg2.extras import execute_values
load_dotenv()

df = pd.read_csv('model3_training_data_checkpoint_238.csv')
print(f'Checkpoint CSV rows: {len(df)}')

# Delete in small batches to avoid timeout
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# Get all rebalance dates and delete one at a time
cur.execute("SELECT DISTINCT rebalance_date FROM model3_training_data ORDER BY rebalance_date")
dates = [row[0] for row in cur.fetchall()]
print(f'Deleting {len(dates)} rebalance dates...')

for rd in dates:
    cur.execute("DELETE FROM model3_training_data WHERE rebalance_date = %s", (rd,))
    conn.commit()
    print(f'  Deleted {rd}')
    time.sleep(0.2)

# Drop new columns if exist
try:
    cur.execute('ALTER TABLE model3_training_data DROP COLUMN IF EXISTS s_fii_trend')
    cur.execute('ALTER TABLE model3_training_data DROP COLUMN IF EXISTS s_dii_trend')
    conn.commit()
    print('Dropped new columns')
except Exception as e:
    print(f'Column drop: {e}')
    conn.rollback()

# Re-insert from checkpoint
cols = ['symbol','rebalance_date','s1_roe_trend','s2_revenue_cagr','s3_fcf',
        's4_pli_tailwind','s7_tam_expansion','s5_promoter_trend','s6_earnings_consist',
        's8_peg_ratio','s9_dii_accumulation','s10_de_improvement','s11_roce',
        's12_eps_cagr','s14_macro_cycle','s15_rs_12m','composite_score',
        'forward_6m_return','in_train','in_validate','in_forward_test']

batch = []
for _, row in df.iterrows():
    batch.append(tuple(None if pd.isna(row[c]) else row[c] for c in cols))
    if len(batch) == 500:
        execute_values(cur, f"INSERT INTO model3_training_data ({','.join(cols)}) VALUES %s", batch)
        conn.commit()
        batch = []
if batch:
    execute_values(cur, f"INSERT INTO model3_training_data ({','.join(cols)}) VALUES %s", batch)
    conn.commit()

cur.execute('SELECT COUNT(*) FROM model3_training_data')
print(f'Restored {cur.fetchone()[0]} rows')

shutil.copy('model3_rf_checkpoint_238.pkl', 'model3_rf.pkl')
print('✓ Model restored')
cur.close()
conn.close()
