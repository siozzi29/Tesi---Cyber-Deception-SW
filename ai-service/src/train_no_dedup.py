# ai-service/src/train_no_dedup.py
#
# ESPERIMENTO: training SENZA deduplicazione, per confronto con train.py.
# Lo scopo è dimostrare empiricamente il data leakage: le metriche sul test
# set saranno artificialmente più alte perché il modello "ricorda" richieste
# identiche viste in training. NON usare questo modello in produzione.

import pandas as pd
import numpy as np
from pathlib import Path
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, roc_curve, auc
from sklearn.model_selection import train_test_split
from src import preprocess
from src import features

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def extract_matrix(df):
    X_list = df.apply(lambda row: features.extract_features(
        row["url"], row["method"], row["content"], row["content_type"]
    ), axis=1)
    return np.array(X_list.tolist()), df["label"].values

def normalize_scores(raw_scores, min_bound, max_bound):
    normalized = (raw_scores - min_bound) / (max_bound - min_bound)
    return np.clip(normalized, 0.0, 1.0)

def main():
    print("=" * 60)
    print("  ESPERIMENTO: Training SENZA deduplicazione")
    print("  Obiettivo: dimostrare data leakage da duplicati")
    print("=" * 60)

    print("\n[1/6] Caricamento dataset (SENZA dedup)...")
    df_2010 = preprocess.load_csic2010(DATA_DIR / "csic2010.csv")
    df_ecml = preprocess.load_csic_ecml(DATA_DIR / "csic_ecml_final.csv")
    colonne_utili = ["url", "method", "content", "content_type", "label"]
    df_all = pd.concat([df_2010[colonne_utili], df_ecml[colonne_utili]], ignore_index=True)

    # *** NESSUNA DEDUPLICAZIONE ***
    print(f"      Righe totali mantenute: {len(df_all)} (duplicati inclusi)")

    dup_count = df_all.duplicated(subset=["method", "url", "content"]).sum()
    print(f"      Di cui righe duplicate: {dup_count} ({dup_count/len(df_all):.1%})")

    print("\n[2/6] Split train/val/test (stesso schema di train.py)...")
    df_normal    = df_all[df_all["label"] == 0]
    df_anomalous = df_all[df_all["label"] == 1]

    train_norm, temp_norm = train_test_split(df_normal,    test_size=0.4, random_state=42)
    val_norm,   test_norm = train_test_split(temp_norm,    test_size=0.5, random_state=42)
    val_anom,   test_anom = train_test_split(df_anomalous, test_size=0.5, random_state=42)

    df_train = train_norm
    df_val   = pd.concat([val_norm, val_anom])
    df_test  = pd.concat([test_norm, test_anom])

    print(f"      Train:      {len(df_train):>6} (solo normali)")
    print(f"      Validation: {len(df_val):>6} ({len(val_norm)} normali, {len(val_anom)} anomali)")
    print(f"      Test:       {len(df_test):>6} ({len(test_norm)} normali, {len(test_anom)} anomali)")

    # Stima di quante righe del test sono identiche a righe del train
    train_keys = set(zip(df_train["method"], df_train["url"], df_train["content"]))
    test_overlap = df_test.apply(
        lambda r: (r["method"], r["url"], r["content"]) in train_keys, axis=1
    ).sum()
    print(f"\n      *** OVERLAP train↔test: {test_overlap} righe del test set")
    print(f"          sono identiche a righe viste in training ({test_overlap/len(df_test):.1%}) ***")

    print("\n[3/6] Estrazione feature...")
    X_train, _      = extract_matrix(df_train)
    X_val,   y_val  = extract_matrix(df_val)
    X_test,  y_test = extract_matrix(df_test)

    print("\n[4/6] Training Isolation Forest (stessi iperparametri ottimali)...")
    # Usiamo gli stessi iperparametri scelti dal train.py con dedup
    params = {"n_estimators": 800, "max_samples": 1.0, "contamination": 0.01}
    model = IsolationForest(random_state=42, **params)
    model.fit(X_train)

    train_raw = -model.decision_function(X_train)
    min_bound, max_bound = float(train_raw.min()), float(train_raw.max())

    val_raw    = -model.decision_function(X_val)
    val_scores = normalize_scores(val_raw, min_bound, max_bound)

    fpr_v, tpr_v, ths_v = roc_curve(y_val, val_scores)
    valid_idx = np.where(fpr_v <= 0.01)[0]
    threshold = float(ths_v[valid_idx[-1]]) if len(valid_idx) > 0 else 0.5
    recall_val = float(tpr_v[valid_idx[-1]]) if len(valid_idx) > 0 else 0.0

    print(f"      Soglia ottimizzata: {threshold:.4f} (Recall su validation: {recall_val:.4f})")

    print("\n[5/6] Valutazione sul test set...")
    test_raw    = -model.decision_function(X_test)
    test_scores = normalize_scores(test_raw, min_bound, max_bound)
    y_pred      = (test_scores > threshold).astype(int)

    fpr_t, tpr_t, _ = roc_curve(y_test, test_scores)
    test_auc = auc(fpr_t, tpr_t)

    precision = precision_score(y_test, y_pred)
    recall    = recall_score(y_test, y_pred)
    f1        = f1_score(y_test, y_pred)

    print(f"      - Precision: {precision:.4f}")
    print(f"      - Recall:    {recall:.4f}")
    print(f"      - F1 Score:  {f1:.4f}")
    print(f"      - AUC ROC:   {test_auc:.4f}")

    print("\n[6/6] Riepilogo comparativo:")
    print("┌─────────────────────┬──────────────────────┬──────────────────────┐")
    print("│ Metrica             │ CON dedup (corretto) │ SENZA dedup (questo) │")
    print("├─────────────────────┼──────────────────────┼──────────────────────┤")
    print(f"│ Righe training      │ ~17.356              │ {len(df_train):>20} │")
    print(f"│ Soglia              │ 0.5908               │ {threshold:>20.4f} │")
    print(f"│ Precision           │ 0.9872               │ {precision:>20.4f} │")
    print(f"│ Recall              │ 0.3749               │ {recall:>20.4f} │")
    print(f"│ F1 Score            │ 0.5434               │ {f1:>20.4f} │")
    print(f"│ AUC ROC             │ 0.7726               │ {test_auc:>20.4f} │")
    print("└─────────────────────┴──────────────────────┴──────────────────────┘")
    print(f"\n  Il test set contiene {test_overlap} righe ({test_overlap/len(df_test):.1%}) già")
    print("  viste in training → qualsiasi metrica è gonfiata artificialmente.")
    print("\n  CONCLUSIONE: i duplicati causano data leakage. Le metriche")
    print("  senza dedup NON rappresentano la capacità di generalizzazione")
    print("  del modello su traffico reale mai visto prima.")

if __name__ == "__main__":
    main()
