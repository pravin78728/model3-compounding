"""
Composite quality-growth scorer for Jun 2026 rebalance.
No ML — direct weighted scoring of fundamental signals.
"""
import os, psycopg2, pandas as pd
from dotenv import load_dotenv
from datetime import date, timedelta
from governance_filter import get_exclusions

load_dotenv()

def get_conn():
    return psycopg2.connect(os.environ['DATABASE_URL'])

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
    WHERE fii_pct IS NOT NULL AND dii_pct IS NOT NULL AND period >= '2025-01-01' ORDER BY symbol, period""")
inst = {}
for sym, period, fii, dii in cur.fetchall():
    inst.setdefault(sym, []).append({'period': period, 'fii': float(fii), 'dii': float(dii)})

cur.execute("""SELECT symbol, date, close_price FROM prices
    WHERE close_price IS NOT NULL AND date >= '2026-08-01'
    ORDER BY symbol, date DESC""")
prices = {}
for symbol, d, price in cur.fetchall():
    if symbol not in prices:
        prices[symbol] = float(price)

cur.execute("SELECT symbol, valid_from, valid_to FROM index_membership WHERE index_name='Nifty 500'")
membership = cur.fetchall()
cur.close()
conn.close()

rebal_date = date(2026, 6, 1)
cutoff = 2026

universe = list(set(s for s, vf, vt in membership
    if vf <= rebal_date and (vt is None or vt >= rebal_date)))

results = []
for symbol in universe:
    try:
        rows = sorted([r for r in financials.get(symbol, []) if r['year'] <= cutoff],
                      key=lambda x: x['year'], reverse=True)
        if len(rows) < 2: continue
        f0, f1 = rows[0], rows[1]
        f3 = rows[3] if len(rows) > 3 else None

        # Hard quality floor
        if not f0['roe'] or f0['roe'] < 15: continue
        if not f0['opm'] or f0['opm'] < 8: continue
        if symbol not in fin_syms:
            if f0['de'] is None or f0['de'] > 1.0: continue
            if not f0['roce'] or f0['roce'] < 15: continue
        if not f0['net_profit'] or f0['net_profit'] <= 0: continue
        if not f1['net_profit'] or f1['net_profit'] <= 0: continue
        profit_growth = (f0['net_profit'] - f1['net_profit']) / abs(f1['net_profit'])
        if profit_growth < -0.10: continue  # Allow up to 10% decline

        scores = {}

        # EPS CAGR 3Y (25%)
        if f0['eps'] and f3 and f3['eps'] and f0['eps'] > 0 and f3['eps'] > 0:
            eps_cagr = (f0['eps']/f3['eps'])**(1/3) - 1
            scores['eps_cagr'] = min(100, max(0, 50 + eps_cagr * 167))

        # ROE quality (20%)
        scores['roe'] = min(100, max(0, f0['roe'] * 2.5))

        # Revenue CAGR 3Y (15%)
        if f0['sales'] and f3 and f3['sales'] and f0['sales'] > 0 and f3['sales'] > 0:
            rev_cagr = (f0['sales']/f3['sales'])**(1/3) - 1
            scores['rev_cagr'] = min(100, max(0, 50 + rev_cagr * 167))

        # ROCE (15%)
        if f0['roce']:
            scores['roce'] = min(100, max(0, f0['roce'] * 2.5))

        # FCF quality (10%)
        cf_rows = sorted([r for r in cashflow.get(symbol, []) if r['year'] <= cutoff],
                         key=lambda x: x['year'], reverse=True)[:3]
        if cf_rows:
            pos = sum(1 for r in cf_rows if r['fcf'] > 0)
            scores['fcf'] = pos/len(cf_rows)*100

        # OPM level (10%)
        scores['opm'] = min(100, max(0, f0['opm'] * 4))

        # D/E (5%) — non-financials only
        if symbol not in fin_syms and f0['de'] is not None:
            scores['de'] = min(100, max(0, 100 - f0['de'] * 60))

        if len(scores) < 3: continue

        weights = {'eps_cagr': 0.25, 'roe': 0.20, 'rev_cagr': 0.15,
                   'roce': 0.15, 'fcf': 0.10, 'opm': 0.10, 'de': 0.05}
        total_w = sum(weights.get(k, 0) for k in scores)
        if total_w == 0: continue
        composite = sum(scores[k]*weights.get(k,0) for k in scores) / total_w

        # Institutional conviction
        inst_score, inst_label = 50, 'Stable'
        if symbol in inst:
            grp = sorted(inst[symbol], key=lambda x: x['period'])
            if len(grp) >= 2:
                fii_chg = grp[-1]['fii'] - grp[0]['fii']
                dii_chg = grp[-1]['dii'] - grp[0]['dii']
                total_chg = fii_chg + dii_chg
                if fii_chg > 0.2 and dii_chg > 0.2 and total_chg > 0.3:
                    inst_score, inst_label = 100, 'Both▲▲ [1]'
                elif total_chg > 0.3 and fii_chg > 0.2:
                    inst_score, inst_label = 85, 'FII▲ [2]'
                elif total_chg > 0.3 and dii_chg > 0.2:
                    inst_score, inst_label = 80, 'DII▲ [2]'
                elif total_chg > 0 and (fii_chg > 0.2 or dii_chg > 0.2):
                    inst_score, inst_label = 65, 'One▲ [3]'
                elif total_chg < -0.5:
                    inst_score, inst_label = 20, 'Both▼ [7]'

        final = composite * 0.70 + inst_score * 0.30

        results.append({
            'symbol': symbol,
            'composite': round(composite, 1),
            'inst_score': inst_score,
            'inst_label': inst_label,
            'final_score': round(final, 1),
            'roe': round(f0['roe'], 1) if f0['roe'] else None,
            'roce': f0['roce'],
            'opm': f0['opm'],
            'eps_cagr_3y': round((f0['eps']/f3['eps'])**(1/3)*100-100, 1) if f0['eps'] and f3 and f3['eps'] and f0['eps'] > 0 and f3['eps'] > 0 else None,
            'profit_growth_1y': round(profit_growth*100, 1),
            'price': prices.get(symbol),
        })
    except Exception:
        pass

df = pd.DataFrame(results)
gov_conn = get_conn()
excluded, _ = get_exclusions(gov_conn, rebal_date)
gov_conn.close()
df = df[~df['symbol'].isin(excluded)]
df = df.sort_values('final_score', ascending=False)
top15 = df.head(15)

print(f"\n{'═'*85}")
print(f"  QUALITY-GROWTH COMPOUNDER PICKS — JUN 2026")
print(f"  Scoring: 70% fundamentals + 30% institutional conviction")
print(f"  Quality floor: ROE>15%, OPM>8%, ROCE>15%, profit positive")
print(f"  Passed quality floor: {len(df)} stocks")
print(f"{'═'*85}")
print(f"\n  {'Rank':<5} {'Symbol':<14} {'Score':>7} {'ROE%':>6} {'ROCE%':>7} {'OPM%':>6} {'EPS3Y%':>8} {'Profit1Y%':>10} {'Price':>10} Conviction")
print(f"  {'─'*85}")
for rank, (_, row) in enumerate(top15.iterrows(), 1):
    price_str = f"Rs.{row['price']:.0f}" if row['price'] else 'N/A'
    eps_str = f"{row['eps_cagr_3y']:.0f}%" if row['eps_cagr_3y'] else 'N/A'
    print(f"  {rank:<5} {row['symbol']:<14} {row['final_score']:>7.1f} {str(row['roe']):>6} {str(row['roce']) if row['roce'] else 'N/A':>7} {str(row['opm']) if row['opm'] else 'N/A':>6} {eps_str:>8} {row['profit_growth_1y']:>9.1f}% {price_str:>10} {row['inst_label']}")

print(f"\n{'═'*85}")
