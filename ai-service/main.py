"""
main.py - Servizio FastAPI per l'inferenza dell'Isolation Forest.

Espone POST /score: riceve i dati grezzi di una richiesta HTTP catturata dal
reverse proxy Go, calcola le 25 feature (stessa logica del training, via
features.py) e restituisce un risk_score in [0,1] più il verdetto "sospetto"
in base alla soglia paranoica calcolata in training.

Avvio:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
import os
import sys
from pathlib import Path

import joblib
import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

AI_SERVICE_DIR = Path(__file__).resolve().parent
if str(AI_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(AI_SERVICE_DIR))

from features import extract_features, features_to_vector, FEATURE_ORDER

app = FastAPI(title="WAAP Anomaly Detection Service")

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

model = joblib.load(os.path.join(MODELS_DIR, "isolation_forest.joblib"))
scaler = joblib.load(os.path.join(MODELS_DIR, "scaler.joblib"))
saved_feature_order = joblib.load(os.path.join(MODELS_DIR, "feature_order.joblib"))
risk_threshold = joblib.load(os.path.join(MODELS_DIR, "risk_threshold.joblib"))
score_bounds = joblib.load(os.path.join(MODELS_DIR, "score_bounds.joblib"))

# Guardia di sicurezza: se l'ordine feature salvato in training non combacia
# con quello di features.py, meglio fallire subito all'avvio (fail-fast)
# piuttosto che servire predizioni silenziosamente sbagliate.
assert list(saved_feature_order) == FEATURE_ORDER, (
    "MISMATCH tra feature_order.joblib e features.py! "
    "Il modello è stato allenato con un set di feature diverso da quello "
    "usato ora in inferenza. Rigenera il training o allinea features.py."
)

# Bound REALI osservati in training (data/score_bounds.joblib), non indovinati:
# garantiscono che il risk_score qui coincida esattamente con quello validato
# durante la ricerca della soglia paranoica.
RAW_SCORE_MIN = score_bounds["min"]
RAW_SCORE_MAX = score_bounds["max"]


class RequestPayload(BaseModel):
    url: str            # path + query string, es. "/tienda1/publico/pagar.jsp?id=123"
    method: str          # "GET", "POST", "PUT"...
    content: str = ""    # corpo della richiesta, stringa vuota se assente
    content_type: str = ""


class ScoreResponse(BaseModel):
    risk_score: float
    is_anomalous: bool
    threshold: float


@app.post("/score", response_model=ScoreResponse)
def get_risk_score(payload: RequestPayload) -> ScoreResponse:
    features = extract_features(payload.url, payload.method, payload.content, payload.content_type)
    vector = features_to_vector(features)

    X = scaler.transform([vector])
    raw_score = model.decision_function(X)[0]  # più basso = più anomalo

    # Stessa normalizzazione usata in training: min/max osservati sul dataset
    risk_score = float(np.clip(1 - (raw_score - RAW_SCORE_MIN) / (RAW_SCORE_MAX - RAW_SCORE_MIN), 0, 1))

    return ScoreResponse(
        risk_score=risk_score,
        is_anomalous=risk_score > risk_threshold,
        threshold=float(risk_threshold),
    )


@app.get("/health")
def health_check():
    """Endpoint leggero per il controllo di integrità del Load Balancer,
    separato da /score per non far girare inferenza ad ogni probe."""
    return {"status": "ok"}