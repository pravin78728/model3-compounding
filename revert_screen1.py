OLD = """    if symbol in financial_symbols:
        if not f1 or not f0['net_profit'] or not f1['net_profit'] or f1['net_profit'] <= 0: return False
        if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False
        if not f3 or not f3['net_profit'] or f3['net_profit'] <= 0: return False
        if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 15: return False
    else:
        if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
        if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
        if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
        if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False
        if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
        if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
        if not f3['net_profit'] or f3['net_profit'] <= 0: return False
        if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False"""

NEW_HYB = """    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False

    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False"""

NEW_LIVE = """    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False
    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False"""

for fname, new in [('forward_test_hybrid.py', NEW_HYB), ('live_picks_jun2026.py', NEW_LIVE)]:
    with open(fname) as f:
        content = f.read()
    if OLD in content:
        content = content.replace(OLD, new)
        with open(fname, 'w') as f:
            f.write(content)
        print(f'✓ Reverted {fname}')
    else:
        print(f'⚠ Not found in {fname} - checking content')
        # Show what's actually there
        for i, line in enumerate(content.split('\n')):
            if 'net_profit' in line and 'financial' in line.lower():
                print(f'  Line {i}: {line}')
