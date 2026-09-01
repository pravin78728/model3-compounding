"""
regime_classifier.py
Classifies market regime at any given date as:
  BULL    — trending up, momentum works, full allocation
  CHOPPY  — range-bound, tighten quality, reduce momentum
  BEAR    — sustained downtrend, heavy quality bias, reduce size
  CRISIS  — VIX spike + breadth collapse, move to cash

Signals used (all market-wide):
  1. Nifty 500 vs 200-DMA (trend)
  2. Nifty 500 12-month momentum
  3. Nifty 500 50-DMA slope (direction)
  4. India VIX level
  5. India VIX 20-day change (direction)
  6. Repo rate direction (macro)
  7. Nifty 500 drawdown from 52-week high
"""

import os
import pandas as pd
import numpy as np
import psycopg2
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

def load_price_series(conn, symbol, start_date=None):
    """Load price series for a symbol into a pandas Series."""
    cur = conn.cursor()
    if start_date:
        cur.execute("""
            SELECT date, close_price FROM prices
            WHERE symbol = %s AND date >= %s AND close_price IS NOT NULL
            ORDER BY date
        """, (symbol, start_date))
    else:
        cur.execute("""
            SELECT date, close_price FROM prices
            WHERE symbol = %s AND close_price IS NOT NULL
            ORDER BY date
        """, (symbol,))
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return pd.Series(dtype=float)
    dates, prices = zip(*rows)
    return pd.Series(
        [float(p) for p in prices],
        index=pd.to_datetime(dates)
    ).sort_index()

def classify_regime(target_date, conn, verbose=False):
    """
    Classify market regime at target_date.
    Returns: ('BULL'|'CHOPPY'|'BEAR'|'CRISIS', dict of signal values)
    """
    td = pd.Timestamp(target_date)
    start = td - timedelta(days=400)  # enough for 200-DMA + 12m momentum

    nifty  = load_price_series(conn, 'NIFTY500_IDX', start.date())
    vix    = load_price_series(conn, 'INDIAVIX_IDX', start.date())

    # Trim to on or before target date
    nifty = nifty[nifty.index <= td]
    vix   = vix[vix.index <= td]

    if len(nifty) < 50:
        return 'UNKNOWN', {}

    signals = {}

    # ── Signal 1: Price vs 200-DMA ────────────────────────────────────────────
    if len(nifty) >= 200:
        ma200 = nifty.iloc[-200:].mean()
    else:
        ma200 = nifty.mean()
    current = float(nifty.iloc[-1])
    signals['price_vs_200dma'] = (current - ma200) / ma200 * 100
    signals['above_200dma'] = current > ma200

    # ── Signal 2: 12-month momentum ───────────────────────────────────────────
    if len(nifty) >= 250:
        price_12m_ago = float(nifty.iloc[-250])
        signals['momentum_12m'] = (current - price_12m_ago) / price_12m_ago * 100
    else:
        signals['momentum_12m'] = 0.0

    # ── Signal 3: 50-DMA slope (rising or falling) ────────────────────────────
    if len(nifty) >= 60:
        ma50_now  = nifty.iloc[-50:].mean()
        ma50_prev = nifty.iloc[-60:-10].mean()
        signals['ma50_slope'] = (ma50_now - ma50_prev) / ma50_prev * 100
    else:
        signals['ma50_slope'] = 0.0

    # ── Signal 4: India VIX level ─────────────────────────────────────────────
    if len(vix) > 0:
        signals['vix_level'] = float(vix.iloc[-1])
    else:
        signals['vix_level'] = 15.0  # default neutral

    # ── Signal 5: VIX 20-day change ───────────────────────────────────────────
    if len(vix) >= 20:
        signals['vix_change_20d'] = (float(vix.iloc[-1]) - float(vix.iloc[-20])) / float(vix.iloc[-20]) * 100
    else:
        signals['vix_change_20d'] = 0.0

    # ── Signal 6: Drawdown from 52-week high ──────────────────────────────────
    if len(nifty) >= 250:
        high_52wk = nifty.iloc[-250:].max()
        signals['drawdown_52wk'] = (current - high_52wk) / high_52wk * 100
    else:
        signals['drawdown_52wk'] = 0.0

    # ── Signal 7: Repo rate direction ─────────────────────────────────────────
    cur2 = conn.cursor()
    cur2.execute("""
        SELECT value FROM macro_indicators
        WHERE indicator = 'repo_rate' AND date <= %s
        ORDER BY date DESC LIMIT 2
    """, (target_date,))
    rates = [float(r[0]) for r in cur2.fetchall()]
    cur2.close()
    if len(rates) >= 2:
        signals['rate_cutting'] = rates[0] < rates[1]
    else:
        signals['rate_cutting'] = False

    # ── Classification logic ──────────────────────────────────────────────────
    vix_level    = signals['vix_level']
    vix_change   = signals['vix_change_20d']
    above_200dma = signals['above_200dma']
    mom_12m      = signals['momentum_12m']
    drawdown     = signals['drawdown_52wk']
    ma50_slope   = signals['ma50_slope']

            # CRISIS: VIX spike + deep drawdown
    if vix_level > 25 and vix_change > 30 and drawdown < -15:
        regime = 'CRISIS'

    # BEAR: below 200-DMA + negative momentum + falling MA50
    # BUT upgrade to CHOPPY if VIX is falling sharply (early recovery signal)
    elif not above_200dma and mom_12m < -5 and ma50_slope < -1:
        if vix_change < -20:  # VIX falling >20% in 20 days = fear dissipating
            regime = 'CHOPPY'
        else:
            regime = 'BEAR'

    # BULL: above 200-DMA + positive momentum + rising MA50
    # BUT downgrade to CHOPPY if VIX is spiking sharply (early warning)
    elif above_200dma and mom_12m > 5 and ma50_slope > 0:
        if vix_change > 40:   # VIX spiking >40% in 20 days = warning even in bull
            regime = 'CHOPPY'
        else:
            regime = 'BULL'

    # CHOPPY: everything else
    else:
        regime = 'CHOPPY'

    if verbose:
        print(f"\nRegime at {target_date}: {regime}")
        print(f"  Price vs 200-DMA:  {signals['price_vs_200dma']:+.1f}%  ({'above' if above_200dma else 'below'})")
        print(f"  12m momentum:      {mom_12m:+.1f}%")
        print(f"  50-DMA slope:      {ma50_slope:+.2f}%")
        print(f"  India VIX:         {vix_level:.1f}  (20d change: {vix_change:+.1f}%)")
        print(f"  52wk drawdown:     {drawdown:+.1f}%")
        print(f"  Rate cutting:      {signals['rate_cutting']}")

    return regime, signals


# ── Signal weights per regime ─────────────────────────────────────────────────
REGIME_WEIGHTS = {
    'BULL': {
        's15_rs_12m':          0.35,   # momentum leads
        's1_roe_trend':        0.10,
        's2_revenue_cagr':     0.10,
        's6_earnings_consist': 0.08,
        's11_roce':            0.08,
        's3_fcf':              0.07,
        's10_de_improvement':  0.07,
        's12_eps_cagr':        0.07,
        's8_peg_ratio':        0.05,
        's14_macro_cycle':     0.03,
        's5_promoter_trend':   0.00,
        's4_pli_tailwind':     0.00,
        's9_dii_accumulation': 0.00,
    },
    'CHOPPY': {
        's15_rs_12m':          0.15,   # momentum reduced
        's1_roe_trend':        0.15,
        's11_roce':            0.12,
        's6_earnings_consist': 0.12,
        's2_revenue_cagr':     0.10,
        's3_fcf':              0.10,
        's10_de_improvement':  0.08,
        's12_eps_cagr':        0.08,
        's8_peg_ratio':        0.05,
        's14_macro_cycle':     0.05,
        's5_promoter_trend':   0.00,
        's4_pli_tailwind':     0.00,
        's9_dii_accumulation': 0.00,
    },
    'BEAR': {
        's15_rs_12m':          0.05,   # momentum minimal
        's1_roe_trend':        0.20,
        's11_roce':            0.15,
        's6_earnings_consist': 0.15,
        's3_fcf':              0.12,
        's2_revenue_cagr':     0.10,
        's10_de_improvement':  0.10,
        's12_eps_cagr':        0.08,
        's8_peg_ratio':        0.05,
        's14_macro_cycle':     0.00,
        's5_promoter_trend':   0.00,
        's4_pli_tailwind':     0.00,
        's9_dii_accumulation': 0.00,
    },
    'CRISIS': {
        's15_rs_12m':          0.00,
        's1_roe_trend':        0.25,
        's11_roce':            0.20,
        's6_earnings_consist': 0.20,
        's3_fcf':              0.15,
        's2_revenue_cagr':     0.10,
        's10_de_improvement':  0.10,
        's8_peg_ratio':        0.00,
        's14_macro_cycle':     0.00,
        's5_promoter_trend':   0.00,
        's4_pli_tailwind':     0.00,
        's9_dii_accumulation': 0.00,
        's12_eps_cagr':        0.00,
    },
}

# ── Quality pre-filter thresholds per regime ──────────────────────────────────
QUALITY_FLOORS = {
    'BULL':   {'roe': 12, 'roce': 12, 'de': 2.0, 'opm':  5},
    'CHOPPY': {'roe': 15, 'roce': 15, 'de': 1.5, 'opm':  8},
    'BEAR':   {'roe': 18, 'roce': 18, 'de': 1.0, 'opm': 10},
    'CRISIS': {'roe': 20, 'roce': 20, 'de': 0.9, 'opm': 12},
}

if __name__ == '__main__':
    conn = psycopg2.connect(os.environ['DATABASE_URL'])

    # Test on all 4 forward test dates + key historical dates
    test_dates = [
        date(2020, 3, 23),   # COVID crash — should be CRISIS/BEAR
        date(2020, 6, 1),    # Recovery — should be BULL
        date(2022, 6, 1),    # Rate hike cycle — should be BEAR/CHOPPY
        date(2024, 6, 1),    # Forward test start
        date(2024, 12, 1),   # Forward test
        date(2025, 6, 1),    # Forward test
        date(2025, 12, 1),   # Forward test
        date(2026, 6, 1),    # Latest
    ]

    print("═" * 55)
    print("  REGIME CLASSIFICATION — TEST DATES")
    print("═" * 55)

    for d in test_dates:
        regime, signals = classify_regime(d, conn, verbose=True)

    conn.close()
    print("\n✓ Regime classifier ready.")
    print("Import with: from regime_classifier import classify_regime, REGIME_WEIGHTS, QUALITY_FLOORS")
