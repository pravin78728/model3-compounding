"""
compute_s13_nlp.py
Scores concall transcripts using Claude API.
Produces S13 management quality score (0-100) per symbol per quarter.
Stores in s13_scores table.
Run this once ANTHROPIC_API_KEY is available in .env
"""

import os
import json
import time
import requests
import psycopg2
from dotenv import load_dotenv
from datetime import date

load_dotenv()

ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in .env")
    print("Add: ANTHROPIC_API_KEY=your_key_here to .env and rerun")
    exit(1)

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur  = conn.cursor()

# Create scores table
cur.execute("""
    CREATE TABLE IF NOT EXISTS s13_scores (
        id                      SERIAL PRIMARY KEY,
        symbol                  TEXT,
        transcript_date         DATE,
        fiscal_quarter          TEXT,
        guidance_specificity    NUMERIC,
        confidence_tone         NUMERIC,
        accountability          NUMERIC,
        outlook_positivity      NUMERIC,
        red_flags               NUMERIC,
        s13_score               NUMERIC,
        key_insight             TEXT,
        scored_at               TIMESTAMP DEFAULT NOW(),
        UNIQUE(symbol, transcript_date)
    );
""")
conn.commit()

SCORING_PROMPT = """You are analyzing an earnings call transcript to score management quality for investment purposes.

Analyze the transcript and provide scores (0-100) for each dimension:

1. GUIDANCE_SPECIFICITY: How specific and concrete are forward guidance and targets? (100=very specific with numbers, 0=vague platitudes)
2. CONFIDENCE_TONE: How confident vs hedging is management's language? (100=very confident, 0=extremely hedging)
3. ACCOUNTABILITY: Does management take responsibility for misses or blame externals? (100=full accountability, 0=all external blame)
4. OUTLOOK_POSITIVITY: How positive is the forward outlook? (100=very bullish, 0=very cautious/bearish)
5. RED_FLAGS: Absence of red flags — one-time items, accounting changes, aggressive assumptions (100=no red flags, 0=many red flags)

Respond ONLY with valid JSON in exactly this format, no other text:
{"guidance_specificity": 75, "confidence_tone": 80, "accountability": 70, "outlook_positivity": 65, "red_flags": 90, "s13_score": 76, "key_insight": "one sentence summary of management quality"}

TRANSCRIPT:
"""

def score_transcript(text, symbol):
    """Call Claude API to score a transcript."""
    # Use first 10000 chars to stay within token limits
    excerpt = text[:10000]
    try:
        r = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'Content-Type': 'application/json',
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01'
            },
            json={
                'model': 'claude-sonnet-4-6',
                'max_tokens': 500,
                'messages': [{'role': 'user', 'content': SCORING_PROMPT + excerpt}]
            },
            timeout=30
        )
        if r.status_code != 200:
            return None
        result = r.json()
        text_response = result['content'][0]['text'].strip()
        # Clean up any markdown
        text_response = text_response.replace('```json', '').replace('```', '').strip()
        return json.loads(text_response)
    except Exception as e:
        print(f"  API error for {symbol}: {e}")
        return None

# Get unscored transcripts
cur.execute("""
    SELECT t.id, t.symbol, t.transcript_date, t.fiscal_quarter, t.transcript_text
    FROM concall_transcripts t
    LEFT JOIN s13_scores s ON t.symbol = s.symbol AND t.transcript_date = s.transcript_date
    WHERE s.id IS NULL
    AND t.word_count >= 200
    ORDER BY t.transcript_date DESC
""")
transcripts = cur.fetchall()
print(f"Transcripts to score: {len(transcripts)}")

scored = 0
errors = 0

for tid, symbol, t_date, quarter, text in transcripts:
    scores = score_transcript(text, symbol)
    if not scores:
        errors += 1
        time.sleep(1)
        continue

    try:
        cur.execute("""
            INSERT INTO s13_scores
                (symbol, transcript_date, fiscal_quarter,
                 guidance_specificity, confidence_tone, accountability,
                 outlook_positivity, red_flags, s13_score, key_insight)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (symbol, transcript_date) DO NOTHING
        """, (
            symbol, t_date, quarter,
            scores.get('guidance_specificity'),
            scores.get('confidence_tone'),
            scores.get('accountability'),
            scores.get('outlook_positivity'),
            scores.get('red_flags'),
            scores.get('s13_score'),
            scores.get('key_insight')
        ))
        conn.commit()
        scored += 1
        print(f"  {symbol} {quarter}: s13={scores.get('s13_score')} — {scores.get('key_insight','')[:60]}")
        time.sleep(0.5)  # Respect rate limits
    except Exception as e:
        errors += 1

print(f"\n✓ Done. scored={scored} errors={errors}")

# Show sample scores
cur.execute("""
    SELECT symbol, fiscal_quarter, s13_score, key_insight
    FROM s13_scores
    ORDER BY s13_score DESC
    LIMIT 10
""")
print("\nTop 10 management quality scores:")
for row in cur.fetchall():
    print(f"  {row[0]:<15} {row[1]:<8} s13={row[2]:.0f} — {row[3][:50] if row[3] else ''}")

cur.close()
conn.close()
