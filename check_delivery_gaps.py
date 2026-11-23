# Check delivery gaps and test URL availability
import requests
from datetime import datetime, timedelta

headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.nseindia.com'
}

# Check last 15 trading days
today = datetime.today()
print("Checking NSE delivery URL availability for last 15 calendar days:")
print(f"{'Date':<15} {'Weekday':<12} {'HTTP Status':<12} {'Available?'}")
print("-"*50)
for i in range(15):
    date = today - timedelta(days=i)
    if date.weekday() >= 5:
        print(f"{date.strftime('%Y-%m-%d'):<15} {'Weekend':<12} {'─':<12} Skip")
        continue
    date_str = date.strftime('%d%m%Y')
    url = f'https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv'
    try:
        r = requests.get(url, headers=headers, timeout=10)
        avail = "✅ Available" if r.status_code == 200 else "❌ Not found"
        print(f"{date.strftime('%Y-%m-%d'):<15} {date.strftime('%A'):<12} {r.status_code:<12} {avail}")
    except Exception as e:
        print(f"{date.strftime('%Y-%m-%d'):<15} {date.strftime('%A'):<12} {'ERROR':<12} {e}")
