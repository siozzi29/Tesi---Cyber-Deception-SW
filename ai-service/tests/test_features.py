import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features import extract_features, FEATURE_NAMES


def test_vector_length_matches_feature_names():
    vec = extract_features("/home", "GET", "", "")
    assert len(vec) == len(FEATURE_NAMES)


def test_empty_request_no_crash():
    vec = extract_features("", "", "", "")
    assert len(vec) == len(FEATURE_NAMES)
    assert all(isinstance(v, (int, float)) for v in vec)


def test_sql_injection_raises_sql_keyword_count():
    benign = extract_features("/login?user=simone", "GET", "", "")
    malicious = extract_features("/login?user=admin' OR 1=1--", "GET", "", "")
    idx = FEATURE_NAMES.index("sql_keyword_count_url")
    assert malicious[idx] > benign[idx]


def test_xss_token_detected_in_body():
    vec = extract_features("/comment", "POST", "<script>alert(1)</script>", "application/x-www-form-urlencoded")
    idx = FEATURE_NAMES.index("xss_token_count_body")
    assert vec[idx] > 0


def test_path_traversal_detected():
    vec = extract_features("/file?path=../../../../etc/passwd", "GET", "", "")
    idx = FEATURE_NAMES.index("path_traversal_tokens_url")
    assert vec[idx] > 0


def test_method_code_mapping():
    idx = FEATURE_NAMES.index("method_code")
    assert extract_features("/x", "GET", "", "")[idx] == 0
    assert extract_features("/x", "POST", "", "")[idx] == 1
    assert extract_features("/x", "WEIRDMETHOD", "", "")[idx] == 7  # fallback


def test_form_urlencoded_body_params_parsed():
    vec = extract_features("/login", "POST", "user=a&pass=b", "application/x-www-form-urlencoded")
    idx = FEATURE_NAMES.index("num_body_params")
    assert vec[idx] == 2


def test_json_body_not_parsed_as_params():
    # Content-Type JSON: niente parsing key=value, per design (vedi commento in features.py)
    vec = extract_features("/api", "POST", "user=a&pass=b", "application/json")
    idx = FEATURE_NAMES.index("num_body_params")
    assert vec[idx] == 0