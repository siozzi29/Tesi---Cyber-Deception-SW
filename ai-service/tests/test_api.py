import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture(scope="module")
def client():
    # Il lifespan carica i .joblib reali: servono presenti in ai-service/models/
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_score_benign_request(client):
    resp = client.post("/score", json={
        "url": "/home", "method": "GET", "content": "", "content_type": ""
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "risk_score" in body and "is_anomalous" in body and "threshold" in body
    assert 0.0 <= body["risk_score"] <= 1.0


def test_score_malicious_request_higher_than_benign(client):
    benign = client.post("/score", json={
        "url": "/home", "method": "GET", "content": "", "content_type": ""
    }).json()
    malicious = client.post("/score", json={
        "url": "/login?user=admin' OR 1=1--", "method": "GET", "content": "", "content_type": ""
    }).json()
    assert malicious["risk_score"] > benign["risk_score"]


def test_score_missing_field_returns_422():
    resp = TestClient(app).post("/score", json={"url": "/x"})  # mancano method/content/content_type
    assert resp.status_code == 422