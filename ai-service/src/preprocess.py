"""
ai-service/src/preprocess.py

Carica i dataset grezzi e li normalizza in un formato comune:
DataFrame con colonne url, method, content, content_type, label
(0 = normale, 1 = anomalo), pronto per essere passato a extract_features.
"""

import re
import pandas as pd
from urllib.parse import urlsplit, urlunsplit

_TRAILING_HTTP_VERSION = re.compile(r"\s+HTTP/\d\.\d\s*$")

_VALID_LABELS = {"normal", "valid", "benign", "0"}
_ANOMALOUS_LABELS = {"anomalous", "attack", "malicious", "invalid", "1"}


def _to_relative_url(raw: str) -> str:
    """Riduce un URL (assoluto o già relativo) a path+query, scartando
    schema/host — coerente con r.URL.RequestURI() lato Go, l'unica cosa
    che il proxy manda davvero a FastAPI in produzione."""
    if not raw:
        return ""
    raw = _TRAILING_HTTP_VERSION.sub("", raw.strip())
    parts = urlsplit(raw)
    return urlunsplit(("", "", parts.path, parts.query, ""))


def _normalize_label(raw) -> int:
    """Converte qualsiasi variante testuale/numerica di label in 0/1.
    Fail-fast su valori sconosciuti: un typo o una terza classe non
    devono finire silenziosamente in una delle due categorie."""
    s = str(raw).strip().lower()
    if s in _VALID_LABELS:
        return 0
    if s in _ANOMALOUS_LABELS:
        return 1
    raise ValueError(f"Valore di label non riconosciuto: {raw!r}")


def load_csic2010(path: str) -> pd.DataFrame:
    """Carica il CSV originale CSIC2010 (Kaggle ispangler /
    csic_database.csv): colonne Method, content, content-type,
    classification, URL, ecc."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    out = pd.DataFrame({
        "url": df["URL"].map(_to_relative_url),
        "method": df["Method"].fillna(""),
        "content": df["content"].fillna(""),
        "content_type": df["content-type"].fillna(""),
        "label": df["classification"].map(_normalize_label),
    })
    out["source_dataset"] = "csic2010"
    return out


def load_csic_ecml(path: str) -> pd.DataFrame:
    """Carica CSVData/csic_ecml_final.csv di msudol/Web-Application-
    Attack-Datasets: URI e GET-Query separati, body in POST-Data."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    def build_url(row):
        uri = row["URI"] or ""
        query = row["GET-Query"] or ""
        combined = f"{uri}?{query}" if query else uri
        return _to_relative_url(combined)

    out = pd.DataFrame({
        "url": df.apply(build_url, axis=1),
        "method": df["Method"].fillna(""),
        "content": df["POST-Data"].fillna(""),
        "content_type": df["Content-Type"].fillna(""),
        "label": df["Class"].map(_normalize_label),
    })
    out["source_dataset"] = "csic_ecml"
    return out


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """CSIC2010 è generato automaticamente e contiene molte richieste
    quasi-identiche (es. ogni GET con query string è seguito da un POST
    equivalente con la stessa query nel body — lo dice anche la
    letteratura sul dataset). Senza dedup, varianti quasi-identiche
    possono finire sia in train che in test: il modello sembra generalizzare
    bene ma in realtà sta solo "riconoscendo" cose già viste (data leakage).
    Dedup esatto su (method, url, content) — semplice ma efficace."""
    before = len(df)
    df = df.drop_duplicates(subset=["method", "url", "content"]).reset_index(drop=True)
    removed = before - len(df)
    if removed:
        print(f"[preprocess] Rimosse {removed} righe duplicate su {before} ({removed / before:.1%})")
    return df