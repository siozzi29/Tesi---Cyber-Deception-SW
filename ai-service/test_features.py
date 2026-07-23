import sys
sys.path.insert(0, '.')
from src.features import extract_features, FEATURE_NAMES

print(f'Totale feature: {len(FEATURE_NAMES)}')

# Test 1: richiesta normale GET
v1 = extract_features('/tienda1/index.jsp', 'GET', '', '')
print('\n=== GET normale ===')
for name, val in zip(FEATURE_NAMES, v1):
    print(f'  {name:35s} = {val}')

# Test 2: SQLi nel body
v2 = extract_features('/login', 'POST', "user=' OR 1=1--&pass=x", 'application/x-www-form-urlencoded')
print('\n=== POST SQLi (solo valori != 0) ===')
for name, val in zip(FEATURE_NAMES, v2):
    if val != 0.0:
        print(f'  {name:35s} = {val}')

# Test 3: double encoding + null byte
v3 = extract_features('/search?q=%2527script%2500', 'GET', '', '')
print('\n=== GET double encoding + null byte (solo valori != 0) ===')
for name, val in zip(FEATURE_NAMES, v3):
    if val != 0.0:
        print(f'  {name:35s} = {val}')

# Test 4: method/content-type mismatch
v4 = extract_features('/api/data', 'GET', 'body_non_atteso', '')
print('\n=== GET con body inatteso (ultime 5 feature) ===')
for name, val in zip(FEATURE_NAMES[-5:], v4[-5:]):
    print(f'  {name:35s} = {val}')

# Test 5: base64 nel body
import base64
payload = base64.b64encode(b'rm -rf / ; cat /etc/passwd').decode()
v5 = extract_features('/upload', 'POST', f'data={payload}', 'application/x-www-form-urlencoded')
print(f'\n=== POST con base64 payload ("{payload[:30]}...") ===')
for name, val in zip(FEATURE_NAMES, v5):
    if val != 0.0:
        print(f'  {name:35s} = {val}')

# Test 6: HTTP Parameter Pollution
v6 = extract_features('/page?id=1&id=2&id=3&cat=x&cat=y', 'GET', '', '')
print('\n=== GET HPP (param duplicati) ===')
for name, val in zip(FEATURE_NAMES, v6):
    if val != 0.0:
        print(f'  {name:35s} = {val}')
