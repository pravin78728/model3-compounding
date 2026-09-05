"""
live_picks_jun2026.py
Jun 2026 rebalance picks — hybrid model + institutional conviction re-ranking.
Institutional conviction scoring:
  1. Both rising + total up         = 100 (strongest)
  2. Total up, only one rising      = 85  (FII) / 80 (DII)
  3. Total same, one rising flat    = 70  (FII) / 65 (DII)
  4. Total same, one up other down  = 55  (replacement, neutral)
  5. All flat                       = 50  (neutral)
  6. Total down, one flat one down  = 35  (mild distribution)
  7. Total down, both down          = 15  (distribution, bearish)
  FII weight > DII weight (FII = data-driven, unemotional)
"""

import os
import pandas as pd
import psycopg2
import pickle
from dotenv import load_dotenv
from datetime import date
from governance_filter import get_exclusions
from regime_classifier import classify_regime

load_dotenv()

conn = psycopg2.connect(os.environ['DATABASE_URL'])
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE rebalance_date = '2026-06-01'
""", conn)

prices_df = pd.read_sql("""
    SELECT symbol, close_price FROM prices p
    WHERE date = (SELECT MAX(date) FROM prices WHERE date <= '2026-08-28')
    AND close_price IS NOT NULL
""", conn)
latest_prices = dict(zip(prices_df['symbol'], prices_df['close_price'].astype(float)))

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

cur.execute("""
    SELECT symbol, period, fii_pct, dii_pct
    FROM institutional_holdings
    WHERE period >= '2025-01-01'
    AND fii_pct IS NOT NULL AND dii_pct IS NOT NULL
    ORDER BY symbol, period
""")
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
    's11_roce','s12_eps_cagr','s14_macro_cycle','s15_rs_12m'
]

rebal_date = date(2026, 6, 1)
regime, _ = classify_regime(rebal_date, conn, verbose=False)
df['rf_score'] = model.predict(df[FEATURES])

gov_conn = psycopg2.connect(os.environ['DATABASE_URL'])
excluded, _ = get_exclusions(gov_conn, rebal_date)
gov_conn.close()
before = len(df)
df = df[~df['symbol'].isin(excluded)]

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

def passes_screen1(symbol, rebal_date):
    f0 = get_fin_year(symbol, rebal_date)
    if not f0: return False
    yr = f0['year']
    f1 = get_fin(symbol, yr-1)
    f3 = get_fin(symbol, yr-3)
    if not f0['roe'] or f0['roe'] <= 20: return False
    if symbol not in financial_symbols:
        if not f0['opm'] or f0['opm'] <= 10: return False
    if symbol not in financial_symbols:
        if f0['de'] is None or f0['de'] >= 0.9: return False
        if not f0['roce'] or f0['roce'] <= 20: return False
    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False
    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False
    prom = get_promoter_pct(symbol, rebal_date)
    if not prom or prom <= 25: return False
    return True

def institutional_score(symbol):
    """
    Score based on FII+DII trend with nuanced 8-level framework.
    FII weighted higher than DII (more data-driven, unemotional).
    """
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
    fii_flat = not fii_up and not fii_down
    dii_up   = dii_now > dii_old + 0.2
    dii_down = dii_now < dii_old - 0.2
    dii_flat = not dii_up and not dii_down
    total_up   = total_chg > 0.3
    total_down = total_chg < -0.3
    total_same = not total_up and not total_down

    # 8-level scoring framework
    if total_up and fii_up and dii_up:
        # 1. Both rising + total up — strongest
        base = 100
        label = 'Both ▲▲ Total ▲  [1]'
    elif total_up and fii_up and not dii_up:
        # 2a. Total up, only FII rising (FII weighted higher)
        base = 85
        label = 'FII ▲ Total ▲     [2]'
    elif total_up and dii_up and not fii_up:
        # 2b. Total up, only DII rising
        base = 80
        label = 'DII ▲ Total ▲     [2]'
    elif total_same and fii_up and fii_flat is False and dii_flat:
        # 3a. Total same, FII rising, DII flat
        base = 70
        label = 'FII ▲ DII — Total—[3]'
    elif total_same and dii_up and fii_flat:
        # 3b. Total same, DII rising, FII flat
        base = 65
        label = 'DII ▲ FII — Total—[3]'
    elif total_same and ((fii_up and dii_down) or (dii_up and fii_down)):
        # 4. Total same, one up other down (replacement)
        base = 55
        label = 'Replacement ↕ [4]'
    elif total_same and fii_flat and dii_flat:
        # 5. All flat
        base = 50
        label = 'All Flat —    [5]'
    elif total_down and (fii_flat or dii_flat):
        # 6. Total down, one flat one reducing
        base = 35
        label = 'Mild Dist ▼   [6]'
    elif total_down and fii_down and dii_down:
        # 7. Both down — distribution
        base = 15
        label = 'Both ▼▼ Dist  [7]'
    else:
        base = 50
        label = 'Mixed         [?]'

    # Magnitude adjustment: larger moves = stronger signal (±10 max)
    magnitude = min(10, abs(total_chg) * 1.5)
    if total_up:
        base += magnitude
    elif total_down:
        base -= magnitude

    return (round(min(100, max(0, base)), 1), label,
            round(fii_now, 1), round(dii_now, 1),
            round(total_now, 1), round(total_chg, 1))

# Screen 1
screen1_mask = df['symbol'].apply(lambda s: passes_screen1(s, rebal_date))
df_filtered = df[screen1_mask].copy()

# Top 10 by RF score
top10 = df_filtered.nlargest(10, 'rf_score').copy()
top10['rf_rank'] = range(1, 11)

# Institutional conviction
inst_results = top10['symbol'].apply(institutional_score)
top10['inst_score']  = inst_results.apply(lambda x: x[0])
top10['inst_label']  = inst_results.apply(lambda x: x[1])
top10['fii']         = inst_results.apply(lambda x: x[2])
top10['dii']         = inst_results.apply(lambda x: x[3])
top10['total_inst']  = inst_results.apply(lambda x: x[4])
top10['total_chg']   = inst_results.apply(lambda x: x[5])

# Final ranking by institutional conviction
top10 = top10.sort_values('inst_score', ascending=False).reset_index(drop=True)
top10['final_rank'] = range(1, 11)

# Prices
top10['entry_price']  = top10['symbol'].apply(lambda s: latest_prices.get(s))
top10['pred_return']  = top10['rf_score']
top10['target_price'] = top10.apply(
    lambda r: r['entry_price']*(1+r['pred_return']) if r['entry_price'] else None, axis=1)

conn.close()

print("═"*95)
print("  MODEL 3 HYBRID — JUN 2026 REBALANCE — FINAL PICKS")
print(f"  Regime: {regime} | Hold: Jun 2026 → Dec 2026 | Generated: {date.today()}")
print(f"  Universe: {before} → {len(df_filtered)} (after filters) → 10 (RF top picks)")
print("═"*95)

print(f"\n  STEP 1-2: RF Model Top 10 (quality + momentum ranked)")
print(f"  {'RF':>4} {'Symbol':<14} {'Pred Ret':>9} {'Entry':>10} {'Target':>10} {'S15':>6} {'ROCE':>6}")
print("  " + "─"*62)
for _, row in top10.sort_values('rf_rank').iterrows():
    ep = f"Rs.{row['entry_price']:.0f}" if row['entry_price'] else "N/A"
    tp = f"Rs.{row['target_price']:.0f}" if row['target_price'] else "N/A"
    s15 = f"{row['s15_rs_12m']:.0f}" if pd.notna(row['s15_rs_12m']) else "N/A"
    s11 = f"{row['s11_roce']:.0f}" if pd.notna(row['s11_roce']) else "N/A"
    print(f"  {int(row['rf_rank']):>4} {row['symbol']:<14} {row['pred_return']*100:>8.1f}% {ep:>10} {tp:>10} {s15:>6} {s11:>6}")

print(f"\n  STEP 3: Final Ranking after Institutional Conviction")
print(f"  {'Rank':>4} {'Symbol':<14} {'Pred Ret':>9} {'Entry':>10} {'Target':>10} {'FII%':>6} {'DII%':>6} {'Δ Total':>8} {'Score':>6} Conviction")
print("  " + "─"*95)
for _, row in top10.iterrows():
    ep = f"Rs.{row['entry_price']:.0f}" if row['entry_price'] else "N/A"
    tp = f"Rs.{row['target_price']:.0f}" if row['target_price'] else "N/A"
    fii = f"{row['fii']:.1f}" if row['fii'] is not None else "N/A"
    dii = f"{row['dii']:.1f}" if row['dii'] is not None else "N/A"
    chg = f"{row['total_chg']:+.1f}" if row['total_chg'] is not None else "N/A"
    print(f"  {int(row['final_rank']):>4} {row['symbol']:<14} {row['pred_return']*100:>8.1f}% {ep:>10} {tp:>10} {fii:>6} {dii:>6} {chg:>8} {row['inst_score']:>6.0f} {row['inst_label']}")

print(f"\n  Conviction levels: [1]=Both▲Total▲ [2]=Total▲ [3]=One▲ [4]=Replace [5]=Flat [6]=MildDist [7]=Both▼")
print(f"  FII weighted higher than DII (institutional, data-driven)")
print(f"  Predicted returns are model estimates. Actual results tracked at Dec 2026.")
print("═"*95)
