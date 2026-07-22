# ai-service/src/train_supervised.py
#
# Confronto diretto con train.py (IsolationForest, unsupervised):
# qui alleniamo un RandomForest usando ANCHE le label anomale in training,
# non solo il traffico normale. Stesso preprocess/split concettuale, stesse
# feature, cosi' il confronto sulle metriche di test e' onesto.
#
# Uso: da dentro ai-service/  ->  python -m src.train_supervised

import numpy as np
from pathlib import Path
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from src import preprocess
from src import features

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)


def extract_matrix(df):
    X_list = df.apply(lambda row: features.extract_features(
        row["url"], row["method"], row["content"], row["content_type"]
    ), axis=1)
    return np.array(X_list.tolist()), df["label"].values


def main():
    print("[1/5] Caricamento dataset...")
    df_all = preprocess.deduplicate(
        __import__("pandas").concat([
            preprocess.load_csic2010(DATA_DIR / "csic2010.csv"),
            preprocess.load_csic_ecml(DATA_DIR / "csic_ecml_final.csv"),
        ], ignore_index=True)
    )

    # QUI la differenza chiave vs train.py: split classico 60/20/20 su TUTTO
    # il dataset (normali + anomali insieme), non solo sui normali. Il
    # modello vede esempi di attacco anche in training.
    print("[2/5] Split 60/20/20 (Random State 42, stratificato sulla label)...")
    df_train, df_temp = train_test_split(df_all, test_size=0.4, random_state=42, stratify=df_all["label"])
    df_val, df_test = train_test_split(df_temp, test_size=0.5, random_state=42, stratify=df_temp["label"])
    print(f"      Train: {len(df_train)} | Val: {len(df_val)} | Test: {len(df_test)}")

    print("[3/5] Estrazione feature...")
    X_train, y_train = extract_matrix(df_train)
    X_val, y_val = extract_matrix(df_val)
    X_test, y_test = extract_matrix(df_test)

    print("[4/5] Training RandomForest (class_weight='balanced' per lo sbilanciamento)...")
    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        class_weight="balanced",  # compensa normali >> anomali senza sottocampionare
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    # Soglia scelta su validation per coerenza col criterio di train.py
    # (qui usiamo 0.5 di default sulla probabilita', ma la lasciamo esplicita
    # cosi' e' facile allinearla a un target FPR come nell'altro script).
    val_proba = model.predict_proba(X_val)[:, 1]
    print(f"      AUC validation: {roc_auc_score(y_val, val_proba):.4f}")

    print("[5/5] Blind-test...")
    test_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (test_proba > 0.5).astype(int)

    print("      Metriche finali sul Test Set:")
    print(f"      - Precision: {precision_score(y_test, y_pred):.4f}")
    print(f"      - Recall:    {recall_score(y_test, y_pred):.4f}")
    print(f"      - F1 Score:  {f1_score(y_test, y_pred):.4f}")
    print(f"      - AUC ROC:   {roc_auc_score(y_test, test_proba):.4f}")

    joblib.dump(model, MODELS_DIR / "random_forest_supervised.joblib")
    print("\nSalvato in ai-service/models/random_forest_supervised.joblib")
    print("NOTA: non sostituisce isolation_forest.joblib, e' un modello parallelo per confronto in tesi.")


if __name__ == "__main__":
    main()