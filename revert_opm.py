OLD = """    if symbol not in financial_symbols:
        if not f0['opm'] or f0['opm'] <= 10: return False"""

NEW = """    if not f0['opm'] or f0['opm'] <= 10: return False"""

for fname in ['forward_test_hybrid.py', 'live_picks_jun2026.py']:
    with open(fname) as f:
        content = f.read()
    if OLD in content:
        content = content.replace(OLD, NEW)
        with open(fname, 'w') as f:
            f.write(content)
        print(f'✓ Reverted OPM in {fname}')
    else:
        print(f'⚠ Not found in {fname}')
