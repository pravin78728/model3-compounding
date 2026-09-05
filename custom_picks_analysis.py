"""
custom_picks_analysis.py
Runs a custom list of stocks through the Jun 2026 rebalance pipeline.
Shows RF score, predicted return, entry price, target price, FII/DII conviction.
"""

import os
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date

load_dotenv()

# Custom stock list - normalize to uppercase
CUSTOM_STOCKS = [
    'ABB', 'DIXON', 'DLF', 'GANESHHOU', 'GMBREW', 'GRSE', 'INDRAMEDCO',
    'INDUSINDBK', 'IRCTC', 'JIOFIN', 'KAYNES', 'KRN', 'MAZDOCK',
    'NATCOPHARM', 'PRESTIGE', 'UNIECOM'
]

conn = psycopg2.connect(os.environ['DATABASE_URL'])

# Load Jun 2026 training data
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE rebalance_date = '2026-06-01'
    AND symbol = ANY(%s)
""", conn, params=(CUSTOM_STOCKS,))

# Latest prices
prices_df = pd.read_sql("""
    SELECT symbol, close_price FROM prices p
    WHERE date = (SELECT MAX(date) FROM prices WHERE date <= '2026-08-28')
    AND close_price IS NOT NULL
    AND symbol = ANY(%s)
""", conn, params=(CUSTOM_STOCKS,))
latest_prices = dict(zip(prices_df['symbol'], prices_df['close_price'].astype(float)))

# Screen 1 data
cur = conn.cursor()
cur.execute("""
    SELECT symbol, year, sales, net_profit, eps,
           borrowings, equity_capital, reserves, roce_pct, opm_pct
    FROM financials
""")
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

cur.execute("SELECT symbol, quarter_end_date, promoter_pct FROM promoter_holdings WHERE promoter_pct IS NOT NULL")
promoter = {}
for symbol, qend, pct in cur.fetchall():
    promoter.setdefault(symbol, []).append({'qend': qend, 'pct': float(pct)})

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector = 'Financial Services'")
financial_symbols = set(row[0] for row in cur.fetchall())

# Institutional holdings
cur.execute("""
    SELECT symbol, period, fii_pct, dii_pct
    FROM institutional_holdings
    WHERE period >= '2025-01-01'
    AND fii_pct IS NOT NULL AND dii_pct IS NOT NULL
    AND symbol = ANY(%s)
    ORDER BY symbol, period
""", (CUSTOM_STOCKS,))
inst_rows = cur.fetchall()
inst_df = pd.DataFrame(inst_rows, columns=['symbol','period','fii_pct','dii_pct'])
inst_df['period'] = pd.to_datetime(inst_df['period'])
inst_df['fii_pct'] = inst_df['fii_pct'].astype(float)
inst_df['dii_pct'] = inst_df['dii_pct'].astype(float)
cur.close()

with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

FEATURES = [
    's1_roe_trend','s2_revenue_cagr','s3_fcf','s4_pli_tailwind',
    's5_promoter_trend','s6_earnings_consist','s7_tam_expansion',
    's8_peg_ratio','s9_dii_accumulation','s10_de_improvement',
    's11_roce','s12_eps_cagr','s14_macro_cycle','s15_rs_12m',
    's_fii_trend','s_dii_trend'
]

rebal_date = date(2026, 6, 1)

def get_fin_year(symbol, rebal_date):
    cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1
    rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff],
                  key=lambda x: x['year'], reverse=True)
    return rows[0] if rows else None

def get_fin(symbol, year):
    rows = [r for r in financials.get(symbol, []) if r['year'] == year]
    return rows[0] if rows else None

def get_promoter_pct(symbol, rebal_date):
    rows = sorted([r for r in promoter.get(symbol, []) if r['qend'] <= rebal_date],
                  key=lambda x: x['qend'], reverse=True)
    return rows[0]['pct'] if rows else None

def screen1_status(symbol, rebal_date):
    """Returns (passes, fail_reason)"""
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False, 'No financials'
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)
    if not f0['roe'] or f0['roe'] <= 20: return False, f'ROE={round(f0["roe"],1) if f0["roe"] else "N/A"} (need >20)'
    if symbol not in financial_symbols:
        if not f0['opm'] or f0['opm'] <= 10: return False, f'OPM={round(f0["opm"],1) if f0["opm"] else "N/A"} (need >10)'
    if symbol not in financial_symbols:
        if f0['de'] is None or f0['de'] >= 0.9: return False, f'D/E={round(f0["de"],2) if f0["de"] else "N/A"} (need <0.9)'
        if not f0['roce'] or f0['roce'] <= 20: return False, f'ROCE={round(f0["roce"],1) if f0["roce"] else "N/A"} (need >20)'
    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False, 'No sales data'
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False, f'Sales 1Y low'
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False, 'Profit 1Y low'
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False, 'Profit 1Y low'
    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False, 'No 3Y sales'
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False, f'Sales 3Y CAGR low'
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False, 'No 3Y profit'
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False, f'Profit 3Y CAGR low'
    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False, f'Promoter={round(prom,1) if prom else "N/A"} (need >25)'
    return True, 'PASS'

def institutional_score(symbol):
    grp = inst_df[inst_df['symbol']==symbol].sort_values('period')
    if len(grp) < 2:
        return 50.0, 'Insufficient data', None, None, None, None
    latest  = grp.iloc[-1]
    oldest  = grp.iloc[0]
    fii_now  = float(latest['fii_pct'])
    dii_now  = float(latest['dii_pct'])
    fii_old  = float(oldest['fii_pct'])
    dii_old  = float(oldest['dii_pct'])
    total_now = fii_now + dii_now
    total_old = fii_old + dii_old
    total_chg = total_now - total_old
    fii_up   = fii_now > fii_old + 0.2
    fii_down = fii_now < fii_old - 0.2
    dii_up   = dii_now > dii_old + 0.2
    dii_down = dii_now < dii_old - 0.2
    total_up   = total_chg > 0.3
    total_down = total_chg < -0.3
    total_same = not total_up and not total_down

    if total_up and fii_up and dii_up:
        base, label = 100, 'Both ▲▲ Total ▲  [1]'
    elif total_up and fii_up and not dii_up:
        base, label = 85, 'FII ▲ Total ▲     [2]'
    elif total_up and dii_up and not fii_up:
        base, label = 80, 'DII ▲ Total ▲     [2]'
    elif total_same and fii_up and not dii_up:
        base, label = 70, 'FII ▲ DII — Total—[3]'
    elif total_same and dii_up and not fii_up:
        base, label = 65, 'DII ▲ FII — Total—[3]'
    elif total_same and ((fii_up and dii_down) or (dii_up and fii_down)):
        base, label = 55, 'Replacement ↕ [4]'
    elif total_same and not fii_up and not dii_up and not fii_down and not dii_down:
        base, label = 50, 'All Flat —    [5]'
    elif total_down and (not fii_down or not dii_down):
        base, label = 35, 'Mild Dist ▼   [6]'
    elif total_down and fii_down and dii_down:
        base, label = 15, 'Both ▼▼ Dist  [7]'
    else:
        base, label = 50, 'Mixed         [?]'

    magnitude = min(10, abs(total_chg) * 1.5)
    if total_up: base += magnitude
    elif total_down: base -= magnitude

    return (round(min(100, max(0, base)), 1), label,
            round(fii_now, 1), round(dii_now, 1),
            round(total_now, 1), round(total_chg, 1))

# Score all custom stocks
if len(df) > 0:
    df['rf_score'] = model.predict(df[FEATURES])
else:
    print("Warning: No stocks found in training data for Jun 2026")

# Check which stocks are missing from training data
found = set(df['symbol'].tolist())
missing = [s for s in CUSTOM_STOCKS if s not in found]

results = []
for sym in CUSTOM_STOCKS:
    row = df[df['symbol']==sym]
    s1_pass, s1_reason = screen1_status(sym, rebal_date)
    inst_sc, inst_label, fii, dii, total_inst, total_chg = institutional_score(sym)
    price = latest_prices.get(sym)

    if len(row) > 0:
        rf_score = float(row.iloc[0]['rf_score'])
        pred_ret = rf_score
        target = price * (1+pred_ret) if price else None
    else:
        rf_score = None
        pred_ret = None
        target = None

    results.append({
        'symbol': sym,
        'screen1': '✓' if s1_pass else '✗',
        'screen1_reason': s1_reason,
        'rf_score': rf_score,
        'pred_return': pred_ret,
        'entry_price': price,
        'target_price': target,
        'fii': fii,
        'dii': dii,
        'total_chg': total_chg,
        'inst_score': inst_sc,
        'inst_label': inst_label,
    })

results_df = pd.DataFrame(results)
# Sort by RF score descending
results_df = results_df.sort_values('rf_score', ascending=False, na_position='last')

conn.close()

print("═"*100)
print("  CUSTOM STOCK LIST — JUN 2026 REBALANCE ANALYSIS")
print("  Model: Hybrid Screen 1 + RF | Hold: Jun 2026 → Dec 2026")
print("═"*100)
print(f"\n  {'Symbol':<14} {'S1':>4} {'Pred Ret':>9} {'Entry':>10} {'Target':>10} {'FII%':>6} {'DII%':>6} {'ΔTotal':>8} {'Inst':>6} Conviction")
print("  " + "─"*100)

for _, row in results_df.iterrows():
    s1 = row['screen1']
    ep = f"Rs.{row['entry_price']:.0f}" if row['entry_price'] else "N/A"
    tp = f"Rs.{row['target_price']:.0f}" if row['target_price'] else "N/A"
    pr = f"{row['pred_return']*100:.1f}%" if row['pred_return'] is not None else "N/A"
    fii = f"{row['fii']:.1f}" if row['fii'] is not None else "N/A"
    dii = f"{row['dii']:.1f}" if row['dii'] is not None else "N/A"
    chg = f"{row['total_chg']:+.1f}" if row['total_chg'] is not None else "N/A"
    inst = f"{row['inst_score']:.0f}" if row['inst_score'] else "N/A"
    reason = '' if row['screen1'] == '✓' else f" ← {row['screen1_reason']}"
    print(f"  {row['symbol']:<14} {s1:>4} {pr:>9} {ep:>10} {tp:>10} {fii:>6} {dii:>6} {chg:>8} {inst:>6} {row['inst_label']}{reason}")

print(f"\n  Screen 1 pass: {(results_df['screen1']=='✓').sum()}/{len(results_df)}")
print(f"  Missing from Jun 2026 universe: {missing if missing else 'None'}")
print(f"\n  Conviction: [1]=Both▲Total▲ [2]=Total▲ [3]=One▲ [4]=Replace [5]=Flat [6]=MildDist [7]=Both▼")
print("═"*100)
