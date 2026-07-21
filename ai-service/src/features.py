"""
ai-service/src/features.py

Estrazione feature da richieste HTTP grezze per il modello Isolation Forest.

VINCOLO ARCHITETTURALE: pkg/aiclient/aiclient.go manda a FastAPI SOLO
url, method, content, content_type per ogni richiesta. Qualsiasi feature
che in training dipendesse da altri campi (User-Agent, cookie, Accept...)
introdurrebbe uno skew train/serve, perché in produzione quei campi non
arrivano mai. Per questo TUTTE le feature qui sotto sono derivabili
esclusivamente da questi 4 campi.

Questa funzione è l'UNICA fonte di verità per la trasformazione richiesta
grezza -> vettore numerico: va importata sia da train.py che da main.py,
mai reimplementata in due posti diversi (rischio di disallineamento).
"""

import math
import re
from collections import Counter
from urllib.parse import urlparse, parse_qsl

FEATURE_NAMES = [
    "url_length",
    "path_length",
    "query_length",
    "num_query_params",
    "avg_query_param_len",
    "max_query_param_len",
    "num_path_segments",
    "num_digits_url",
    "num_special_chars_url",
    "special_char_ratio_url",
    "url_entropy",
    "path_traversal_tokens_url",
    "sql_keyword_count_url",
    "xss_token_count_url",
    "method_code",
    "content_type_code",
    "has_body",
    "body_length",
    "num_body_params",
    "avg_body_param_len",
    "num_digits_body",
    "num_special_chars_body",
    "special_char_ratio_body",
    "body_entropy",
    "path_traversal_tokens_body",
    "sql_keyword_count_body",
    "xss_token_count_body",
]

# Caratteri considerati "sicuri"/attesi in un URL ben formato (RFC 3986
# unreserved + separatori comuni). Tutto il resto (', ", <, >, ;, %00, ecc.)
# conta come carattere sospetto.
_SAFE_URL_CHARS = re.compile(r"[A-Za-z0-9\-\._~/]")

_METHOD_MAP = {
    "GET": 0, "POST": 1, "PUT": 2, "DELETE": 3,
    "HEAD": 4, "OPTIONS": 5, "PATCH": 6,
}

_CONTENT_TYPE_PREFIXES = [
    ("application/x-www-form-urlencoded", 1),
    ("multipart/form-data", 2),
    ("application/json", 3),
    ("text/xml", 4),
    ("application/xml", 4),
]

# Liste di token usati come SEGNALI NUMERICI (conteggio), non come regole
# hard-coded: il modello decide da solo quanto "pesano" nel definire un'
# anomalia, guardando la loro distribuzione nel traffico normale vs quello
# escluso dal training.
_SQL_KEYWORDS = [
    "select ", "union ", "insert ", "update ", "delete ", "drop ",
    "or 1=1", "' or '", "--", "/*", "*/", "xp_cmdshell",
    "information_schema", "sleep(", "benchmark(", "waitfor delay",
]
_XSS_TOKENS = [
    "<script", "javascript:", "onerror=", "onload=", "%3cscript",
    "document.cookie", "<img", "<svg", "alert(",
]
_TRAVERSAL_TOKENS = ["../", "..%2f", "%2e%2e", "..\\", "%2e%2e%2f"]


def _entropy(s: str) -> float:
    """Entropia di Shannon: alta entropia = stringa 'rumorosa'/offuscata
    (tipico di payload codificati o obfuscation), bassa entropia = testo
    ripetitivo e prevedibile (tipico di URL/parametri legittimi)."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _count_tokens(haystack: str, tokens: list) -> int:
    h = haystack.lower()
    return sum(h.count(t) for t in tokens)


def _special_char_ratio(s: str) -> float:
    if not s:
        return 0.0
    special = sum(1 for ch in s if not (ch.isalnum() or ch in "-._~/&=?"))
    return special / len(s)


def _content_type_code(content_type: str) -> int:
    ct = (content_type or "").lower()
    for prefix, code in _CONTENT_TYPE_PREFIXES:
        if ct.startswith(prefix):
            return code
    return 0 if not ct else 5  # 0 = assente, 5 = presente ma non riconosciuto


def extract_features(url: str, method: str, content: str, content_type: str) -> list:
    """Trasforma i 4 campi grezzi ricevuti da aiclient.go in un vettore
    numerico di len(FEATURE_NAMES) elementi, nell'ordine di FEATURE_NAMES."""
    url = url or ""
    method = (method or "").upper()
    content = content or ""
    content_type = content_type or ""

    parsed = urlparse(url)
    path = parsed.path or ""
    query = parsed.query or ""

    query_params = parse_qsl(query, keep_blank_values=True)
    query_param_lens = [len(v) for _, v in query_params]

    # I parametri del body si interpretano solo se il content-type dichiara
    # form-urlencoded: su JSON/multipart il parsing key=value non ha senso,
    # e forzarlo introdurrebbe rumore invece di segnale.
    body_params = []
    if content and "form-urlencoded" in content_type.lower():
        body_params = parse_qsl(content, keep_blank_values=True)
    body_param_lens = [len(v) for _, v in body_params]

    features = [
        len(url),
        len(path),
        len(query),
        len(query_params),
        (sum(query_param_lens) / len(query_param_lens)) if query_param_lens else 0.0,
        max(query_param_lens) if query_param_lens else 0.0,
        len([seg for seg in path.split("/") if seg]),
        sum(ch.isdigit() for ch in url),
        sum(1 for ch in url if not _SAFE_URL_CHARS.match(ch)),
        _special_char_ratio(url),
        _entropy(url),
        _count_tokens(url, _TRAVERSAL_TOKENS),
        _count_tokens(url, _SQL_KEYWORDS),
        _count_tokens(url, _XSS_TOKENS),
        _METHOD_MAP.get(method, 7),
        _content_type_code(content_type),
        1.0 if content else 0.0,
        len(content),
        len(body_params),
        (sum(body_param_lens) / len(body_param_lens)) if body_param_lens else 0.0,
        sum(ch.isdigit() for ch in content),
        sum(1 for ch in content if not _SAFE_URL_CHARS.match(ch)),
        _special_char_ratio(content),
        _entropy(content),
        _count_tokens(content, _TRAVERSAL_TOKENS),
        _count_tokens(content, _SQL_KEYWORDS),
        _count_tokens(content, _XSS_TOKENS),
    ]
    assert len(features) == len(FEATURE_NAMES), "features e FEATURE_NAMES devono avere la stessa lunghezza"
    return features