"""
Training pipeline - Isolation Forest su CSIC 2010 (WAAP Cyber Deception)
=========================================================================
Trasforma ogni richiesta HTTP grezza in un vettore di feature numeriche,
allena l'Isolation Forest SOLO su traffico "Normal" (classification == 0)
e valuta la capacità di isolare le richieste "Anomalous".

Le stesse feature (stesso ordine!) andranno ricalcolate in Go dentro
pkg/aiclient prima di chiamare l'endpoint FastAPI /score.
"""
import math
import os
import re
from collections import Counter

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
from urllib.parse import urlparse, parse_qs, unquote

# ---------------------------------------------------------------------------
# 1. CARICAMENTO DATASET
# ---------------------------------------------------------------------------
df = pd.read_csv("data/csic_database.csv")

# La colonna 'classification' è già 0=Normal, 1=Anomalous: perfetta come y_true
df = df.fillna("")  # NaN nei campi opzionali (content, content-type...) -> stringa vuota


# ---------------------------------------------------------------------------
# 2. FEATURE ENGINEERING
# ---------------------------------------------------------------------------
SQLI_XSS_TOKENS = [
    "select", "union", "drop", "insert", "--", "or 1=1", "' or", "\"or",
    "<script", "onerror=", "onload=", "alert(", "../", "..\\", "etc/passwd",
    "cmd=", "exec(", "%00", "waitfor", "sleep(",
]


def shannon_entropy(s: str) -> float:
    """Entropia di Shannon: le stringhe di attacco (payload offuscati/encodati)
    tendono ad avere entropia diversa dal traffico applicativo normale."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def count_special_chars(s: str) -> int:
    return len(re.findall(r"[^a-zA-Z0-9\s]", s))


def extract_features(row) -> dict:
    raw_url = str(row["URL"])
    # La colonna URL contiene anche " HTTP/1.1" in coda: lo rimuoviamo
    url = raw_url.replace(" HTTP/1.1", "").strip()
    decoded_url = unquote(url)

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    content = str(row["content"])
    method = str(row["Method"])
    user_agent = str(row["User-Agent"])
    cookie = str(row["cookie"])

    combined_payload = decoded_url + " " + content  # per lo scan di token sospetti
    combined_lower = combined_payload.lower()

    return {
        # --- Struttura URL ---
        "url_length": len(url),
        "path_length": len(parsed.path),
        "path_depth": parsed.path.count("/"),
        "num_params": len(query_params),
        "query_length": len(parsed.query),

        # --- Composizione caratteri (segnali di offuscamento/injection) ---
        "num_digits": sum(c.isdigit() for c in decoded_url),
        "num_special_chars_url": count_special_chars(decoded_url),
        "num_uppercase": sum(c.isupper() for c in url),
        "url_entropy": shannon_entropy(decoded_url),

        # --- Body / content ---
        "content_length": len(content),
        "has_content": 1 if content else 0,
        "num_special_chars_content": count_special_chars(content),
        "content_entropy": shannon_entropy(content),

        # --- Metodo HTTP (encoding semplice ordinale) ---
        "method_get": 1 if method == "GET" else 0,
        "method_post": 1 if method == "POST" else 0,
        "method_put": 1 if method == "PUT" else 0,

        # --- Heuristica pattern noti (segnale forte, non l'unico) ---
        "suspicious_token_count": sum(tok in combined_lower for tok in SQLI_XSS_TOKENS),

        # --- Feature aggiuntive ad alto potere discriminante per SQLi/XSS/Traversal ---
        "max_param_value_length": max((len(v) for vals in query_params.values() for v in vals), default=0),
        "num_encoded_chars": url.count("%"),
        "digit_ratio": (sum(c.isdigit() for c in decoded_url) / len(decoded_url)) if decoded_url else 0.0,
        "special_char_ratio": (count_special_chars(decoded_url) / len(decoded_url)) if decoded_url else 0.0,
        "num_equals": url.count("="),
        "num_ampersands": url.count("&"),
        "params_vs_equals_mismatch": abs(url.count("=") - len(query_params)),
        "content_type_is_form": 1 if "x-www-form-urlencoded" in str(row["content-type"]) else 0,
    }


print("Estrazione feature in corso...")
features_df = pd.DataFrame(df.apply(extract_features, axis=1).tolist())
y_true = df["classification"].astype(int)  # 0 = Normal, 1 = Anomalous

print(features_df.describe().T)

# ---------------------------------------------------------------------------
# 3. SPLIT: alleniamo SOLO su traffico normale (comportamento nativo IF)
# ---------------------------------------------------------------------------
X_train_raw = features_df[y_true == 0]

scaler = StandardScaler()
X_train = scaler.fit_transform(X_train_raw)
X_all = scaler.transform(features_df)  # per la valutazione su tutto il dataset

# ---------------------------------------------------------------------------
# 4. TRAINING
# ---------------------------------------------------------------------------
model = IsolationForest(
    n_estimators=300,
    max_samples="auto",
    contamination=0.05,   # margine di tolleranza; la tariamo con la validazione sotto
    random_state=42,
    n_jobs=-1,
)

print("\nTraining Isolation Forest...")
model.fit(X_train)

# ---------------------------------------------------------------------------
# 5. VALUTAZIONE (a soglia fissa 0.5, come baseline "di fabbrica")
# ---------------------------------------------------------------------------
raw_preds = model.predict(X_all)              # 1 = normale, -1 = anomalia
y_pred = np.where(raw_preds == -1, 1, 0)       # riallineo a 0/1 come y_true

print("\n=== Baseline (contamination di default) ===")
print(classification_report(y_true, y_pred, digits=3))
print("Confusion matrix:")
print(confusion_matrix(y_true, y_pred))

# ---------------------------------------------------------------------------
# 5b. RICERCA SOGLIA OTTIMALE sul risk_score continuo [0,1]
#     Stessa logica del tuo interceptor.go: score > soglia -> TarpitAndTrap
# ---------------------------------------------------------------------------
from sklearn.metrics import f1_score, precision_score, recall_score

raw_scores = model.decision_function(X_all)  # più basso = più anomalo
risk_scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

# ---------------------------------------------------------------------------
# 5b. SOGLIA "PARANOICA": FPR massimo 1% sul traffico sano
#     Filosofia: l'IA deve essere quasi mai colpevole di bloccare un utente
#     legittimo. I Falsi Negativi (attacchi non rilevati qui) sono accettabili
#     perché vengono comunque intercettati a valle dagli Honey-URL, che sono
#     deterministici al 100%.
# ---------------------------------------------------------------------------
from sklearn.metrics import f1_score, precision_score, recall_score

raw_scores = model.decision_function(X_all)  # più basso = più anomalo
risk_scores = 1 - (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min())

TARGET_FPR = 0.01  # 1% massimo di traffico sano scambiato per anomalia

# Calcoliamo la soglia SOLO sulla distribuzione del traffico Normal (y_true == 0):
# il 99° percentile di questa distribuzione è, per costruzione, il punto oltre
# il quale cade al massimo l'1% del traffico sano.
normal_scores = risk_scores[y_true == 0]
paranoid_threshold = np.percentile(normal_scores, (1 - TARGET_FPR) * 100)

y_pred_paranoid = (risk_scores > paranoid_threshold).astype(int)

# Verifica empirica dell'FPR effettivo ottenuto (deve essere <= 1%)
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

# La soglia finale che userà FastAPI/interceptor.go è questa, non 0.5 fisso
RISK_THRESHOLD = float(paranoid_threshold)

# ---------------------------------------------------------------------------
# 6. SERIALIZZAZIONE
# ---------------------------------------------------------------------------
os.makedirs("models", exist_ok=True)
joblib.dump(model, "models/isolation_forest.joblib")
joblib.dump(scaler, "models/scaler.joblib")
joblib.dump(list(features_df.columns), "models/feature_order.joblib")
joblib.dump(RISK_THRESHOLD, "models/risk_threshold.joblib")

print("\nModello, scaler, ordine feature e soglia salvati in models/")
print(f"Soglia operativa (RISK_THRESHOLD): {RISK_THRESHOLD:.4f}")
print("Ordine feature (fondamentale per replicarlo in Go):")
print(list(features_df.columns))