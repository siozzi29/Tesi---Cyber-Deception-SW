# ai-service/src/train.py

import pandas as pd
import numpy as np
from pathlib import Path
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, roc_curve, auc
from sklearn.model_selection import train_test_split, KFold
from src import preprocess
from src import features

# Calcolo dinamico delle directory per massima portabilità
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(exist_ok=True)

def extract_matrix(df):
    """Estrae la matrice delle feature X e il vettore delle label y usando i 4 campi rigorosi."""
    # Le feature derivano strettamente da url, method, content e content_type per evitare skew in produzione.
    X_list = df.apply(lambda row: features.extract_features(
        row["url"], row["method"], row["content"], row["content_type"]
    ), axis=1)
    return np.array(X_list.tolist()), df["label"].values

def normalize_scores(raw_scores, min_bound, max_bound):
    """Normalizza i punteggi raw (negativi nel decision_function) nell'intervallo [0, 1]."""
    # Si applica un clipping per evitare che anomalie estreme in test superino il rischio 1.0.
    normalized = (raw_scores - min_bound) / (max_bound - min_bound)
    return np.clip(normalized, 0.0, 1.0)

def main():
    print("[1/8] Caricamento e preparazione dataset...")
    df_2010 = preprocess.load_csic2010(DATA_DIR / "csic2010.csv")
    df_ecml = preprocess.load_csic_ecml(DATA_DIR / "csic_ecml_final.csv")
    df_all = pd.concat([df_2010, df_ecml], ignore_index=True)
    df_dedup = preprocess.deduplicate(df_all)
    
    print(f"[2/8] Creazione split a 3 vie (Random State 42)...")
    df_normal = df_dedup[df_dedup["label"] == 0]
    df_anomalous = df_dedup[df_dedup["label"] == 1]
    
    # Split campioni normali: 60% Train, 20% Validation, 20% Test
    train_norm, temp_norm = train_test_split(df_normal, test_size=0.4, random_state=42)
    val_norm, test_norm = train_test_split(temp_norm, test_size=0.5, random_state=42)
    
    # Split campioni anomali: 0% Train, 50% Validation, 50% Test
    val_anom, test_anom = train_test_split(df_anomalous, test_size=0.5, random_state=42)
    
    df_train = train_norm
    df_val = pd.concat([val_norm, val_anom])
    df_test = pd.concat([test_norm, test_anom])
    
    print(f"      Train: {len(df_train)} (Solo normali)")
    print(f"      Validation: {len(df_val)} ({len(val_norm)} normali, {len(val_anom)} anomali)")
    print(f"      Test: {len(df_test)} ({len(test_norm)} normali, {len(test_anom)} anomali)")
    
    print("[3/8] Estrazione feature vettoriali...")
    X_train, y_train = extract_matrix(df_train)
    X_val, y_val = extract_matrix(df_val)
    X_test, y_test = extract_matrix(df_test)
    
    print("[4/8] Addestramento Isolation Forest (Grid Search su Validation)...")
    hyperparams = [
        {"n_estimators": n, "max_samples": m, "contamination": c}
        for n in [800]
        for m in [1.0]
        for c in [0.01, 0.02, 0.03,0.05, 0.08, 0.1,]
    ]
    
    best_model = None
    best_recall = -1
    best_threshold = 0
    best_bounds = (0, 0)
    best_params = {}
    
    for i, params in enumerate(hyperparams, 1):
        print(f"      [{i}/{len(hyperparams)}] Provo {params}...")
        try:
            # Fit rigoroso solo sui dati normali con gestione degli errori sui parametri
            model = IsolationForest(random_state=42, **params)
            model.fit(X_train)
        except ValueError as e:
            print(f"      [SKIP] {params} -> {e}")
            continue
        
        # Scikit-Learn decision_function: positivo = normale, negativo = anomalo.
        # Invertiamo il segno per avere una logica in cui rischio alto = maggiore anomalia.
        train_raw = -model.decision_function(X_train)
        min_bound, max_bound = float(train_raw.min()), float(train_raw.max())
        
        val_raw = -model.decision_function(X_val)
        val_scores = normalize_scores(val_raw, min_bound, max_bound)
        
        # Ricerca della soglia su Validation con target FPR <= 0.01
        fpr, tpr, thresholds = roc_curve(y_val, val_scores)
        valid_indices = np.where(fpr <= 0.01)[0]
        
        if len(valid_indices) > 0:
            idx = valid_indices[-1]
            threshold = thresholds[idx]
            recall = tpr[idx]
            if recall > best_recall:
                best_recall = recall
                best_threshold = threshold
                best_model = model
                best_bounds = (min_bound, max_bound)
                best_params = params
                
    print(f"      Iperparametri scelti: {best_params}")
    print(f"[5/8] Soglia di rischio ottimizzata trovata: {best_threshold:.4f} (Recall validazione: {best_recall:.4f})")
    
    print("[6/8] Valutazione blind-test (Eseguita 1 sola volta)...")
    test_raw = -best_model.decision_function(X_test)
    test_scores = normalize_scores(test_raw, best_bounds[0], best_bounds[1])
    
    y_pred = (test_scores > best_threshold).astype(int)
    fpr_test, tpr_test, _ = roc_curve(y_test, test_scores)
    test_auc = auc(fpr_test, tpr_test)
    
    print(f"      Metriche finali sul Test Set:")
    print(f"      - Precision: {precision_score(y_test, y_pred):.4f}")
    print(f"      - Recall:    {recall_score(y_test, y_pred):.4f}")
    print(f"      - F1 Score:  {f1_score(y_test, y_pred):.4f}")
    print(f"      - AUC ROC:   {test_auc:.4f}")
    
    print("[7/8] Salvataggio dei joblib nella cartella models...")
    joblib.dump(best_model, MODELS_DIR / "isolation_forest.joblib")
    joblib.dump(float(best_threshold), MODELS_DIR / "risk_threshold.joblib")
    joblib.dump(best_bounds, MODELS_DIR / "score_bounds.joblib")
    
    print("[8/8] Esecuzione k-fold per verifica stabilità soglia (Opzionale)...")
    seeds = [10, 42, 123, 777, 999]
    kfold_thresholds = []
    kfold_recalls = []
    
    for seed in seeds:
        # Replicazione rapida della suddivisione e tuning per valutare la varianza
        t_n, temp_n = train_test_split(df_normal, test_size=0.4, random_state=seed)
        v_n, _ = train_test_split(temp_n, test_size=0.5, random_state=seed)
        v_a, _ = train_test_split(df_anomalous, test_size=0.5, random_state=seed)
        
        X_t, _ = extract_matrix(t_n)
        X_v, y_v = extract_matrix(pd.concat([v_n, v_a]))
        
        kf_model = IsolationForest(random_state=seed, **best_params)
        kf_model.fit(X_t)
        
        kf_t_raw = -kf_model.decision_function(X_t)
        kf_min, kf_max = kf_t_raw.min(), kf_t_raw.max()
        
        kf_v_raw = -kf_model.decision_function(X_v)
        kf_v_scores = normalize_scores(kf_v_raw, kf_min, kf_max)
        
        fpr, tpr, ths = roc_curve(y_v, kf_v_scores)
        valid_idx = np.where(fpr <= 0.01)[0]
        if len(valid_idx) > 0:
            kfold_thresholds.append(ths[valid_idx[-1]])
            kfold_recalls.append(tpr[valid_idx[-1]])
            
    print(f"      Soglia media: {np.mean(kfold_thresholds):.4f} (Deviazione Standard: {np.std(kfold_thresholds):.4f})")
    print(f"      Recall medio: {np.mean(kfold_recalls):.4f} (Deviazione Standard: {np.std(kfold_recalls):.4f})")
    print("\nProcesso di ML completato con successo. Dati e modelli salvati e pronti per FastAPI.")

if __name__ == "__main__":
    main()