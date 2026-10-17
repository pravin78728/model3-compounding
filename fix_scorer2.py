with open('backtest_regime_gated.py', 'r') as f:
    content = f.read()

# Fix 1: Better weighting — ROCE and rev growth matter more than ROE alone
old = "    weights = {'eps_cagr':0.25,'roe':0.20,'rev_cagr':0.15,'roce':0.15,'fcf':0.10,'opm':0.10,'de':0.05}"
new = "    weights = {'eps_cagr':0.25,'roce':0.25,'rev_cagr':0.20,'roe':0.10,'fcf':0.10,'opm':0.05,'de':0.05}"

if old in content:
    content = content.replace(old, new)
    print('Fixed weights')
else:
    print('Weights pattern not found')

# Fix 2: In BEAR regime deploy 30% into top quality stocks instead of full cash
old = "    else:\n        model_ret = 0.04  # Cash return ~8% annualised = 4% per 6m\n        action = \"CASH\""
new = """    else:
        # In non-BULL: deploy 30% into top 3 highest-quality stocks, 70% cash
        universe = get_universe(rebal_date)
        excluded, _ = get_exclusions(gov_conn, rebal_date)
        scored_all = [(sym, score_stock(sym, rebal_date)) for sym in universe
                      if sym not in excluded]
        scored_all = [(s, sc) for s, sc in scored_all if sc]
        scored_all.sort(key=lambda x: x[1], reverse=True)
        top3 = scored_all[:3]
        partial_rets = []
        for sym, _ in top3:
            p0 = get_price_on(sym, rebal_date)
            p1 = get_price_on(sym, next_date)
            if p0 and p1 and p0 > 0:
                partial_rets.append((p1-p0)/p0)
        stock_ret = float(np.mean(partial_rets)) if partial_rets else 0.04
        model_ret = stock_ret * 0.30 + 0.04 * 0.70  # 30% stocks + 70% cash
        action = f"PARTIAL ({len(partial_rets)} stocks, 30%)\" """

if old in content:
    content = content.replace(old, new)
    print('Fixed BEAR regime')
else:
    print('BEAR pattern not found')

with open('backtest_regime_gated.py', 'w') as f:
    f.write(content)
