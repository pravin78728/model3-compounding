import requests
import io
import pypdf
import json

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

# Fetch transcript
url = 'https://nsearchives.nseindia.com/corporate/INFY_22102024201421_SEfiling_Earningscalltranscript.pdf'
r = requests.get(url, headers=headers, timeout=15)
reader = pypdf.PdfReader(io.BytesIO(r.content))
text = ''
for page in reader.pages:
    text += page.extract_text() or ''

transcript_excerpt = text[:8000]
print(f"Transcript length: {len(text)} chars, using first 8000")

# Score with Claude API
prompt = """You are analyzing an earnings call transcript to score management quality for investment purposes.

Analyze the following earnings call transcript and provide scores (0-100) for each dimension:

1. GUIDANCE_SPECIFICITY: How specific and concrete are management's forward guidance and targets? (100=very specific with numbers, 0=vague platitudes)
2. CONFIDENCE_TONE: How confident vs hedging is management's language? (100=very confident, 0=extremely hedging)
3. ACCOUNTABILITY: Does management take responsibility for misses or blame externals? (100=full accountability, 0=all external blame)
4. OUTLOOK_POSITIVITY: How positive is the forward outlook? (100=very bullish, 0=very cautious/bearish)
5. RED_FLAGS: Absence of red flags like one-time items, accounting changes (100=no red flags, 0=many red flags)

Respond ONLY with valid JSON in exactly this format with no other text:
{"guidance_specificity": 75, "confidence_tone": 80, "accountability": 70, "outlook_positivity": 65, "red_flags": 90, "overall_score": 76, "key_insight": "one sentence summary"}

TRANSCRIPT:
""" + transcript_excerpt

api_response = requests.post(
    'https://api.anthropic.com/v1/messages',
    headers={'Content-Type': 'application/json'},
    json={
        'model': 'claude-sonnet-4-6',
        'max_tokens': 500,
        'messages': [{'role': 'user', 'content': prompt}]
    }
)

print(f'API Status: {api_response.status_code}')
result = api_response.json()
text_response = result['content'][0]['text']
print(f'Response: {text_response}')
scores = json.loads(text_response)
print()
print('INFY Q2 2024 Management Quality Scores:')
for k, v in scores.items():
    print(f'  {k}: {v}')
