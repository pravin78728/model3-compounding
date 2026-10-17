with open('backtest_regime_gated.py', 'r') as f:
    content = f.read()

old = "    if not f0['net_profit'] or f0['net_profit'] <= 0: return None\n    if not f1['net_profit'] or f1['net_profit'] <= 0: return None\n    if (f0['net_profit']-f1['net_profit'])/abs(f1['net_profit']) < -0.10: return None"

new = "    if not f0['net_profit'] or f0['net_profit'] <= 0: return None\n    if not f1['net_profit'] or f1['net_profit'] <= 0: return None\n    if (f0['net_profit']-f1['net_profit'])/abs(f1['net_profit']) < -0.10: return None\n    # Consistency: require profit positive in 4 of last 5 years\n    recent5 = [r for r in rows[:5] if r['net_profit'] is not None]\n    if len(recent5) >= 4:\n        pos_years = sum(1 for r in recent5 if r['net_profit'] > 0)\n        if pos_years < 4: return None"

if old in content:
    content = content.replace(old, new)
    with open('backtest_regime_gated.py', 'w') as f:
        f.write(content)
    print('Fixed')
else:
    print('Pattern not found')
