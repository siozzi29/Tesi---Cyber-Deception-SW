import requests
import random
import time
import threading

PROXY_URL = "http://localhost:8080"

# Traffico Legittimo
LEGITIMATE_PATHS = [
    "/",
    "/?p=1",
    "/?p=126",
    "/?p=140",
    "/?cat=1",
    "/?page_id=37",
    "/?s=articolo+interessante",
    "/?s=wordpress",
    "/wp-includes/css/dashicons.min.css",
    "/wp-content/themes/twentytwenty/style.css"
]

# Traffico Malevolo (Attacchi vari)
ATTACKS = [
    "/?s=1'+OR+'1'='1",
    "/?p=1+UNION+SELECT+user,password+FROM+wp_users",
    "/?page_id=../../../etc/passwd",
    "/?s=<script>alert('xss')</script>",
    "/?author=1&cmd=cat+/etc/passwd",
    "/?s=admin'+--",
    "/?p=1;+DROP+TABLE+wp_users;"
]

def send_request(path, expected_type):
    url = f"{PROXY_URL}{path}"
    try:
        start_time = time.time()
        res = requests.get(url, timeout=3)
        elapsed = time.time() - start_time
        
        status = res.status_code
        if status == 200:
            print(f"[OK] {expected_type} | {path} -> Passata ({elapsed:.3f}s)")
        elif status == 403:
            print(f"[BLOCKED] {expected_type} | {path} -> Bloccata dal WAF! ({elapsed:.3f}s)")
        else:
            print(f"[INFO] {expected_type} | {path} -> Status HTTP {status}")
    except Exception as e:
        print(f"[ERROR] Impossibile contattare {url}: {e}")

def run_simulation():
    print(f"--- INIZIO SIMULAZIONE DI TRAFFICO SU {PROXY_URL} ---")
    print("Invio di richieste miste (legittime e malevole)...\n")
    
    threads = []
    
    # Prepariamo un mix di 100 richieste (80 legittime, 20 attacchi) mischiate
    requests_to_send = []
    for _ in range(80):
        requests_to_send.append((random.choice(LEGITIMATE_PATHS), "LEGIT"))
    for _ in range(20):
        requests_to_send.append((random.choice(ATTACKS), "ATTACK"))
        
    random.shuffle(requests_to_send)
    
    for path, req_type in requests_to_send:
        # Usiamo i thread per inviare le richieste velocemente e testare il carico
        t = threading.Thread(target=send_request, args=(path, req_type))
        threads.append(t)
        t.start()
        time.sleep(0.05) # Piccola pausa per non intasare le porte locali tutte nello stesso istante
        
    for t in threads:
        t.join()
        
    print("\n--- SIMULAZIONE COMPLETATA ---")
    print("Controlla la dashboard del Proxy (http://localhost:9090) per vedere tutti i punteggi!")

if __name__ == "__main__":
    run_simulation()
