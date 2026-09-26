"""
rebalance_check.py
Runs on Dec 1 and Jun 1 each year.
Updates financials data, runs score_and_pick.py and emails rebalance picks.
"""
import os, subprocess
from dotenv import load_dotenv
from datetime import date, datetime

load_dotenv()

NOTIFY_EMAIL = 'pravin.borade@gmail.com'

def send_email(subject, body):
    import subprocess
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
            cwd=os.path.dirname(os.path.abspath(__file__))
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Could not fetch picks: {e}"

today = date.today()
print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Rebalance check for {today}")

picks_output = get_picks()

subject = f"🔄 Model 3 REBALANCE — {today} | Action Required"
body = f"""MODEL 3 — SEMI-ANNUAL REBALANCE
{'='*60}
Rebalance Date: {today}
Next Rebalance: {'Jun 2027' if today.month == 12 else 'Dec 2026'}

Review current holdings and rebalance to the picks below.
Sell positions not in the new top picks.
Buy new picks per allocation prescribed.

{'='*60}
{picks_output}
{'='*60}

Steps:
1. Review picks above
2. Sell stocks not in current top picks
3. Buy new picks per allocation
4. Update your portfolio tracker
"""

send_email(subject, body)
print("Rebalance email sent")
