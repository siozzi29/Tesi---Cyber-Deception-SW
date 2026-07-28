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

NOTA VERSIONING: qualunque modifica a FEATURE_NAMES cambia la dimensione
del vettore. I file .joblib salvati con una versione precedente di questo
modulo NON sono più compatibili: vanno rigenerati con train.py (e
train_supervised.py, se in uso) DOPO ogni modifica qui.
"""

import math
import re
from collections import Counter
from urllib.parse import urlparse, parse_qsl

FEATURE_NAMES = [
    # --- 1. Analisi Strutturale e Dimensionale (URL e Query) ---
    "url_length",                # Lunghezza totale dell'URL
    "path_length",               # Lunghezza del percorso (es. /wp-content/)
    "query_length",              # Lunghezza della stringa di query (dopo il ?)
    "num_query_params",          # Numero totale di parametri nella query
    "avg_query_param_len",       # Lunghezza media dei parametri (rileva payload massivi)
    "max_query_param_len",       # Lunghezza massima di un singolo parametro
    "num_path_segments",         # Numero di cartelle nel percorso (es. /a/b/c = 3)
    
    # --- 2. Analisi Tipografica (Caratteri speciali nell'URL) ---
    "num_digits_url",            # Quantità di numeri nell'URL
    "num_special_chars_url",     # Quantità totale di caratteri speciali nell'URL
    "special_char_ratio_url",    # Rapporto tra caratteri speciali e normali (alto in XSS/SQLi)
    
    # --- 3. Analisi Entropica (Rilevamento Offuscamento) ---
    "url_entropy",               # Disordine dell'URL (alta entropia = offuscamento/crittografia)
    
    # --- 4. Pattern Malevoli Noti (Firme comportamentali nell'URL) ---
    "path_traversal_tokens_url", # Conteggio token come ../ o %2e%2e/
    "sql_keyword_count_url",     # Conteggio keyword SQL (es. UNION, SELECT, OR 1=1)
    "xss_token_count_url",       # Conteggio payload XSS (es. <script>, alert)
    
    # --- 6. Analisi del Payload (Body della richiesta) ---
    "method_code",               # Verbo HTTP (GET=0, POST=1, ecc.)
    "content_type_code",         # Formato dati (JSON, Form, XML)
    "has_body",                  # Flag booleano (0 o 1) se la richiesta ha un corpo
    "body_length",               # Dimensione totale del body in byte
    "num_body_params",           # Numero di parametri se il body è form-urlencoded
    "avg_body_param_len",        # Lunghezza media dei parametri del body
    "num_digits_body",           # Quantità di numeri nel body
    "num_special_chars_body",    # Quantità di caratteri speciali nel body
    "special_char_ratio_body",   # Rapporto caratteri speciali/normali nel body
    "body_entropy",              # Entropia del body (alta per Web Shell o file binari anomali)
    "path_traversal_tokens_body",# Conteggio token path traversal nel body
    "sql_keyword_count_body",    # Conteggio keyword SQL nel body
    "xss_token_count_body",      # Conteggio payload XSS nel body
    
    # --- 5. Tecniche di Evasione Avanzate (WAF Bypass) ---
    "ratio_encoded_chars_url",   # Percentuale URL-encoded (abuso = evasione filtri)
    "has_double_encoding",       # Rileva doppio encoding (es. %2527) tipico di WAF bypass
    "has_null_byte",             # Rileva %00 usato per troncare le stringhe in C/PHP
    "num_duplicate_params",      # Parametri ripetuti (HTTP Parameter Pollution)
    "path_entropy",              # Entropia calcolata solo sul percorso
    "query_entropy",             # Entropia calcolata solo sulla query string
    "max_path_segment_len",      # Lunghezza del segmento di path più lungo
    "num_uppercase_in_query",    # Anomalie nell'uso delle maiuscole (evasione case-sensitive)
    
    # --- Ulteriori feature avanzate sul Body ---
    "body_to_url_length_ratio",  # Rapporto dimensionale tra Body e URL
    "has_base64_pattern",        # Rileva stringhe Base64 (spesso usate per iniettare shell)
    "num_semicolons_body",       # Abuso di punti e virgola (indica Command Injection)
    
    # --- 7. Coerenza Strutturale del Protocollo ---
    "method_body_mismatch",      # Richieste GET ma con un Body (sintassi illecita)
    "content_type_body_mismatch",# Body presente ma Content-Type assente (o viceversa)
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

# --- Pattern per le nuove feature di evasion/encoding ---
_ENCODED_CHAR_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_DOUBLE_ENCODED_RE = re.compile(r"%25[0-9A-Fa-f]{2}")
# Base64-like: blocchi di 4 caratteri dell'alfabeto base64, almeno 4 blocchi
# (16+ caratteri), con eventuale padding finale. Soglia minima di lunghezza
# applicata a parte per evitare falsi positivi su stringhe corte casuali.
_BASE64_RE = re.compile(r"(?:[A-Za-z0-9+/]{4}){4,}(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")
_MIN_BASE64_LEN = 20


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


def _ratio_encoded_chars(url: str) -> float:
    """Percentuale dell'URL occupata da sequenze %XX. Ogni match copre 3
    caratteri grezzi (%, hex, hex): un URL fortemente encoded è un segnale
    tipico di tentativi di evasione dai filtri WAF basati su pattern testuali."""
    if not url:
        return 0.0
    matches = _ENCODED_CHAR_RE.findall(url)
    return (len(matches) * 3) / len(url)


def _has_double_encoding(url: str) -> float:
    """%25XX = un '%' codificato di nuovo (es. %2527 = %27 = ' doppiamente
    incapsulato). Tecnica classica per superare un singolo passaggio di
    URL-decoding lato filtro."""
    return 1.0 if _DOUBLE_ENCODED_RE.search(url or "") else 0.0


def _has_null_byte(s: str) -> float:
    """%00 (o il byte nullo letterale) è usato storicamente per troncare
    stringhe lato server in linguaggi/librerie C-based, bypassando check
    su estensioni file o path. Copre anche %2500 (null byte double-encoded),
    variante classica per eludere WAF che decodificano l'URL una sola volta."""
    if not s:
        return 0.0
    s_lower = s.lower()
    return 1.0 if (
        "%00" in s_lower       # null byte semplice
        or "%2500" in s_lower  # null byte double-encoded
        or "\x00" in s         # null byte letterale
    ) else 0.0


def _num_duplicate_params(params: list) -> int:
    """Conta le occorrenze di parametri ripetuti oltre la prima (HTTP
    Parameter Pollution): es. ?id=1&id=2 conta 1 duplicato su 'id'."""
    if not params:
        return 0
    counts = Counter(k for k, _ in params)
    return sum(c - 1 for c in counts.values() if c > 1)


def _max_path_segment_len(path: str) -> int:
    segments = [seg for seg in path.split("/") if seg]
    return max((len(seg) for seg in segments), default=0)


def _num_uppercase(s: str) -> int:
    return sum(1 for ch in s if ch.isupper())


def _has_base64_pattern(s: str) -> float:
    """Rileva blocchi di testo compatibili con base64: un payload offuscato
    (es. comando shell o script codificato) spesso passa in questa forma
    nel body di una richiesta malevola."""
    if not s or len(s) < _MIN_BASE64_LEN:
        return 0.0
    return 1.0 if _BASE64_RE.search(s) else 0.0


def _body_to_url_ratio(content: str, url: str) -> float:
    """Un body molto più lungo dell'URL è normale per upload/form estesi,
    ma un rapporto anomalo su richieste altrimenti semplici (es. un URL di
    3 caratteri con un body di 5000) è un segnale di sospetto."""
    if not url:
        return float(len(content))
    return len(content) / len(url)


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
        # --- Nuove feature: evasion/encoding su URL e path ---
        _ratio_encoded_chars(url),
        _has_double_encoding(url),
        _has_null_byte(url),
        _num_duplicate_params(query_params),
        _entropy(path),
        _entropy(query),
        _max_path_segment_len(path),
        _num_uppercase(query),
        # --- Nuove feature: body ---
        _body_to_url_ratio(content, url),
        _has_base64_pattern(content),
        content.count(";"),
        # --- Nuove feature: coerenza strutturale richiesta ---
        1.0 if method in ("GET", "HEAD") and content else 0.0,
        1.0 if bool(content_type) != bool(content) else 0.0,
    ]
    assert len(features) == len(FEATURE_NAMES), "features e FEATURE_NAMES devono avere la stessa lunghezza"
    return features