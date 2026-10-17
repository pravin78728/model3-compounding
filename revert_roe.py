OLD = """    roe_threshold = 12 if symbol in financial_symbols else 20
    if not f0['roe'] or f0['roe'] <= roe_threshold: return False"""

NEW = """    if not f0['roe'] or f0['roe'] <= 20: return False"""

for fname in ['forward_test_hybrid.py', 'live_picks_jun2026.py']:
    with open(fname) as f:
        content = f.read()
    if OLD in content:
        content = content.replace(OLD, NEW)
        with open(fname, 'w') as f:
            f.write(content)
        print(f'✓ Reverted ROE in {fname}')
    else:
        print(f'⚠ Not found in {fname}')
