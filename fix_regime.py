with open('backtest_regime_gated.py', 'r') as f:
    content = f.read()

old = '''    if above_dma and momentum_pos and p_now > dma200 * 1.03 and p_now > p_12m * 1.05: return 'BULL'
    if not above_dma and not momentum_pos: return 'BEAR'
    return 'CHOPPY' '''

new = '''    # 6-month momentum check
    d6m = rebal_date - timedelta(days=180)
    p_6m_prices = [p for d, p in prices.get(idx,[]) if d >= d6m and d <= d6m + timedelta(days=20)]
    p_6m = p_6m_prices[0] if p_6m_prices else None
    momentum_6m = p_now > p_6m * 1.03 if p_6m else True

    if above_dma and momentum_pos and p_now > dma200 * 1.03 and p_now > p_12m * 1.05 and momentum_6m: return 'BULL'
    if not above_dma and not momentum_pos: return 'BEAR'
    return 'CHOPPY' '''

if old in content:
    content = content.replace(old, new)
    with open('backtest_regime_gated.py', 'w') as f:
        f.write(content)
    print('Fixed')
else:
    print('Pattern not found - checking...')
    # Find the regime function
    idx = content.find('def classify_regime')
    print(content[idx:idx+500])
