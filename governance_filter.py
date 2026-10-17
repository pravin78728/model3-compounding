"""
governance_filter.py
Hard exclusion screens applied before portfolio construction.
Returns set of (symbol, rebalance_date) pairs that are EXCLUDED.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_exclusions(conn, rebal_date):
    """
    Returns set of symbols to exclude at this rebalance date.
    Applies 3 governance screens using point-in-time data.
    """
    cur = conn.cursor()
    excluded = set()
    reasons = {}

    # ── Screen 1: Extreme leverage (D/E > 5x) ────────────────────────────────
    cur.execute("""
        SELECT symbol,
               borrowings / NULLIF(equity_capital + reserves, 0) as de_ratio
        FROM financials
        WHERE year = %s
          AND borrowings IS NOT NULL
          AND equity_capital IS NOT NULL
          AND reserves IS NOT NULL
          AND borrowings / NULLIF(equity_capital + reserves, 0) > 5
    """, (rebal_date.year - 1,))
    for symbol, de in cur.fetchall():
        excluded.add(symbol)
        reasons[symbol] = f'extreme_leverage D/E={float(de):.1f}'

        # ── Screen 2: CFO negative while profit positive (non-financials only) ────
    # Banks/NBFCs/HFCs excluded — their CFO is structurally negative by design
    cur.execute("""
        WITH fin_companies AS (
            SELECT DISTINCT symbol FROM (
                VALUES ('HDFCBANK'),('ICICIBANK'),('AXISBANK'),('KOTAKBANK'),
                       ('SBIN'),('PNB'),('BANKBARODA'),('CANBK'),('INDIANB'),
                       ('FEDERALBNK'),('INDUSINDBK'),('YESBANK'),('IDFCFIRSTB'),
                       ('BAJFINANCE'),('BAJAJFINSV'),('CHOLAFIN'),('MANAPPURAM'),
                       ('MUTHOOTFIN'),('LICHSGFIN'),('PNBHOUSING'),('HDFC'),
                       ('LTF'),('IIFL'),('SHRIRAMFIN'),('SUNDARMFIN'),('M&MFIN'),
                       ('RECLTD'),('PFC'),('IREDA'),('HUDCO'),('MASFIN'),
                       ('INDOSTAR'),('CAPF'),('PFS'),('REPCOHOME'),('APTUS'),
                       ('FIVESTAR'),('CGCL'),('IDFC'),('IFCI'),('EDELWEISS'),
                       ('JMFINANCIL'),('MOTILALOFS'),('ANGELONE'),('BSE'),
                       ('NIACL'),('GICRE'),('LICI'),('ICICIGI'),('HDFCLIFE'),
                       ('SBILIFE'),('MAXFINSERV'),('POLICYBZR'),('PIRAMALFIN'),
                       ('RELCAPITAL'),('RELIGARE'),('PEL'),('IDBI'),('CHOLAHLDNG')
            ) AS t(symbol)
        )
        SELECT c.symbol, COUNT(*) as bad_years
        FROM cashflow c
        JOIN financials f ON c.symbol = f.symbol AND c.year = f.year
        WHERE c.year BETWEEN %s AND %s
          AND c.cfo < 0
          AND f.net_profit > 0
          AND c.symbol NOT IN (SELECT symbol FROM fin_companies)
        GROUP BY c.symbol
        HAVING COUNT(*) >= 2
    """, (rebal_date.year - 3, rebal_date.year - 1))
    for symbol, bad_years in cur.fetchall():
        excluded.add(symbol)
        reasons[symbol] = f'cfo_profit_divergence {bad_years} years'

    # ── Screen 3: Consecutive losses (net profit < 0 in 2 of last 3 years) ───
    cur.execute("""
        SELECT symbol, COUNT(*) as loss_years
        FROM financials
        WHERE year BETWEEN %s AND %s
          AND net_profit IS NOT NULL
          AND net_profit < 0
        GROUP BY symbol
        HAVING COUNT(*) >= 2
    """, (rebal_date.year - 3, rebal_date.year - 1))
    for symbol, loss_years in cur.fetchall():
        excluded.add(symbol)
        reasons[symbol] = f'consecutive_losses {loss_years} years'

    # ── Screen 4: Promoter stake below 10% (founder disengaged) ──────────────
    cur.execute("""
        SELECT symbol, promoter_pct
        FROM promoter_holdings
        WHERE quarter_end_date <= %s
          AND promoter_pct IS NOT NULL
        ORDER BY quarter_end_date DESC
    """, (rebal_date,))
    seen = {}
    for symbol, pct in cur.fetchall():
        if symbol not in seen:
            seen[symbol] = float(pct)

    for symbol, pct in seen.items():
        if pct < 10.0:
            excluded.add(symbol)
            reasons[symbol] = f'low_promoter_stake {pct:.1f}%'

    cur.close()
    return excluded, reasons


if __name__ == '__main__':
    # Test the filter on a known bad date
    from datetime import date
    conn = psycopg2.connect(os.environ['DATABASE_URL'])

    test_date = date(2019, 12, 1)
    excluded, reasons = get_exclusions(conn, test_date)

    print(f"Governance exclusions at {test_date}: {len(excluded)} stocks")
    # Show known bad actors
    for sym in ['CGPOWER', 'SAMMAANCAP', 'PNBHOUSING', 'INDIANB', 'JPPOWER']:
        status = f"EXCLUDED — {reasons[sym]}" if sym in excluded else "passed filter"
        print(f"  {sym}: {status}")

    print()
    print("All excluded symbols:")
    for sym in sorted(excluded):
        print(f"  {sym}: {reasons[sym]}")

    conn.close()
