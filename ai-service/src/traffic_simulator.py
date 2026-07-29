# ai-service/src/traffic_simulator.py

import time
import random
import requests
import csv
from pathlib import Path

BASE_URL = "http://localhost:8080"
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "wordpress_normal.csv"

# ==================================
# PARAMETRI DEL SIMULATORE
# ==================================
PROB_NORMAL = 0.70    # 70% di probabilità traffico legittimo
PROB_ATTACK = 0.20    # 20% di probabilità attacchi web
PROB_HONEYPOT = 0.10  # 10% di probabilità esche deception

# Cookie di sessione (Aggiornali dal browser se scaduti!)
COOKIE_NAME = "wordpress_logged_in_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7Ca91cfae2e79798a4db3a4794206b1b9c656bebac8753d27de35d50a45ff506ae"
COOKIE_NAME_2 = "wordpress_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE_2 = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7C26a9acadbaca5844d3734b7ce0923b1d8f90ce0da2abc6ce6718e3c7a380474f"

DELAY_MIN = 0.5       # Attesa minima tra le richieste (secondi)
DELAY_MAX = 2.0       # Attesa massima tra le richieste (secondi)

# Esche conosciute (Honeypots)
HONEYPOTS = [
    "/health-check",
    "/wp-login.php",
    "/honey",
    "/wp-cron.php"
]

# Payload d'attacco basilari (SQLi, XSS, Path Traversal)
ATTACK_PAYLOADS = [
    "/?id=1' OR '1'='1",
    "/?search=<script>alert('xss')</script>",
    "/wp-content/../../../etc/passwd",
    "/?cmd=cat%20/etc/shadow",
    "/?q=UNION%20SELECT%20NULL,NULL,NULL"
]

def load_normal_urls():
    urls = []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Estraiamo solo le get per comodità di simulazione rapida
                if row["method"] == "GET":
                    urls.append(row["url"])
    except Exception as e:
        print(f"[!] Errore nel caricare il CSV: {e}")
        urls = ["/"]
        
    return list(set(urls)) if urls else ["/"]

def main():
    print(f"[*] Inizializzazione Traffic Simulator verso {BASE_URL}")
    print("[*] Caricamento URL legittimi dal dataset...")
    normal_urls = load_normal_urls()
    print(f"[*] Trovati {len(normal_urls)} URL legittimi unici.")
    
    print("\n[+] SIMULAZIONE AVVIATA (Premi Ctrl+C per fermare)")
    print(f"    - Traffico Normale: {PROB_NORMAL*100}%")
    print(f"    - Attacchi Reali:   {PROB_ATTACK*100}%")
    print(f"    - Trappole (Honey): {PROB_HONEYPOT*100}%")
    print("-" * 50)
    
    session = requests.Session()
    session.proxies = {"http": None, "https": None}
    
    # Inietta i cookie per navigare come utente autenticato
    if COOKIE_NAME and COOKIE_VALUE:
        session.cookies.set(COOKIE_NAME, COOKIE_VALUE)
    if COOKIE_NAME_2 and COOKIE_VALUE_2:
        session.cookies.set(COOKIE_NAME_2, COOKIE_VALUE_2)
    
    req_count = 0
    try:
        while True:
            req_count += 1
            dice = random.random()
            
            if dice < PROB_NORMAL:
                # TRAFFICO NORMALE
                target = random.choice(normal_urls)
                url = f"{BASE_URL}{target}"
                tipo = "\033[92m[NORMALE]\033[0m" # Verde
                
            elif dice < (PROB_NORMAL + PROB_ATTACK):
                # ATTACCO WEB
                payload = random.choice(ATTACK_PAYLOADS)
                url = f"{BASE_URL}{payload}"
                tipo = "\033[91m[ATTACCO]\033[0m" # Rosso
                
            else:
                # ESCA DECEPTION
                honey = random.choice(HONEYPOTS)
                url = f"{BASE_URL}{honey}"
                tipo = "\033[93m[HONEYPOT]\033[0m" # Giallo
                
            # Esegui la richiesta
            try:
                resp = session.get(url, timeout=3)
                status = resp.status_code
            except Exception as e:
                status = "ERR"
                
            print(f"{req_count:04d} | {tipo} -> {url} (Status: {status})")
            
            # Pausa casuale per realismo
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
            
    except KeyboardInterrupt:
        print("\n[*] Simulazione fermata dall'utente.")
        print(f"[*] Totale richieste inviate: {req_count}")

if __name__ == "__main__":
    main()
