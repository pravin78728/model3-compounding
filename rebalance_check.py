"""
rebalance_check.py
Runs on Dec 1 and Jun 1 each year.
1. Refreshes financials from Screener.in
2. Rebuilds compounder features
3. Runs score_and_pick.py
4. Emails rebalance picks
"""
import os, subprocess
from dotenv import load_dotenv
from datetime import date, datetime

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
NOTIFY_EMAIL = 'pravin.borade@gmail.com'
LOG_TIME = datetime.now().strftime('%Y-%m-%d %H:%M')

def run_script(script_name, description):
    print(f"[{LOG_TIME}] Running {description}...")
    result = subprocess.run(
        ['python3', script_name],
        capture_output=True, text=True,
        cwd=SCRIPT_DIR
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-200:]}")
    else:
        print(f"  Done: {result.stdout[-100:].strip()}")
    return result.returncode == 0

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

def get_picks():
    try:
        result = subprocess.run(
            ['python3', 'score_and_pick.py'],
            capture_output=True, text=True,
            cwd=SCRIPT_DIR
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Could not fetch picks: {e}"

today = date.today()
next_rebal = 'Jun 2027' if today.month == 12 else 'Dec 2026'

print(f"[{LOG_TIME}] Starting semi-annual rebalance refresh for {today}")

# Step 1: Refresh financials from Screener.in
fin_ok = run_script('fetch_financials_full.py', 'Screener.in financials refresh')

# Step 2: Rebuild compounder features with fresh data
feat_ok = run_script('build_compounder_features.py', 'Rebuild compounder features')

# Step 3: Get fresh picks
picks_output = get_picks()

# Step 4: Send email
status = "✓ Data refreshed" if (fin_ok and feat_ok) else "⚠ Partial refresh — check logs"

subject = f"🔄 Model 3 REBALANCE — {today} | {status}"
body = f"""MODEL 3 — SEMI-ANNUAL REBALANCE
{'='*60}
Rebalance Date:  {today}
Next Rebalance:  {next_rebal}
Data Status:     {status}

Financials refreshed: {'✓' if fin_ok else '✗ FAILED — using previous data'}
Features rebuilt:     {'✓' if feat_ok else '✗ FAILED — using previous data'}

ACTION:
1. Review new picks below
2. Sell positions not in new top picks
3. Buy new picks per allocation shown
4. Hold 70% cash if CHOPPY/BEAR regime

{'='*60}
NEW PICKS & ALLOCATION:
{'='*60}
{picks_output}
{'='*60}

Logs: /Users/pravinborade/model3-compounding/model3-compounding/rebalance.log
"""

send_email(subject, body)
print(f"[{LOG_TIME}] Rebalance complete")
