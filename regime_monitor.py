"""
regime_monitor.py
Checks current market regime and sends email if regime has changed.
Run weekly via cron after price update.
Stores last known regime in a local file for comparison.
"""
import os, psycopg2, numpy as np, json, subprocess
from dotenv import load_dotenv
from datetime import date, timedelta, datetime

load_dotenv()

REGIME_FILE = os.path.join(os.path.dirname(__file__), '.last_regime.json')
NOTIFY_EMAIL = 'pravin.borade@gmail.com'  # Update if needed

def get_regime():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute("""SELECT date, close_price FROM prices
        WHERE symbol='NIFTY500_IDX' AND date >= %s ORDER BY date""",
        (date.today() - timedelta(days=400),))
    rows = [(d, float(p)) for d, p in cur.fetchall()]
    cur.close()
    conn.close()

    if not rows: return 'UNKNOWN', None, None, None

    rd = rows[-1][0]
    p_now = rows[-1][1]
    p_200 = [p for d,p in rows if d >= rd-timedelta(days=200) and d <= rd]
    p_12m = [p for d,p in rows if d >= rd-timedelta(days=375) and d <= rd-timedelta(days=350)]
    dma200 = np.mean(p_200) if p_200 else None
    p_12m_v = p_12m[0] if p_12m else None

    if dma200 and p_12m_v:
        above_dma_pct = (p_now/dma200-1)*100
        momentum_pct  = (p_now/p_12m_v-1)*100
        if p_now > dma200*1.03 and p_now > p_12m_v*1.05:
            regime = 'BULL'
        elif p_now < dma200*0.97 and p_now < p_12m_v*0.95:
            regime = 'BEAR'
        else:
            regime = 'CHOPPY'
        return regime, p_now, round(above_dma_pct,1), round(momentum_pct,1)
    return 'UNKNOWN', p_now, None, None

def get_picks():
    import subprocess, os
    try:
        result = subprocess.run(
            ['python3', 'score_and_pick.py'],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        return result.stdout.strip()
    except Exception as e:
        return f'Could not fetch picks: {e}'

def load_last_regime():
    try:
        with open(REGIME_FILE) as f:
            return json.load(f)
    except:
        return {'regime': None, 'date': None}

def save_regime(regime, p_now):
    with open(REGIME_FILE, 'w') as f:
        json.dump({'regime': regime, 'date': str(date.today()), 'price': p_now}, f)

def send_email(subject, body):
    try:
        proc = subprocess.Popen(
            ['mail', '-s', subject, NOTIFY_EMAIL],
            stdin=subprocess.PIPE
        )
        proc.communicate(body.encode())
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email failed: {e}")

# Main
regime, p_now, dma_pct, mom_pct = get_regime()
last = load_last_regime()
last_regime = last.get('regime')

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Regime: {regime} | Nifty500: {p_now:.0f} | vs 200-DMA: {dma_pct}% | vs 12m: {mom_pct}%")

# Determine action prescription
if regime == 'BULL':
    action = "DEPLOY 100% — Run score_and_pick.py and deploy top 10 stocks"
elif regime == 'BEAR':
    action = "DEPLOY 30% — Top 3 stocks only + 70% cash. Consider reducing exposure."
else:
    action = "DEPLOY 30% — Top 3 stocks only + 70% cash"


# Build subject and body
regime_changed = last_regime and last_regime != regime
regime_change_banner = f"""
⚠️  REGIME CHANGE: {last_regime} → {regime}
ACTION REQUIRED — Review and rebalance portfolio immediately.
""" if regime_changed else ''

subject = f'🚨 Model 3 REGIME CHANGE: {last_regime}→{regime} | {date.today()}' if regime_changed else f'Model 3 Weekly | {regime} Regime | {date.today()}'

if regime == 'BULL':
    stock_pct, cash_pct = '100%', '0%'
elif regime in ('BEAR', 'CHOPPY'):
    stock_pct, cash_pct = '30%', '70%'

picks_output = get_picks()

body = f"""MODEL 3 — WEEKLY REGIME & PICKS REPORT
{'='*60}
Date:        {date.today()}
Nifty500:    {p_now:.0f}
vs 200-DMA:  {dma_pct}%  (BULL needs >+3%)
vs 12m ago:  {mom_pct}%  (BULL needs >+5%)

REGIME:      {regime}
{regime_change_banner}
ALLOCATION:
  Stocks:    {stock_pct}
  Cash:      {cash_pct}
  Action:    {action}

{'='*60}
PICKS & CONVICTION SCORES:
{'='*60}
{picks_output}
{'='*60}
"""

# Always send weekly email
send_email(subject, body)
save_regime(regime, p_now)
print(f'Weekly report sent. Regime change: {regime_changed}')
