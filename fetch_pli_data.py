import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

cur.execute('''
    CREATE TABLE IF NOT EXISTS pli_beneficiaries (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        company_name TEXT,
        pli_sector TEXT NOT NULL,
        approval_year INT,
        incentive_period_years INT,
        estimated_incentive_cr NUMERIC,
        active BOOLEAN DEFAULT TRUE,
        notes TEXT,
        CONSTRAINT pli_unique UNIQUE (symbol, pli_sector)
    );
''')

pli_data = [
    ('DIXON',     'Dixon Technologies',         'Electronics',      2021, 5, 2800,  True, 'Large scale electronics PLI'),
    ('AMBER',     'Amber Enterprises',          'White Goods',       2021, 5, 1500,  True, 'AC components PLI'),
    ('HAVELLS',   'Havells India',              'White Goods',       2021, 5, 800,   True, 'White goods PLI'),
    ('VGUARD',    'V-Guard Industries',         'White Goods',       2021, 5, 400,   True, 'White goods PLI'),
    ('KAYNES',    'Kaynes Technology',          'Electronics',      2022, 5, 1200,  True, 'Electronics PLI'),
    ('SYRMA',     'Syrma SGS Technology',       'Electronics',      2022, 5, 600,   True, 'Electronics PLI'),
    ('SUNPHARMA', 'Sun Pharmaceutical',         'Pharma',           2021, 6, 3500,  True, 'API and formulations PLI'),
    ('DRREDDY',   'Dr Reddys Laboratories',     'Pharma',           2021, 6, 2800,  True, 'API PLI'),
    ('CIPLA',     'Cipla',                      'Pharma',           2021, 6, 2200,  True, 'Pharma PLI'),
    ('DIVISLAB',  'Divis Laboratories',         'Pharma',           2021, 6, 1800,  True, 'API PLI'),
    ('AUROPHARMA','Aurobindo Pharma',           'Pharma',           2021, 6, 2000,  True, 'API PLI'),
    ('TATAMOTORS','Tata Motors',                'Auto',             2021, 5, 6000,  True, 'Auto PLI incl EV'),
    ('M&M',       'Mahindra & Mahindra',        'Auto',             2021, 5, 4800,  True, 'Auto PLI incl EV'),
    ('MARUTI',    'Maruti Suzuki',              'Auto',             2021, 5, 3500,  True, 'Auto PLI'),
    ('BOSCHLTD',  'Bosch',                      'Auto Components',  2021, 5, 1200,  True, 'Auto components PLI'),
    ('MOTHERSON', 'Samvardhana Motherson',      'Auto Components',  2021, 5, 1800,  True, 'Auto components PLI'),
    ('PIIND',     'PI Industries',              'Chemicals',        2021, 5, 800,   True, 'Specialty chemicals PLI'),
    ('DEEPAKNTR', 'Deepak Nitrite',             'Chemicals',        2021, 5, 600,   True, 'Chemicals PLI'),
    ('AARTIIND',  'Aarti Industries',           'Chemicals',        2021, 5, 700,   True, 'Chemicals PLI'),
    ('BRITANNIA', 'Britannia Industries',       'Food Processing',  2021, 6, 800,   True, 'Food processing PLI'),
    ('TATACONSUM','Tata Consumer Products',     'Food Processing',  2021, 6, 600,   True, 'Food processing PLI'),
    ('HFCL',      'HFCL',                       'Telecom',          2021, 5, 400,   True, 'Telecom & networking PLI'),
    ('ADANIGREEN','Adani Green Energy',         'Solar',            2022, 5, 4500,  True, 'Solar module PLI'),
    ('WAAREEENER','Waaree Energies',            'Solar',            2022, 5, 3200,  True, 'Solar PLI - top beneficiary'),
    ('JSWSTEEL',  'JSW Steel',                  'Steel',            2021, 5, 6000,  True, 'Specialty steel PLI'),
    ('SAIL',      'Steel Authority of India',   'Steel',            2021, 5, 4000,  True, 'Specialty steel PLI'),
    ('TATASTEEL', 'Tata Steel',                 'Steel',            2021, 5, 5000,  True, 'Specialty steel PLI'),
    ('HAL',       'Hindustan Aeronautics',      'Defence',          2022, 7, 8000,  True, 'Defence PLI'),
    ('BEL',       'Bharat Electronics',         'Defence',          2022, 7, 3000,  True, 'Defence PLI'),
    ('COCHINSHIP','Cochin Shipyard',            'Defence',          2022, 7, 1500,  True, 'Shipbuilding PLI'),
    ('MAZDOCK',   'Mazagon Dock',               'Defence',          2022, 7, 2000,  True, 'Shipbuilding PLI'),
    ('TATACHEM',  'Tata Chemicals',             'Battery',          2022, 5, 2000,  True, 'ACC battery PLI'),
    ('EXIDEIND',  'Exide Industries',           'Battery',          2022, 5, 1500,  True, 'ACC battery PLI'),
]

execute_values(cur, """
    INSERT INTO pli_beneficiaries
        (symbol, company_name, pli_sector, approval_year, incentive_period_years,
         estimated_incentive_cr, active, notes)
    VALUES %s
    ON CONFLICT (symbol, pli_sector) DO UPDATE SET
        company_name = EXCLUDED.company_name,
        approval_year = EXCLUDED.approval_year,
        incentive_period_years = EXCLUDED.incentive_period_years,
        estimated_incentive_cr = EXCLUDED.estimated_incentive_cr,
        active = EXCLUDED.active,
        notes = EXCLUDED.notes
""", pli_data)

conn.commit()
print(f"PLI rows upserted: {cur.rowcount}")

cur.execute("SELECT pli_sector, COUNT(*) as cos FROM pli_beneficiaries GROUP BY pli_sector ORDER BY cos DESC;")
for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
print("Done.")
