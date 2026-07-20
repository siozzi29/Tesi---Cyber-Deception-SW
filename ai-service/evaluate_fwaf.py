"""
evaluate_fwaf.py - Cross-dataset generalization test.

NON riallena il modello. Prende l'Isolation Forest gia' allenato su CSIC2010
(ieri) e lo testa su un dataset completamente diverso (FWAF) per misurare
quanto generalizza oltre i dati su cui e' nato.

Limite noto del dataset FWAF: contiene solo stringhe URL/query, non
un'intera richiesta HTTP strutturata. Trattiamo quindi ogni riga come se
fosse una GET senza corpo (method="GET", content="", content_type="").
"""
import os

import joblib
import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, precision_score, recall_score, f1_score

from features import extract_features, features_to_vector, FEATURE_ORDER

MODELS_DIR = "models"
FWAF_DIR = "data/fwaf"


def load_fwaf_file(path: str) -> list:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    # Dedup, come fa anche lo script originale del dataset
    return list(set(line.strip() for line in lines if line.strip()))


def build_feature_matrix(urls: list) -> np.ndarray:
    vectors = []
    for url in urls:
        f = extract_features(url, method="GET", content="", content_type="")
        vectors.append(features_to_vector(f))
    return np.array(vectors)


def main():
    print("Caricamento modello allenato su CSIC2010...")
    model = joblib.load(os.path.join(MODELS_DIR, "isolation_forest.joblib"))
    scaler = joblib.load(os.path.join(MODELS_DIR, "scaler.joblib"))
    saved_order = joblib.load(os.path.join(MODELS_DIR, "feature_order.joblib"))
    threshold = joblib.load(os.path.join(MODELS_DIR, "risk_threshold.joblib"))
    bounds = joblib.load(os.path.join(MODELS_DIR, "score_bounds.joblib"))

    assert list(saved_order) == FEATURE_ORDER, "MISMATCH feature order!"

    print("Caricamento dataset FWAF...")
    bad_queries = load_fwaf_file(os.path.join(FWAF_DIR, "badqueries.txt"))
    good_queries = load_fwaf_file(os.path.join(FWAF_DIR, "goodqueries.txt"))
    print(f"  {len(bad_queries)} query malevole, {len(good_queries)} query benigne")

    # Per velocita' e per bilanciare il confronto, campioniamo le query buone
    # (altrimenti 1.3M righe ci mettono un'eternita' e sbilanciano il report)
    rng = np.random.default_rng(42)
    if len(good_queries) > 50000:
        idx = rng.choice(len(good_queries), size=50000, replace=False)
        good_queries = [good_queries[i] for i in idx]
        print(f"  Campionate 50.000 query benigne su {len(idx)} per il test")

    print("Calcolo feature e risk score...")
    all_urls = bad_queries + good_queries
    y_true = np.array([1] * len(bad_queries) + [0] * len(good_queries))  # 1=anomalo, 0=normale

    X = build_feature_matrix(all_urls)
    X_scaled = scaler.transform(X)
    raw_scores = model.decision_function(X_scaled)
    risk_scores = np.clip(1 - (raw_scores - bounds["min"]) / (bounds["max"] - bounds["min"]), 0, 1)

    y_pred = (risk_scores > threshold).astype(int)

    fp = np.sum((y_pred == 1) & (y_true == 0))
    tn = np.sum((y_pred == 0) & (y_true == 0))
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    print("\n" + "=" * 70)
    print("RISULTATI CROSS-DATASET: modello CSIC2010 valutato su FWAF")
    print("=" * 70)
    print(f"Soglia usata (identica a CSIC2010, nessun re-training): {threshold:.4f}")
    print(f"FPR su traffico benigno FWAF: {fpr:.4%}  (per confronto: 1.00% su CSIC2010)")
    print(f"Precision: {precision_score(y_true, y_pred):.3f} | "
          f"Recall: {recall_score(y_true, y_pred):.3f} | "
          f"F1: {f1_score(y_true, y_pred):.3f}")
    print("\nClassification report:")
    print(classification_report(y_true, y_pred, target_names=["Normale", "Anomalo"], digits=3))
    print("Confusion matrix:")
    print(confusion_matrix(y_true, y_pred))


if __name__ == "__main__":
    main()