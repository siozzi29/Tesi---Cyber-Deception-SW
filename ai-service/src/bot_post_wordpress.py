# ai-service/src/bot_post_wordpress.py

import csv
import random
import string
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from pathlib import Path

BASE_URL = "http://localhost:8080"
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_FILE = BASE_DIR / "data" / "wordpress_normal.csv"

# ==========================================
# CONFIGURAZIONI PER L'UTENTE
# ==========================================
# Usiamo gli stessi identici cookie dello spider per essere loggati
COOKIE_NAME = "wordpress_logged_in_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7Ca91cfae2e79798a4db3a4794206b1b9c656bebac8753d27de35d50a45ff506ae"

COOKIE_NAME_2 = "wordpress_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE_2 = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7C26a9acadbaca5844d3734b7ce0923b1d8f90ce0da2abc6ce6718e3c7a380474f"
# ==========================================

def extract_path(url):
    parsed = urlparse(url)
    return parsed.path + ("?" + parsed.query if parsed.query else "")

def random_string(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def main():
    print(f"[*] Avvio Bot POST su {BASE_URL}")
    session = requests.Session()
    
    # Bypass proxy di sistema
    session.proxies = {"http": None, "https": None}
    
    # Inserimento Cookie
    session.cookies.set(COOKIE_NAME, COOKIE_VALUE)
    session.cookies.set(COOKIE_NAME_2, COOKIE_VALUE_2)
    
    dataset_records = []
    
    # 1. VISITA LA PAGINA PER CREARE UN NUOVO ARTICOLO E RUBA IL NONCE
    new_post_url = f"{BASE_URL}/wp-admin/post-new.php"
    print(f"[*] 1. Richiesta GET a {new_post_url} per estrarre i Nonces segreti...")
    try:
        response = session.get(new_post_url, timeout=10)
    except Exception as e:
        print(f"Errore di connessione: {e}")
        return
        
    if "wp-login.php" in response.url or response.status_code != 200:
        print("[!] Errore: I cookie sono scaduti o non validi. Rifai il login e aggiorna i cookie!")
        return
        
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Cerca il campo hidden del nonce per gli articoli
    nonce_input = soup.find("input", {"id": "_wpnonce"})
    if not nonce_input:
        print("[!] Nonce non trovato. Sei sicuro di essere un amministratore?")
        return
        
    wp_nonce = nonce_input.get("value")
    print(f"    -> Trovato _wpnonce per post: {wp_nonce}")
    
    # 2. SIMULAZIONE DI AZIONI POST (Creazione bozze e Heartbeat)
    print("\n[*] 2. Inizio bombardamento di richieste POST autentiche...")
    
    # 2.A Simulazione Login (per addestrare l'AI alla pagina wp-login.php)
    print("    [POST Login] Simulazione invio credenziali a wp-login.php...")
    login_url = f"{BASE_URL}/wp-login.php"
    login_data = {
        "log": "admin",
        "pwd": "password_finta_per_ai",
        "wp-submit": "Log In",
        "redirect_to": f"{BASE_URL}/wp-admin/",
        "testcookie": "1"
    }
    
    # Invia la POST finta
    try:
        session.post(login_url, data=login_data, timeout=5)
    except:
        pass
        
    # Salva la traccia nel dataset in modo che l'AI la consideri normale (Data Augmentation x300)
    for _ in range(300):
        login_content_str = "log=admin&pwd=password_finta_per_ai&wp-submit=Log+In&redirect_to=http%3A%2F%2Flocalhost%3A8080%2Fwp-admin%2F&testcookie=1"
        dataset_records.append([extract_path(login_url), "POST", login_content_str, "application/x-www-form-urlencoded", 0])
    
    # B. Salvataggio di 200 finte Bozze per addestramento massiccio
    for i in range(200):
        title = f"Bozza Tesi {random_string(5)}"
        content = f"Questo e un contenuto finto generato dal bot per la tesi {random_string(20)}"
        
        post_data = {
            "_wpnonce": wp_nonce,
            "action": "draft",
            "post_title": title,
            "content": content,
            "post_type": "post"
        }
        
        post_url = f"{BASE_URL}/wp-admin/post.php"
        resp = session.post(post_url, data=post_data)
        
        # Salviamo la struttura esatta nel CSV
        content_str = f"_wpnonce={wp_nonce}&action=draft&post_title={title.replace(' ', '+')}&content={content.replace(' ', '+')}&post_type=post"
        content_type = "application/x-www-form-urlencoded"
        
        dataset_records.append([extract_path(post_url), "POST", content_str, content_type, 0])
        print(f"    [POST Bozza] Status {resp.status_code} - Titolo: {title}")
        
    # B. Simulazione di Heartbeat (Ajax) - Tipica azione di background di WP
    # Simuliamo payload massicci verso admin-ajax.php
    for i in range(20):
        ajax_url = f"{BASE_URL}/wp-admin/admin-ajax.php"
        ajax_data = {
            "action": "heartbeat",
            "screen_id": "dashboard",
            "interval": "60"
        }
        try:
            resp = session.post(ajax_url, data=ajax_data)
        except requests.exceptions.RequestException as e:
            print(f"      [POST {i+1}/200] Errore di connessione: {e}")
            continue
        content_str = "action=heartbeat&screen_id=dashboard&interval=60"
        content_type = "application/x-www-form-urlencoded"
        
        dataset_records.append([extract_path(ajax_url), "POST", content_str, content_type, 0])
        print(f"    [POST Ajax] Heartbeat simulato - Status: {resp.status_code}")

    # C. Bilanciamento delle rotte basilari pubbliche (Data Augmentation)
    # Per evitare che la homepage e la pagina di login pubbliche diventino anomalie 
    # rispetto all'enorme massa di POST che abbiamo iniettato.
    for _ in range(600):
        dataset_records.append(["/", "GET", "", "", 0])
    
    for _ in range(300):
        dataset_records.append(["/wp-login.php", "GET", "", "", 0])
        
    for _ in range(300):
        dataset_records.append(["/wp-login.php?redirect_to=http%3A%2F%2Flocalhost%3A8080%2Fwp-admin%2F&reauth=1", "GET", "", "", 0])

    # 3. SALVATAGGIO NEL CSV
    print(f"\n[*] 3. Aggiungo {len(dataset_records)} nuovi record bilanciati al dataset CSV...")
    with open(OUTPUT_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(dataset_records)
        
    print("[*] Operazione completata! Il tuo file CSV ora contiene traffico POST reale di WordPress.")
    print("[*] Lancia un'ultima volta `python -m src.train` e abbiamo chiuso il cerchio!")

if __name__ == "__main__":
    main()
