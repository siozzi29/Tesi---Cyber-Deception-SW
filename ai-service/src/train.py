# ai-service/src/train.py

import pandas as pd
import numpy as np
from pathlib import Path
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.decomposition import PCA
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
    print("[1/9] Caricamento e preparazione dataset (DOMAIN-SPECIFIC FINE-TUNING)...")
    df_2010 = preprocess.load_csic2010(DATA_DIR / "csic2010.csv")
    df_ecml = preprocess.load_csic_ecml(DATA_DIR / "csic_ecml_final.csv")
    colonne_utili = ["url", "method", "content", "content_type", "label"]    
    
    df_2010 = df_2010[colonne_utili] 
    df_ecml = df_ecml[colonne_utili]
    df_all_csic = pd.concat([df_2010, df_ecml], ignore_index=True)
    
    # 1. SCARTIAMO IL TRAFFICO NORMALE CSIC (Teniamo solo gli attacchi label == 1)
    df_csic_attacks = df_all_csic[df_all_csic["label"] == 1]
    df_attacks_dedup = preprocess.deduplicate(df_csic_attacks)
    
    # 2. CARICHIAMO IL TRAFFICO WORDPRESS (L'UNICO TRAFFICO NORMALE CHE CI INTERESSA)
    df_wp = preprocess.load_wordpress_traffic(DATA_DIR / "wordpress_normal.csv")
    if not df_wp.empty:
        df_wp = df_wp[colonne_utili]
        # Oversampling dinamico rimosso poichè il dataset CSV (con data augmentation) 
        # ha ormai superato abbondantemente la soglia dei 14.000 attacchi.
        df_wp_weighted = df_wp.copy()
        print(f"      Incluso dataset WP (Solo Normali): {len(df_wp_weighted)} righe")
    else:
        df_wp_weighted = pd.DataFrame(columns=colonne_utili)
        
    df_dedup = pd.concat([df_attacks_dedup, df_wp_weighted], ignore_index=True)
    print(f"      Totale Dataset Ibrido (Attacchi CSIC + Normale WP): {len(df_dedup)} righe")
    
    print(f"[2/9] Creazione split a 3 vie (Random State 42)...")
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
    
    print("[3/9] Estrazione feature vettoriali...")
    X_train, y_train = extract_matrix(df_train)
    X_val, y_val = extract_matrix(df_val)
    X_test, y_test = extract_matrix(df_test)
    
    print("[4/9] Addestramento Isolation Forest (Grid Search su Validation)...")
    hyperparams = [
        {"n_estimators": 100, "max_samples": 1.0, "contamination": 0.01},
        {"n_estimators": 200, "max_samples": 1.0, "contamination": 0.05},
        {"n_estimators": 300, "max_samples": 1.0, "contamination": 0.1},
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
        val_raw = -model.decision_function(X_val)

        # FIX: Se usassimo max_bound dal solo training set (tutto traffico normale), 
        # spalmeremmo il traffico normale su tutto lo spettro [0, 1]. Includendo 
        # le anomalie di X_val nel calcolo del massimo, le richieste normali 
        # rimarranno confinate a valori molto bassi (es. 0.1 - 0.2), mentre gli 
        # attacchi schizzeranno verso lo 0.9 - 1.0.
        min_bound = float(min(train_raw.min(), val_raw.min()))
        max_bound = float(val_raw.max())
        
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
    print(f"[5/9] Soglia di rischio ottimizzata trovata: {best_threshold:.4f} (Recall validazione: {best_recall:.4f})")
    
    print("[6/9] Valutazione blind-test (Eseguita 1 sola volta)...")
    test_raw = -best_model.decision_function(X_test)
    test_scores = normalize_scores(test_raw, best_bounds[0], best_bounds[1])
    
    y_pred = (test_scores > best_threshold).astype(int)
    fpr_test, tpr_test, thresholds_test = roc_curve(y_test, test_scores)
    test_auc = auc(fpr_test, tpr_test)
    
    print(f"      Metriche finali sul Test Set:")
    print(f"      - Precision: {precision_score(y_test, y_pred):.4f}")
    print(f"      - Recall:    {recall_score(y_test, y_pred):.4f}")
    print(f"      - F1 Score:  {f1_score(y_test, y_pred):.4f}")
    print(f"      - AUC ROC:   {test_auc:.4f}")
    
    print("[7/9] Salvataggio dei joblib nella cartella models...")
    joblib.dump(best_model, MODELS_DIR / "isolation_forest.joblib")
    joblib.dump(float(best_threshold), MODELS_DIR / "risk_threshold.joblib")
    joblib.dump(best_bounds, MODELS_DIR / "score_bounds.joblib")
    
    print("[8/9] Esecuzione k-fold...")
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
        kf_v_raw = -kf_model.decision_function(X_v)
        
        kf_min = float(min(kf_t_raw.min(), kf_v_raw.min()))
        kf_max = float(kf_v_raw.max())
        
        kf_v_scores = normalize_scores(kf_v_raw, kf_min, kf_max)
        
        fpr, tpr, ths = roc_curve(y_v, kf_v_scores)
        valid_idx = np.where(fpr <= 0.01)[0]
        if len(valid_idx) > 0:
            kfold_thresholds.append(ths[valid_idx[-1]])
            kfold_recalls.append(tpr[valid_idx[-1]])
            
    print(f"      Soglia media: {np.mean(kfold_thresholds):.4f} (Deviazione Standard: {np.std(kfold_thresholds):.4f})")
    print(f"      Recall medio: {np.mean(kfold_recalls):.4f} (Deviazione Standard: {np.std(kfold_recalls):.4f})")
    
    print("[9/9] Generazione dei grafici di addestramento (Distribuzione e Bar Chart)...")
    
    # --- Grafico 1: Distribuzione degli score (Semplicissimo) ---
    plt.figure(figsize=(10, 6))
    
    scores_normal = test_scores[y_test == 0]
    scores_anomalous = test_scores[y_test == 1]
    
    # Colori base: verde (buono), rosso (cattivo)
    sns.histplot(scores_normal, bins=50, color="#2ecc71", alpha=0.7, label="Traffico Normale", stat="density", kde=False)
    sns.histplot(scores_anomalous, bins=50, color="#e74c3c", alpha=0.7, label="Attacchi Reali", stat="density", kde=False)
    
    plt.axvline(x=best_threshold, color='black', linestyle='--', linewidth=3, label=f'Soglia di Blocco ({best_threshold:.4f})')
    
    plt.title("Livello di Rischio Assegnato dal Modello (Test Set)", fontsize=14)
    plt.xlabel("Punteggio di Rischio (0 = Totalmente Sicuro, 1 = Attacco Certo)", fontsize=12)
    plt.ylabel("Quantità di richieste", fontsize=12)
    plt.legend(fontsize=11)
    plt.grid(axis='y', linestyle="--", alpha=0.4)
    plt.savefig(MODELS_DIR / "distribuzione_score.png", dpi=300, bbox_inches='tight')
    plt.close()

    # --- Grafico 2: Esito della Classificazione (Bar Chart Intuitivo) ---
    # Mostra brutalmente cosa viene bloccato e cosa passa.
    normali_totali = len(scores_normal)
    normali_bloccati = np.sum(scores_normal > best_threshold)
    normali_passati = normali_totali - normali_bloccati
    
    attacchi_totali = len(scores_anomalous)
    attacchi_bloccati = np.sum(scores_anomalous > best_threshold)
    attacchi_passati = attacchi_totali - attacchi_bloccati
    
    perc_norm_passati = (normali_passati / normali_totali) * 100
    perc_norm_bloccati = (normali_bloccati / normali_totali) * 100
    perc_att_passati = (attacchi_passati / attacchi_totali) * 100
    perc_att_bloccati = (attacchi_bloccati / attacchi_totali) * 100

    print("\n      --- BREAKDOWN DETTAGLIATO (Richiesta da appunti) ---")
    print(f"      TRAFFICO LEGITTIMO (Valori Negativi) - {normali_totali} richieste totali nel test set:")
    print(f"      - Veri Negativi (TN) - Fatti Passare: {normali_passati} ({perc_norm_passati:.2f}%)")
    print(f"      - Falsi Positivi (FP) - Bloccati per Errore: {normali_bloccati} ({perc_norm_bloccati:.2f}%)")
    print("")
    print(f"      ATTACCHI REALI (Valori Positivi) - {attacchi_totali} richieste totali nel test set:")
    print(f"      - Veri Positivi (TP) - Bloccati dal WAF: {attacchi_bloccati} ({perc_att_bloccati:.2f}%)")
    print(f"      - Falsi Negativi (FN) - Fatti Passare: {attacchi_passati} ({perc_att_passati:.2f}%)")
    print("      --------------------------------------------------")

    # NOVITA': Stampa a video quali attacchi esatti stanno passando (Falsi Negativi)
    if attacchi_passati > 0:
        print("\n      [!] IDENTIFICAZIONE DEI FALSI NEGATIVI (Primi 15):")
        # Ricaviamo il sotto-dataframe degli attacchi nel test set
        df_test_anomalous = df_test[df_test["label"] == 1]
        
        # Gli attacchi che sono passati sono quelli in cui score <= best_threshold
        buchi_mask = scores_anomalous <= best_threshold
        df_buchi = df_test_anomalous[buchi_mask]
        
        i = 0
        for _, row in df_buchi.iterrows():
            if i >= 15:
                break
            # Stampiamo metodo e url troncato a 100 caratteri
            url_str = str(row['url'])
            if len(url_str) > 100:
                url_str = url_str[:97] + "..."
            print(f"      - {row['method']} {url_str}")
            i += 1
    
    # Stampa a video quali richieste legittime vengono bloccate (Falsi Positivi)
    if normali_bloccati > 0:
        print("\n      [!] IDENTIFICAZIONE DEI FALSI POSITIVI (Primi 15):")
        df_test_normal = df_test[df_test["label"] == 0]
        fp_mask = scores_normal > best_threshold
        df_fp = df_test_normal[fp_mask]
        
        i = 0
        for _, row in df_fp.iterrows():
            if i >= 15:
                break
            url_str = str(row['url'])
            if len(url_str) > 100:
                url_str = url_str[:97] + "..."
            print(f"      - {row['method']} {url_str}")
            i += 1
            
    print("      --------------------------------------------------")

    labels = ['Traffico Legittimo\n(Valori Negativi)', 'Attacchi Reali\n(Valori Positivi)']
    passati = [perc_norm_passati, perc_att_passati]
    bloccati = [perc_norm_bloccati, perc_att_bloccati]

    x = np.arange(len(labels))
    width = 0.35

    plt.figure(figsize=(10, 7))
    
    # Disegno le barre individualmente per gestire i colori semantici (Verde=Giusto, Rosso=Sbagliato)
    # 1. Traffico Legittimo
    b1_tn = plt.bar(x[0] - width/2, passati[0], width, color='#2ecc71') # TN (Corretto -> Verde)
    b2_fp = plt.bar(x[0] + width/2, bloccati[0], width, color='#e74c3c') # FP (Errore -> Rosso)
    
    # 2. Attacchi Reali
    b3_fn = plt.bar(x[1] - width/2, passati[1], width, color='#e74c3c') # FN (Errore -> Rosso)
    b4_tp = plt.bar(x[1] + width/2, bloccati[1], width, color='#2ecc71') # TP (Corretto -> Verde)

    plt.ylabel('Percentuale (%)', fontsize=12)
    plt.title("Matrice di Confusione / Esito Classificazione (Test Set)", fontsize=14)
    plt.xticks(x, labels, fontsize=12, fontweight='bold')
    plt.ylim(0, 115) # Spazio per le etichette in cima
    
    # Legenda personalizzata
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#2ecc71', label='Azione Corretta (Sicuro)'),
        Patch(facecolor='#e74c3c', label='Azione Errata (Rischio)')
    ]
    plt.legend(handles=legend_elements, fontsize=11)

    # Scrive i numeri esatti e le etichette formali sopra le colonne
    # Barra 1: TN
    plt.text(x[0] - width/2, passati[0] + 1.5, f'Veri Negativi\n(TN)\n{passati[0]:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#1e8449')
    # Barra 2: FP
    plt.text(x[0] + width/2, bloccati[0] + 1.5, f'Falsi Positivi\n(FP)\n{bloccati[0]:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#922b21')
    # Barra 3: FN
    plt.text(x[1] - width/2, passati[1] + 1.5, f'Falsi Negativi\n(FN)\n{passati[1]:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#922b21')
    # Barra 4: TP
    plt.text(x[1] + width/2, bloccati[1] + 1.5, f'Veri Positivi\n(TP)\n{bloccati[1]:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold', color='#1e8449')

    plt.grid(axis='y', linestyle="--", alpha=0.3)
    plt.savefig(MODELS_DIR / "esito_classificazione.png", dpi=300, bbox_inches='tight')
    plt.close()

    print("\nProcesso di ML completato con successo. Grafici semplici pronti per la tesi.")

if __name__ == "__main__":
    main()