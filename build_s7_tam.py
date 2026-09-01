"""
build_s7_tam.py
Builds S7 TAM expansion signal — structural wave beneficiary tagging.
Three waves:
  1. Formalisation: unorganised→organised (GST, UPI, digital credit)
  2. Capex: PLI, infrastructure, defence, power
  3. Financialisation: savings shifting to financial products

Score = 0 (no wave), 50 (one wave), 80 (two waves), 100 (three waves)
"""

import os
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()

# Create table
cur.execute("""
    CREATE TABLE IF NOT EXISTS tam_expansion (
        id                  SERIAL PRIMARY KEY,
        symbol              TEXT UNIQUE,
        formalisation_wave  BOOLEAN DEFAULT FALSE,
        capex_wave          BOOLEAN DEFAULT FALSE,
        financialisation_wave BOOLEAN DEFAULT FALSE,
        wave_count          INTEGER DEFAULT 0,
        s7_score            NUMERIC DEFAULT 0,
        notes               TEXT
    );
""")
conn.commit()
print("✓ Created tam_expansion table")

# ── Wave definitions by industry ──────────────────────────────────────────────

# Formalisation wave industries — unorganised → organised shift
FORMALISATION_INDUSTRIES = {
    # Consumer shift to branded/organised
    'Computers - Software & Consulting', 'IT Services & Consulting',
    'Household & Personal Products', 'Packaged Foods',
    'Hospitals & Healthcare Services', 'Diagnostics',
    'Pharmaceuticals', 'Retail',
    'Specialty Retail', 'Hotels & Resorts',
    'Restaurants', 'Education',
    'Logistics Solution Provider', 'Courier Services',
    'Specialty Chemicals', 'Agrochemicals',
    'Paints & Coatings', 'Adhesives & Sealants',
    'Footwear', 'Gems, Jewellery & Watches',
    'Textiles', 'Apparel & Accessories',
    'Home Furnishings', 'Consumer Electronics',
    'White Goods', 'Air Conditioner & Refrigerators',
    'Residential, Commercial Projects',
    'Organized Retail', 'Quick Service Restaurant',
    'Diagnostic & Testing Services',     # Additional industries missed in first pass
    'Hospital', 'Hospitals & Clinics',
    'IT Enabled Services', 'Business Process Outsourcing',
    'E-Commerce', 'Online Services',
    'Biotechnology',
    'Diagnostics & Testing Services',
    'Optical', 'Dental',
    'Quick Service Restaurant',
    'Organized Retail',
    'Online Food Delivery',
    'EdTech', 'E-Learning',
}

# Capex wave industries — PLI, infra, defence, power
CAPEX_INDUSTRIES = {
    # Capital goods and construction
    'Heavy Electrical Equipment', 'Industrial Machinery',
    'Engineering', 'Defence', 'Aerospace & Defense',
    'Aerospace & Defence', 'Railways',
    'Civil Construction', 'Infrastructure Developers & Operators',
    'Power Generation', 'Power Transmission & Distribution',
    'Renewable Energy', 'Solar Energy',
    'Electronic Components', 'Semiconductors',
    'Electronic Equipment', 'Cables - Power',
    'Iron & Steel', 'Iron & Steel Products',
    'Aluminum', 'Copper', 'Zinc',
    'Cement & Cement Products',
    'Capital Goods - Electrical Equipment',
    'Capital Goods - Non Electrical Equipment',
    'Shipbuilding', 'Marine',
    'Construction & Engineering',
    'Water Supply & Management',
    'Auto Components & Equipments',
    'Commercial Vehicles',
    'Electric Vehicles',     'Port & Port services',
    'Airport & Airport services',
    'LPG/CNG/PNG/LNG Supplier',
    'Road Assets Toll, Annuity, Hybrid-Annuity',
    'Oil Storage & Transportation',
    'Offshore Support Solution Drilling',
    'Petroleum Products',
    'Gas Distribution',
    'Water Treatment',
    'Dredging',
}

# Financialisation wave industries
FINANCIALISATION_INDUSTRIES = {
    'Private Sector Bank', 'Public Sector Bank',
    'Non Banking Financial Company (NBFC)',
    'Housing Finance Company',
    'Microfinance Institution',
    'Insurance', 'Life Insurance', 'General Insurance',
    'Asset Management Company',
    'Stockbroking & Allied',
    'Wealth Management',
    'Financial Technology (Fintech)',
    'Payment Gateway & Solutions',
    'Credit Rating Agency',
    'Depository & Custody Activities',
    'Holding Company',    'Digital Payments',
    'Financial Technology (Fintech)',
    'Online Broking',
    'Currency Exchange',
    'Credit Information',
}

# PLI beneficiaries get automatic capex wave tag
cur.execute("SELECT DISTINCT symbol FROM pli_beneficiaries WHERE active = TRUE")
pli_symbols = set(row[0] for row in cur.fetchall())
print(f"PLI symbols (auto capex wave): {len(pli_symbols)}")

# Get all symbols with industry classification
cur.execute("""
    SELECT symbol, industry, broad_sector
    FROM industry_classification
    WHERE industry IS NOT NULL
""")
all_stocks = cur.fetchall()
print(f"Classifying {len(all_stocks)} symbols...")

rows = []
for symbol, industry, broad_sector in all_stocks:
    formal = industry in FORMALISATION_INDUSTRIES
    capex  = industry in CAPEX_INDUSTRIES or symbol in pli_symbols
    fin    = industry in FINANCIALISATION_INDUSTRIES

    # Broad sector overrides for cases not caught by industry
    if broad_sector == 'Financial Services':
        fin = True
    if broad_sector == 'Industrials':
        capex = True
    if broad_sector == 'Utilities':
        capex = True
    if broad_sector in ('Consumer Discretionary', 'Fast Moving Consumer Goods'):
        formal = True
    if broad_sector == 'Information Technology':
        formal = True
    if broad_sector == 'Services':
        formal = True
    if broad_sector == 'Healthcare':
        formal = True
    if broad_sector == 'Energy':
        capex = True

    wave_count = sum([formal, capex, fin])
    if wave_count == 0:
        score = 0.0
    elif wave_count == 1:
        score = 50.0
    elif wave_count == 2:
        score = 80.0
    else:
        score = 100.0

    notes = []
    if formal: notes.append('formalisation')
    if capex:  notes.append('capex')
    if fin:    notes.append('financialisation')

    rows.append((
        symbol, formal, capex, fin,
        wave_count, score,
        '+'.join(notes) if notes else 'none'
    ))

execute_values(cur, """
    INSERT INTO tam_expansion
        (symbol, formalisation_wave, capex_wave, financialisation_wave,
         wave_count, s7_score, notes)
    VALUES %s
    ON CONFLICT (symbol) DO UPDATE SET
        formalisation_wave    = EXCLUDED.formalisation_wave,
        capex_wave            = EXCLUDED.capex_wave,
        financialisation_wave = EXCLUDED.financialisation_wave,
        wave_count            = EXCLUDED.wave_count,
        s7_score              = EXCLUDED.s7_score,
        notes                 = EXCLUDED.notes
""", rows)
conn.commit()

# Summary
cur.execute("""
    SELECT wave_count, COUNT(*), ROUND(AVG(s7_score),1)
    FROM tam_expansion
    GROUP BY wave_count ORDER BY wave_count
""")
print("\n=== Wave distribution ===")
for row in cur.fetchall():
    print(f"  {row[0]} waves: {row[1]} stocks (avg score={row[2]})")

cur.execute("""
    SELECT notes, COUNT(*) FROM tam_expansion
    GROUP BY notes ORDER BY COUNT(*) DESC LIMIT 10
""")
print("\n=== Top wave combinations ===")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

# Show sample high-score stocks
cur.execute("""
    SELECT t.symbol, t.notes, t.s7_score, i.industry
    FROM tam_expansion t
    JOIN industry_classification i ON t.symbol = i.symbol
    WHERE t.s7_score = 100
    LIMIT 15
""")
print("\n=== Sample 3-wave stocks (score=100) ===")
for row in cur.fetchall():
    print(f"  {row[0]:<15} {row[1]:<40} {row[3]}")

cur.close()
conn.close()
print("\n✓ S7 TAM expansion table built")
