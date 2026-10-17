import os
import psycopg2
from dotenv import load_dotenv

# Load the DATABASE_URL from your .env file
load_dotenv()
db_url = os.getenv("DATABASE_URL")

# Connect to your Supabase database
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Create a table to hold daily price data
cur.execute("""
    CREATE TABLE IF NOT EXISTS prices (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        date DATE NOT NULL,
        close_price NUMERIC NOT NULL
    );
""")

# Insert one sample row so we can confirm it worked
cur.execute("""
    INSERT INTO prices (symbol, date, close_price)
    VALUES (%s, %s, %s);
""", ("RELIANCE", "2026-08-24", 2950.50))

conn.commit()
print("Table created and sample row inserted successfully.")

cur.close()
conn.close()
