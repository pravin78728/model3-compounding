with open('score_and_pick.py', 'r') as f:
    content = f.read()

old = "print(f\"  {'Rank':<5} {'Symbol':<14} {'Score':>7} {'ROE%':>6} {'ROCE%':>7} {'EPS3Y%':>8} {'Profit1Y%':>11} {'Price':>10} Conviction\")"
new = "print(f\"  {'Rank':<5} {'Symbol':<14} {'Score':>7} {'ROE%':>6} {'ROCE%':>7} {'EPS3Y%':>8} {'Profit1Y%':>11} {'Price':>10} {'Inst':>6} Conviction\")"

if old in content:
    content = content.replace(old, new)
    print("Fixed header")
else:
    print("Header not found")

old2 = "    print(f\"  {rank:<5} {row['symbol']:<14} {row['final_score']:>7.1f} {str(row['roe']):>6} {str(row['roce']) if row['roce'] else 'N/A':>7} {eps_str:>8} {row['profit_1y']:>10.1f}% {price_str:>10} {row['inst_label']}{marker}\")"
new2 = "    print(f\"  {rank:<5} {row['symbol']:<14} {row['final_score']:>7.1f} {str(row['roe']):>6} {str(row['roce']) if row['roce'] else 'N/A':>7} {eps_str:>8} {row['profit_1y']:>10.1f}% {price_str:>10} {row['inst_score']:>6} {row['inst_label']}{marker}\")"

if old2 in content:
    content = content.replace(old2, new2)
    print("Fixed row format")
else:
    print("Row not found")

with open('score_and_pick.py', 'w') as f:
    f.write(content)
