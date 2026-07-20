"""
Training pipeline - Isolation Forest
=========================================================================
Trasforma ogni richiesta HTTP grezza in un vettore di feature numeriche,
allena l'Isolation Forest SOLO su traffico "Normal" (classification == 0)
e valuta la capacità di isolare le richieste "Anomalous".

Le stesse feature (stesso ordine!) vengono ricalcolate in produzione da
features.py e main.py, così training e inferenza non possono divergere.
"""
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, confusion_matrix, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from features import FEATURE_ORDER, extract_features


def extract_features_from_row(row) -> dict:
    return extract_features(
        str(row["URL"]),
        str(row["Method"]),
        str(row["content"]),
        str(row.get("content-type", "")),
    )


def main() -> None:
    # ---------------------------------------------------------------------------
    # 1. CARICAMENTO DATASET
    # ---------------------------------------------------------------------------
    df = pd.read_csv("data/csic_database.csv")

    # La colonna 'classification' è già 0=Normal, 1=Anomalous: perfetta come y_true
    df = df.fillna("")

    # ---------------------------------------------------------------------------
    # 2. FEATURE ENGINEERING
    # ---------------------------------------------------------------------------
    print("Estrazione feature in corso...")
    features_df = pd.DataFrame([extract_features_from_row(row) for _, row in df.iterrows()])
    features_df = features_df.reindex(columns=FEATURE_ORDER, fill_value=0)
    y_true = df["classification"].astype(int)  # 0 = Normal, 1 = Anomalous

    print(features_df.describe().T)

    # ---------------------------------------------------------------------------
    # 3. SPLIT: alleniamo SOLO su traffico normale (comportamento nativo IF)
    # ---------------------------------------------------------------------------
    X_train_raw = features_df[y_true == 0]

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train_raw)
    X_all = scaler.transform(features_df)

    # ---------------------------------------------------------------------------
    # 4. TRAINING
    # ---------------------------------------------------------------------------
    model = IsolationForest(
        n_estimators=800,
        max_samples=512,
        max_features=1.0,
        contamination=0.2,
        random_state=42,
        n_jobs=-1,
    )

    print("\nTraining Isolation Forest...")
    model.fit(X_train)

    # ---------------------------------------------------------------------------
    # 5. VALUTAZIONE
    # ---------------------------------------------------------------------------
    raw_preds = model.predict(X_all)
    y_pred = np.where(raw_preds == -1, 1, 0)

    print("\n=== Baseline (contamination di default) ===")
    print(classification_report(y_true, y_pred, digits=3))
    print("Confusion matrix:")
    print(confusion_matrix(y_true, y_pred))

    # ---------------------------------------------------------------------------
    # 5b. SOGLIA "PARANOICA": FPR massimo 1% sul traffico sano
    # ---------------------------------------------------------------------------
    raw_scores = model.decision_function(X_all)
    risk_scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

    TARGET_FPR = 0.01
    normal_scores = risk_scores[y_true == 0]
    paranoid_threshold = np.percentile(normal_scores, (1 - TARGET_FPR) * 100)
    y_pred_paranoid = (risk_scores > paranoid_threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_true, y_pred_paranoid).ravel()
    actual_fpr = fp / (fp + tn)

    print(f"\n=== Soglia paranoica (target FPR <= {TARGET_FPR:.0%}) ===")
    print(f"Soglia impostata: {paranoid_threshold:.4f}")
    print(f"FPR effettivo ottenuto: {actual_fpr:.4%}  (Falsi Positivi: {fp} su {fp + tn} traffico sano)")
    print(f"Precision: {precision_score(y_true, y_pred_paranoid):.3f} | "
          f"Recall: {recall_score(y_true, y_pred_paranoid):.3f} | "
          f"F1: {f1_score(y_true, y_pred_paranoid):.3f}")
    print("\n=== Classification report a soglia paranoica ===")
    print(classification_report(y_true, y_pred_paranoid, digits=3))
    print("Confusion matrix:")
    print(confusion_matrix(y_true, y_pred_paranoid))

    RISK_THRESHOLD = float(paranoid_threshold)

    # ---------------------------------------------------------------------------
    # 6. SERIALIZZAZIONE
    # ---------------------------------------------------------------------------
    os.makedirs("models", exist_ok=True)
    joblib.dump(model, "models/isolation_forest.joblib")
    joblib.dump(scaler, "models/scaler.joblib")
    joblib.dump(list(FEATURE_ORDER), "models/feature_order.joblib")
    joblib.dump(RISK_THRESHOLD, "models/risk_threshold.joblib")
    joblib.dump({"min": float(raw_scores.min()), "max": float(raw_scores.max())}, "models/score_bounds.joblib")

    print("\nModello, scaler, ordine feature, soglia e bound normalizzazione salvati in models/")
    print(f"Soglia operativa (RISK_THRESHOLD): {RISK_THRESHOLD:.4f}")
    print(f"Score bounds: min={raw_scores.min():.4f}, max={raw_scores.max():.4f}")
    print("Ordine feature (fondamentale per replicarlo in Go):")
    print(list(FEATURE_ORDER))


if __name__ == "__main__":
    main()
