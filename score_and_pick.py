"""
score_and_pick.py
Composite quality-growth scorer — runs at any rebalance date.
Shows regime, deployment prescription, and top picks.
"""
import os, psycopg2, pandas as pd, numpy as np
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions

load_dotenv()

def get_conn():
    return psycopg2.connect(os.environ['DATABASE_URL'])

# Determine current rebalance date (nearest Jun 1 or Dec 1)
today = date.today()
if today.month <= 6:
    rebal_date = date(today.year, 6, 1)
else:
    rebal_date = date(today.year, 12, 1)

conn = get_conn()
cur = conn.cursor()

cur.execute("SELECT symbol, year, sales, net_profit, eps, borrowings, equity_capital, reserves, roce_pct, opm_pct FROM financials")
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

cur.execute("SELECT symbol, year, free_cash_flow FROM cashflow WHERE free_cash_flow IS NOT NULL")
cashflow = {}
for symbol, year, fcf in cur.fetchall():
    cashflow.setdefault(symbol, []).append({'year': year, 'fcf': float(fcf)})

cur.execute("SELECT symbol FROM industry_classification WHERE broad_sector='Financial Services'")
fin_syms = set(r[0] for r in cur.fetchall())

cur.execute("""SELECT symbol, period, fii_pct, dii_pct FROM institutional_holdings
    WHERE fii_pct IS NOT NULL AND dii_pct IS NOT NULL AND period >= '2025-01-01'
    ORDER BY symbol, period""")
inst = {}
for sym, period, fii, dii in cur.fetchall():
    inst.setdefault(sym, []).append({'period': period, 'fii': float(fii), 'dii': float(dii)})

# Latest prices
cur.execute("""SELECT symbol, close_price FROM prices p
    WHERE date = (SELECT MAX(date) FROM prices WHERE date <= %s)
    AND close_price IS NOT NULL""", (today,))
prices = dict(cur.fetchall())
prices = {k: float(v) for k, v in prices.items()}

# Nifty500 regime
cur.execute("""SELECT date, close_price FROM prices
    WHERE symbol='NIFTY500_IDX' AND date >= %s ORDER BY date""",
    (today - timedelta(days=400),))
idx_rows = [(d, float(p)) for d, p in cur.fetchall()]

cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name='Nifty 500'")
membership = cur.fetchall()
cur.close()
conn.close()

# Regime classification
regime = 'UNKNOWN'
if idx_rows:
    rd_idx = idx_rows[-1][0]
    p_now = idx_rows[-1][1]
    p_200 = [p for d,p in idx_rows if d >= rd_idx-timedelta(days=200) and d <= rd_idx]
    p_12m = [p for d,p in idx_rows if d >= rd_idx-timedelta(days=375) and d <= rd_idx-timedelta(days=350)]
    dma200 = np.mean(p_200) if p_200 else None
    p_12m_v = p_12m[0] if p_12m else None
    if dma200 and p_12m_v:
        if p_now > dma200*1.03 and p_now > p_12m_v*1.05:
            regime = 'BULL'
        elif p_now < dma200*0.97 and p_now < p_12m_v*0.95:
            regime = 'BEAR'
        else:
            regime = 'CHOPPY'

universe = list(set(s for s, vf, vt in membership
    if vf <= rebal_date and (vt is None or vt >= rebal_date)))

cutoff = rebal_date.year if rebal_date.month >= 4 else rebal_date.year - 1

results = []
for symbol in universe:
    try:
        rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff],
                      key=lambda x: x['year'], reverse=True)
        if len(rows) < 2: continue
        f0, f1 = rows[0], rows[1]
        f3 = rows[3] if len(rows) > 3 else None

        if not f0['roe'] or f0['roe'] < 15: continue
        if not f0['opm'] or f0['opm'] < 8: continue
        if symbol not in fin_syms:
            if f0['de'] is None or f0['de'] > 1.0: continue
            if not f0['roce'] or f0['roce'] < 15: continue
        if not f0['net_profit'] or f0['net_profit'] <= 0: continue
        if not f1['net_profit'] or f1['net_profit'] <= 0: continue
        if (f0['net_profit']-f1['net_profit'])/abs(f1['net_profit']) < -0.10: continue
        recent5 = [r for r in rows[:5] if r['net_profit'] is not None]
        if len(recent5) >= 4 and sum(1 for r in recent5 if r['net_profit'] > 0) < 4: continue

        scores = {}
        if f0['eps'] and f3 and f3['eps'] and f0['eps'] > 0 and f3['eps'] > 0:
            scores['eps_cagr'] = min(100, max(0, 50 + ((f0['eps']/f3['eps'])**(1/3)-1)*167))
        scores['roe'] = min(100, max(0, f0['roe'] * 2.5))
        if f0['sales'] and f3 and f3['sales'] and f0['sales'] > 0 and f3['sales'] > 0:
            scores['rev_cagr'] = min(100, max(0, 50 + ((f0['sales']/f3['sales'])**(1/3)-1)*167))
        if f0['roce']:
            scores['roce'] = min(100, max(0, f0['roce'] * 2.5))
        cf_rows = sorted([r for r in cashflow.get(symbol, []) if r['year'] <= cutoff],
                         key=lambda x: x['year'], reverse=True)[:3]
        if cf_rows:
            scores['fcf'] = sum(1 for r in cf_rows if r['fcf'] > 0)/len(cf_rows)*100
        scores['opm'] = min(100, max(0, f0['opm'] * 4))
        if symbol not in fin_syms and f0['de'] is not None:
            scores['de'] = min(100, max(0, 100 - f0['de'] * 60))
        if len(scores) < 3: continue

        weights = {'eps_cagr':0.25,'roce':0.25,'rev_cagr':0.20,'roe':0.10,'fcf':0.10,'opm':0.05,'de':0.05}
        total_w = sum(weights.get(k,0) for k in scores)
        composite = sum(scores[k]*weights.get(k,0) for k in scores) / total_w

        # Institutional conviction (8-level)
        inst_score, inst_label = 50, 'Stable'
        if symbol in inst:
            grp = sorted(inst[symbol], key=lambda x: x['period'])
            if len(grp) >= 2:
                fii_chg = grp[-1]['fii'] - grp[0]['fii']
                dii_chg = grp[-1]['dii'] - grp[0]['dii']
                total_chg = fii_chg + dii_chg
                fii_up = fii_chg > 0.2; dii_up = dii_chg > 0.2
                total_up = total_chg > 0.3; total_down = total_chg < -0.3
                if total_up and fii_up and dii_up:
                    inst_score, inst_label = 100, 'Both▲▲ [1]'
                elif total_up and fii_up:
                    inst_score, inst_label = 85, 'FII▲ Total▲ [2]'
                elif total_up and dii_up:
                    inst_score, inst_label = 80, 'DII▲ Total▲ [2]'
                elif not total_up and not total_down and (fii_up or dii_up):
                    inst_score, inst_label = 65, 'One▲ Stable [3]'
                elif total_down and fii_chg < -0.2 and dii_chg < -0.2:
                    inst_score, inst_label = 15, 'Both▼ [7]'
                elif total_down:
                    inst_score, inst_label = 35, 'Mild Dist [6]'

        final = composite * 0.70 + inst_score * 0.30
        eps_cagr_val = None
        if f0['eps'] and f3 and f3['eps'] and f0['eps'] > 0 and f3['eps'] > 0:
            eps_cagr_val = round((f0['eps']/f3['eps'])**(1/3)*100-100, 1)

        results.append({
            'symbol': symbol,
            'composite': round(composite, 1),
            'inst_score': inst_score,
            'inst_label': inst_label,
            'final_score': round(final, 1),
            'roe': round(f0['roe'], 1) if f0['roe'] else None,
            'roce': f0['roce'],
            'opm': f0['opm'],
            'eps_cagr_3y': eps_cagr_val,
            'profit_1y': round((f0['net_profit']-f1['net_profit'])/abs(f1['net_profit'])*100, 1),
            'price': prices.get(symbol),
        })
    except Exception:
        pass

df = pd.DataFrame(results)
gov_conn = get_conn()
excluded, _ = get_exclusions(gov_conn, rebal_date)
gov_conn.close()
df = df[~df['symbol'].isin(excluded)]
df = df.sort_values('final_score', ascending=False).reset_index(drop=True)

# Regime-based deployment
if regime == 'BULL':
    picks = df.head(10)
    deploy_msg = "DEPLOY 100% — Top 10 stocks"
elif regime == 'BEAR':
    picks = df.head(3)
    deploy_msg = "DEPLOY 30% — Top 3 stocks only + 70% cash"
else:  # CHOPPY
    picks = df.head(3)
    deploy_msg = "DEPLOY 30% — Top 3 stocks only + 70% cash"

print(f"\n{'═'*85}")
print(f"  COMPOUNDER MODEL — {rebal_date} REBALANCE")
print(f"  Date: {today} | Regime: {regime} | Action: {deploy_msg}")
print(f"  Quality floor passed: {len(df)} stocks")
print(f"{'═'*85}")
print(f"\n  {'Rank':<5} {'Symbol':<14} {'Score':>7} {'ROE%':>6} {'ROCE%':>7} {'EPS3Y%':>8} {'Profit1Y%':>11} {'Price':>10} Conviction")
print(f"  {'─'*85}")

for rank, (_, row) in enumerate(picks.iterrows(), 1):
    price_str = f"Rs.{row['price']:.0f}" if row['price'] else 'N/A'
    eps_str = f"{row['eps_cagr_3y']:.0f}%" if row['eps_cagr_3y'] else 'N/A'
    marker = ' ◄ DEPLOY' if rank <= (10 if regime=='BULL' else 3) else ''
    print(f"  {rank:<5} {row['symbol']:<14} {row['final_score']:>7.1f} {str(row['roe']):>6} {str(row['roce']) if row['roce'] else 'N/A':>7} {eps_str:>8} {row['profit_1y']:>10.1f}% {price_str:>10} {row['inst_label']}{marker}")

print(f"\n  Scoring: ROCE 25% + EPS CAGR 25% + Rev CAGR 20% + ROE 10% + FCF 10% + OPM 5% + D/E 5%")
print(f"  Inst conviction: 30% weight on final score")
print(f"{'═'*85}")
