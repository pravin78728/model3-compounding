import os, psycopg2, pandas as pd
from dotenv import load_dotenv
from psycopg2.extras import execute_values
load_dotenv()

df = pd.read_csv('model3_training_data_checkpoint_238.csv')
print(f'Loaded {len(df)} rows from checkpoint')

conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

cur.execute("""
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
)
""")
conn.commit()
print('Created table')

cols = ['symbol','rebalance_date','s1_roe_trend','s2_revenue_cagr','s3_fcf',
        's4_pli_tailwind','s7_tam_expansion','s5_promoter_trend','s6_earnings_consist',
        's8_peg_ratio','s9_dii_accumulation','s10_de_improvement','s11_roce',
        's12_eps_cagr','s14_macro_cycle','s15_rs_12m','composite_score',
        'forward_6m_return','in_train','in_validate','in_forward_test']

batch = []
for _, row in df.iterrows():
    batch.append(tuple(None if pd.isna(row[c]) else row[c] for c in cols))
    if len(batch) == 500:
        execute_values(cur, f"""
            INSERT INTO model3_training_data ({','.join(cols)}) VALUES %s
        """, batch)
        conn.commit()
        batch = []

if batch:
    execute_values(cur, f"""
        INSERT INTO model3_training_data ({','.join(cols)}) VALUES %s
    """, batch)
    conn.commit()

cur.execute('SELECT COUNT(*) FROM model3_training_data')
print(f'Restored {cur.fetchone()[0]} rows')
cur.close()
conn.close()
print('✓ Checkpoint restored')
