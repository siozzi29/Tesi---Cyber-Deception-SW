# ai-service/src/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import joblib
import numpy as np
from pathlib import Path
from src import features

# Modelli dati Pydantic strettamente aderenti alle struct del reverse proxy Go
class RequestPayload(BaseModel):
    url: str
    method: str
    content: str
    content_type: str

class ScoreResponse(BaseModel):
    risk_score: float
    is_anomalous: bool
    threshold: float

# Dizionario globale per conservare i modelli caricati ed evitare oneri computazionali ad ogni richiesta
ml_resources = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestisce il ciclo di vita dell'applicazione.
    Carica Isolation Forest, bounds e soglia di rischio solo all'avvio del worker.
    """
    base_dir = Path(__file__).resolve().parent.parent
    models_dir = base_dir / "models"
    
    try:
        ml_resources["model"] = joblib.load(models_dir / "isolation_forest.joblib")
        ml_resources["threshold"] = joblib.load(models_dir / "risk_threshold.joblib")
        ml_resources["bounds"] = joblib.load(models_dir / "score_bounds.joblib")
        print("Modelli ML caricati in memoria con successo.")
    except FileNotFoundError:
        print("Errore critico: File joblib non trovati. Assicurati di aver eseguito train.py.")
        
    yield
    ml_resources.clear()

app = FastAPI(title="WAAP Cyber Deception - AI Service", lifespan=lifespan)

@app.get("/health")
def health_check():
    """Endpoint di monitoraggio primario, utilizzato per garantire la disponibilità del servizio interno."""
    return {"status": "ok", "message": "Il servizio ML è operativo."}

@app.post("/score", response_model=ScoreResponse)
def score_traffic(payload: RequestPayload):
    """
    Riceve il traffico grezzo inoltrato dal proxy Go, ne calcola la rappresentazione
    vettoriale e valuta il punteggio di rischio. Restituisce HTTP 400 se i dati
    in entrata non possono essere processati, permettendo al proxy di attuare la logica fail-open.
    """
    try:
        # 1. Estrazione unificata delle feature matematiche a partire dagli unici 4 campi consentiti
        vector = features.extract_features(
            payload.url, payload.method, payload.content, payload.content_type
        )
        X = np.array(vector).reshape(1, -1)
        
        # 2. Ottenimento dello score. L'inversione di segno permette di trasformare la
        # classificazione (positivo=normale) in una valutazione di rischio (positivo=anomalo).
        model = ml_resources["model"]
        raw_score = -model.decision_function(X)[0]
        
        # 3. Normalizzazione del punteggio all'interno della finestra statistica [0, 1] calcolata sul train
        min_bound, max_bound = ml_resources["bounds"]
        normalized_score = (raw_score - min_bound) / (max_bound - min_bound)
        clamped_score = float(max(0.0, min(1.0, normalized_score)))
        
        # 4. Determinazione superamento soglia
        threshold = ml_resources["threshold"]
        is_anom = clamped_score > threshold
        
        return ScoreResponse(
            risk_score=clamped_score,
            is_anomalous=is_anom,
            threshold=threshold
        )
    except Exception as e:
        # HTTP 400 chiaro garantisce un instradamento passivo trasparente dal proxy Go
        raise HTTPException(status_code=400, detail=f"Elaborazione payload fallita: {str(e)}")