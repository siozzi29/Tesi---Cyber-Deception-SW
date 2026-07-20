"""
features.py - Feature engineering condiviso tra training (train.py) e
inferenza in produzione (main.py / FastAPI).

IMPORTANTE: questa è la SINGOLA fonte di verità per il calcolo delle feature.
Se train.py e main.py calcolassero le feature con logiche diverse (anche
minime), il modello riceverebbe in produzione dati fuori distribuzione
rispetto a quelli visti in training, e le predizioni sarebbero inaffidabili.
"""
import math
from collections import Counter
from urllib.parse import urlparse, parse_qs, unquote

SQLI_XSS_TOKENS = [
    "select", "union", "drop", "insert", "--", "or 1=1", "' or", "\"or",
    "<script", "onerror=", "onload=", "alert(", "../", "..\\", "etc/passwd",
    "cmd=", "exec(", "%00", "waitfor", "sleep(",
]

# Ordine ufficiale delle feature: deve combaciare ESATTAMENTE con
# ai-service/models/feature_order.joblib generato dal training.
FEATURE_ORDER = [
    "url_length", "path_length", "path_depth", "num_params", "query_length",
    "num_digits", "num_special_chars_url", "num_uppercase", "url_entropy",
    "content_length", "has_content", "num_special_chars_content", "content_entropy",
    "method_get", "method_post", "method_put",
    "suspicious_token_count", "max_param_value_length", "num_encoded_chars",
    "digit_ratio", "special_char_ratio", "num_equals", "num_ampersands",
    "params_vs_equals_mismatch", "content_type_is_form",
]


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def count_special_chars(s: str) -> int:
    import re
    return len(re.findall(r"[^a-zA-Z0-9\s]", s))


def extract_features(url_raw: str, method: str, content: str, content_type: str) -> dict:
    """
    Calcola le 25 feature a partire dai dati grezzi di UNA richiesta HTTP.

    url_raw: path + query string della richiesta (es. "/tienda1/publico/pagar.jsp?id=123")
             Non serve schema/host, solo quello che arriva dopo il dominio.
    method: "GET" / "POST" / "PUT" / ...
    content: corpo della richiesta (stringa vuota se assente)
    content_type: header Content-Type (stringa vuota se assente)
    """
    url = (url_raw or "").replace(" HTTP/1.1", "").strip()
    decoded_url = unquote(url)

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    content = content or ""
    method = (method or "").upper()
    content_type = content_type or ""

    combined_lower = (decoded_url + " " + content).lower()

    features = {
        "url_length": len(url),
        "path_length": len(parsed.path),
        "path_depth": parsed.path.count("/"),
        "num_params": len(query_params),
        "query_length": len(parsed.query),

        "num_digits": sum(c.isdigit() for c in decoded_url),
        "num_special_chars_url": count_special_chars(decoded_url),
        "num_uppercase": sum(c.isupper() for c in url),
        "url_entropy": shannon_entropy(decoded_url),

        "content_length": len(content),
        "has_content": 1 if content else 0,
        "num_special_chars_content": count_special_chars(content),
        "content_entropy": shannon_entropy(content),

        "method_get": 1 if method == "GET" else 0,
        "method_post": 1 if method == "POST" else 0,
        "method_put": 1 if method == "PUT" else 0,

        "suspicious_token_count": sum(tok in combined_lower for tok in SQLI_XSS_TOKENS),

        "max_param_value_length": max((len(v) for vals in query_params.values() for v in vals), default=0),
        "num_encoded_chars": url.count("%"),
        "digit_ratio": (sum(c.isdigit() for c in decoded_url) / len(decoded_url)) if decoded_url else 0.0,
        "special_char_ratio": (count_special_chars(decoded_url) / len(decoded_url)) if decoded_url else 0.0,
        "num_equals": url.count("="),
        "num_ampersands": url.count("&"),
        "params_vs_equals_mismatch": abs(url.count("=") - len(query_params)),
        "content_type_is_form": 1 if "x-www-form-urlencoded" in content_type else 0,
    }

    return features


def features_to_vector(features: dict) -> list:
    """Converte il dizionario di feature in una lista ordinata secondo
    FEATURE_ORDER, pronta per essere passata allo scaler/modello."""
    return [features[k] for k in FEATURE_ORDER]