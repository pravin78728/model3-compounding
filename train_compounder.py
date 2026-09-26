"""
train_compounder.py
Trains RF on compounder signals — no momentum, quality-growth focus.
"""
import os
import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
import pickle
import warnings
warnings.filterwarnings('ignore')

load_dotenv()
conn = psycopg2.connect(os.environ['DATABASE_URL'])

print("Loading training data...")
df = pd.read_sql("""
    SELECT * FROM model3_training_data
    WHERE forward_6m_return IS NOT NULL
""", conn)
conn.close()

print(f"  Total rows with labels: {len(df)}")
print(f"  Train rows:    {df['in_train'].sum()}")
print(f"  Validate rows: {df['in_validate'].sum()}")

FEATURES = [
    'c1_eps_cagr', 'c2_eps_accel', 'c3_roe_quality', 'c4_fcf_quality',
    'c5_rev_cagr', 'c6_margin_expan', 'c7_roce_trend', 'c8_earn_consist',
    'c9_de_improve', 'c10_peg', 'c11_promoter', 'c12_macro', 'c13_pli'
]
TARGET = 'forward_6m_return'

df[TARGET] = df[TARGET].clip(-0.8, 3.0)
train_df = df[df['in_train']].copy()
val_df   = df[df['in_validate']].copy()

X_train = train_df[FEATURES]
y_train = train_df[TARGET]
X_val   = val_df[FEATURES]
y_val   = val_df[TARGET]

print(f"\nTrain shape:    {X_train.shape}")
print(f"Validate shape: {X_val.shape}")
print(f"Signal coverage (non-null %):")
for f in FEATURES:
    pct = X_train[f].notna().mean() * 100
    print(f"  {f:<20} {pct:.1f}%")

print("\n── Walk-forward cross-validation ──")
rebal_dates = sorted(train_df['rebalance_date'].unique())
fold_maes, fold_corrs = [], []

for i in range(4, len(rebal_dates)):
    past_dates = rebal_dates[:i]
    next_date  = rebal_dates[i]
    fold_train = train_df[train_df['rebalance_date'].isin(past_dates)]
    fold_test  = train_df[train_df['rebalance_date'] == next_date]
    if len(fold_test) < 10: continue

    rf = RandomForestRegressor(
        n_estimators=200, max_depth=6, min_samples_leaf=10,
        max_features=0.6, random_state=42, n_jobs=-1)
    rf.fit(fold_train[FEATURES], fold_train[TARGET])
    preds = rf.predict(fold_test[FEATURES])
    mae  = mean_absolute_error(fold_test[TARGET], preds)
    corr = np.corrcoef(fold_test[TARGET], preds)[0,1] if len(fold_test) > 1 else 0
    fold_maes.append(mae)
    fold_corrs.append(corr)
    print(f"  Fold {i}: {next_date} | n={len(fold_test)} | MAE={mae:.3f} | corr={corr:.3f}")

print(f"\n  Avg MAE:  {np.mean(fold_maes):.3f}")
print(f"  Avg corr: {np.mean(fold_corrs):.3f}")

print("\n── Training final model ──")
final_model = RandomForestRegressor(
    n_estimators=500, max_depth=6, min_samples_leaf=10,
    max_features=0.5, random_state=42, n_jobs=-1)
final_model.fit(X_train, y_train)
print("  ✓ Model trained")

print("\n── Feature importances ──")
importances = pd.Series(final_model.feature_importances_, index=FEATURES)
for feat, imp in importances.sort_values(ascending=False).items():
    bar = '█' * int(imp * 200)
    print(f"  {feat:<20} {imp:.4f}  {bar}")

print("\n── Validation (2020–2023) ──")
val_preds = final_model.predict(X_val)
val_mae   = mean_absolute_error(y_val, val_preds)
val_corr  = np.corrcoef(y_val, val_preds)[0,1]

val_df = val_df.copy()
val_df['predicted'] = val_preds
val_df['actual']    = y_val.values
top_q    = val_df.nlargest(int(len(val_df)*0.25), 'predicted')
bottom_q = val_df.nsmallest(int(len(val_df)*0.25), 'predicted')

print(f"  MAE:        {val_mae:.3f}")
print(f"  Corr:       {val_corr:.3f}")
print(f"  Top-25%:    {top_q['actual'].mean()*100:.1f}%")
print(f"  Bottom-25%: {bottom_q['actual'].mean()*100:.1f}%")
print(f"  Lift:       {(top_q['actual'].mean()-bottom_q['actual'].mean())*100:.1f}%")

print("\n  Per period:")
for rd in sorted(val_df['rebalance_date'].unique()):
    sub = val_df[val_df['rebalance_date']==rd]
    top25 = sub.nlargest(25, 'predicted')
    print(f"    {rd}: top-25 avg={top25['actual'].mean()*100:.1f}%")

with open('model3_rf.pkl', 'wb') as f:
    pickle.dump(final_model, f)
print("\n✓ Compounder model saved to model3_rf.pkl")
