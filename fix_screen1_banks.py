OLD = """    if not f1 or not f1['sales'] or not f0['sales'] or f1['sales'] <= 0: return False
    if (f0['sales']-f1['sales'])/f1['sales']*100 <= 1: return False
    if not f1['net_profit'] or not f0['net_profit'] or f1['net_profit'] <= 0: return False
    if (f0['net_profit']-f1['net_profit'])/f1['net_profit']*100 <= 1: return False

    if not f3 or not f3['sales'] or f3['sales'] <= 0: return False
    if ((f0['sales']/f3['sales'])**(1/3)-1)*100 <= 15: return False
    if not f3['net_profit'] or f3['net_profit'] <= 0: return False
    if ((f0['net_profit']/f3['net_profit'])**(1/3)-1)*100 <= 20: return False"""

NEW = """    if symbol in financial_symbols:
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

with open('forward_test_hybrid.py', 'r') as f:
    content = f.read()
if OLD in content:
    content = content.replace(OLD, NEW)
    with open('forward_test_hybrid.py', 'w') as f:
        f.write(content)
    print('✓ Fixed forward_test_hybrid.py')
else:
    print('⚠ Pattern not found')
