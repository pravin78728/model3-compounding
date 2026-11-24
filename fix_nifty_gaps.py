"""
fix_nifty_gaps.py — Fill NIFTY500_IDX holiday gaps
====================================================
For dates where NIFTY500_IDX is missing (NSE holidays),
fills with the previous trading day's value.
This keeps the regime check smooth across holiday gaps.

Usage:
    python fix_nifty_gaps.py
"""

import os, pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from datetime import datetime

load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))

def main():
    print("NIFTY500_IDX Gap Filler")
    print("="*40)

    with engine.connect() as conn:
        # Get all trading days (days with stock data)
        trading_days = pd.read_sql(text("""
            SELECT DISTINCT date FROM prices
            WHERE symbol != 'NIFTY500_IDX'
            AND volume IS NOT NULL
            ORDER BY date
        """), conn)
        trading_days['date'] = pd.to_datetime(trading_days['date']).dt.date

        # Get existing NIFTY500_IDX dates
        idx_dates = pd.read_sql(text("""
            SELECT date, close_price FROM prices
            WHERE symbol = 'NIFTY500_IDX'
            ORDER BY date
        """), conn)
        idx_dates['date'] = pd.to_datetime(idx_dates['date']).dt.date
        idx_map = dict(zip(idx_dates['date'], idx_dates['close_price']))

        # Find missing trading days
        all_trading = set(trading_days['date'].tolist())
        idx_set     = set(idx_map.keys())
        missing     = sorted(all_trading - idx_set)

        print(f"Trading days total: {len(all_trading)}")
        print(f"NIFTY500_IDX days: {len(idx_set)}")
        print(f"Missing dates: {len(missing)}")

        if not missing:
            print("No gaps found.")
            return

        # For each missing date, use previous day's value
        sorted_idx  = sorted(idx_map.items())
        rows_to_add = []
        for d in missing:
            # Find most recent prior date with index value
            prior = [(dt, cp) for dt, cp in sorted_idx if dt < d]
            if not prior:
                print(f"  {d}: No prior value found — skipping")
                continue
            prior_date, prior_close = prior[-1]
            rows_to_add.append(('NIFTY500_IDX', d, float(prior_close)))
            print(f"  {d}: filling with {prior_date} value = {prior_close}")

        if rows_to_add:
            conn.execute(text("""
                INSERT INTO prices (symbol, date, close_price)
                VALUES (:s, :d, :c)
                ON CONFLICT (symbol, date) DO NOTHING
            """), [{'s': r[0], 'd': r[1], 'c': r[2]} for r in rows_to_add])
            conn.commit()
            print(f"\nInserted {len(rows_to_add)} gap-fill rows for NIFTY500_IDX")

    print("Done.")

if __name__ == "__main__":
    main()
