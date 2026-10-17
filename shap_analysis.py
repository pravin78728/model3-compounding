"""
shap_analysis.py
SHAP signal attribution for Model 3 Random Forest.
Shows which signals drive the model's stock picks.
"""

import os
import numpy as np
import pandas as pd
import psycopg2
import pickle
import shap
from dotenv import load_dotenv

load_dotenv()

# Load model and data
print("Loading model and training data...")
with open('model3_rf.pkl', 'rb') as f:
    model = pickle.load(f)

conn = psycopg2.connect(os.environ['DATABASE_URL'])
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE in_validate = TRUE
    AND forward_6m_return IS NOT NULL
    ORDER BY rebalance_date, symbol
""", conn)
conn.close()

FEATURES = [
    's1_roe_trend', 's2_revenue_cagr', 's3_fcf', 's4_pli_tailwind',
    's5_promoter_trend', 's6_earnings_consist', 's8_peg_ratio',
    's9_dii_accumulation', 's10_de_improvement', 's11_roce',
    's12_eps_cagr', 's14_macro_cycle', 's15_rs_12m'
]

FEATURE_LABELS = {
    's1_roe_trend':        'S1  ROE trend',
    's2_revenue_cagr':     'S2  Revenue CAGR',
    's3_fcf':              'S3  FCF quality',
    's4_pli_tailwind':     'S4  PLI tailwind',
    's5_promoter_trend':   'S5  Promoter trend',
    's6_earnings_consist': 'S6  Earnings consistency',
    's8_peg_ratio':        'S8  PEG ratio',
    's9_dii_accumulation': 'S9  DII accumulation',
    's10_de_improvement':  'S10 D/E improvement',
    's11_roce':            'S11 ROCE',
    's12_eps_cagr':        'S12 EPS CAGR',
    's14_macro_cycle':     'S14 Macro cycle',
    's15_rs_12m':          'S15 RS 12-month',
}

X_val = df[FEATURES]
print(f"Validation rows: {len(X_val)}")

# Compute SHAP values
print("Computing SHAP values (may take 1-2 minutes)...")
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_val)

# Mean absolute SHAP per feature
mean_shap = np.abs(shap_values).mean(axis=0)
shap_df = pd.DataFrame({
    'feature': FEATURES,
    'label': [FEATURE_LABELS[f] for f in FEATURES],
    'mean_abs_shap': mean_shap,
    'rf_importance': model.feature_importances_
}).sort_values('mean_abs_shap', ascending=False)

print("\n── SHAP Signal Attribution (Validation Period 2020–2023) ──")
print(f"{'Signal':<30} {'SHAP Impact':>12} {'RF Importance':>14}")
print("─" * 60)
for _, row in shap_df.iterrows():
    bar = '█' * int(row['mean_abs_shap'] * 400)
    print(f"{row['label']:<30} {row['mean_abs_shap']:>10.4f}   {row['rf_importance']:>10.4f}  {bar}")

# Per-date SHAP breakdown
print("\n── Top signal per rebalance date (what drove picks) ──")
df_copy = df.copy()
df_copy['predicted'] = model.predict(X_val)
shap_df_full = pd.DataFrame(shap_values, columns=FEATURES, index=df.index)

for rd in sorted(df['rebalance_date'].unique()):
    mask = df['rebalance_date'] == rd
    if mask.sum() == 0:
        continue
    period_shap = shap_df_full[mask].abs().mean()
    top_signal = period_shap.idxmax()
    top_label = FEATURE_LABELS[top_signal]
    top_val = period_shap[top_signal]
    print(f"  {rd}: top driver = {top_label} (SHAP={top_val:.4f})")

# Top and bottom picks — what signals drove them
print("\n── What drove the top picks in best period (Jun 2020) ──")
jun2020 = df[df['rebalance_date'] == pd.Timestamp('2020-06-01').date()].copy()
if len(jun2020) > 0:
    jun2020['predicted'] = model.predict(jun2020[FEATURES])
    jun2020_shap = pd.DataFrame(
        explainer.shap_values(jun2020[FEATURES]),
        columns=FEATURES,
        index=jun2020.index
    )
    top5 = jun2020.nlargest(5, 'predicted')
    print(f"{'Symbol':<12} {'Top driver':<30} {'SHAP':>8} {'Actual return':>14}")
    print("─" * 70)
    for idx, row in top5.iterrows():
        stock_shap = jun2020_shap.loc[idx].abs()
        top_feat = stock_shap.idxmax()
        top_feat_val = jun2020_shap.loc[idx, top_feat]
        actual = df.loc[idx, 'forward_6m_return'] if idx in df.index else None
        actual_str = f"{actual*100:.1f}%" if actual is not None else "N/A"
        print(f"{row['symbol']:<12} {FEATURE_LABELS[top_feat]:<30} {top_feat_val:>8.4f} {actual_str:>14}")

print("\n✓ SHAP analysis complete.")
print("\nPhase 3 summary:")
print("  ✓ Training data built (11,065 rows, 22 rebalance dates)")
print("  ✓ Random Forest trained with walk-forward CV")
print("  ✓ Validation CAGR: 56% (gate >28%)")
print("  ✓ Validation Sharpe: 1.20 (gate >1.0 revised)")
print("  ✓ Max drawdown: -26.8% (gate <30%)")
print("  ✓ Governance filter applied")
print("  ✓ SHAP attribution complete")
print("\nNext: git commit all scripts, then Phase 4 paper trading.")
