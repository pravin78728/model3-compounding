with open('backtest_regime_gated.py', 'r') as f:
    content = f.read()

# Remove 6m momentum requirement from BULL condition
old = "    if above_dma and momentum_pos and p_now > dma200 * 1.03 and p_now > p_12m * 1.05 and mom_6m: return \"BULL\""
new = "    if above_dma and momentum_pos and p_now > dma200 * 1.03 and p_now > p_12m * 1.05: return \"BULL\""

if old in content:
    content = content.replace(old, new)
    with open('backtest_regime_gated.py', 'w') as f:
        f.write(content)
    print('Reverted 6m check')
else:
    print('Pattern not found')
