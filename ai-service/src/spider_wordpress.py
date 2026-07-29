# ai-service/src/spider_wordpress.py

import csv
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path

BASE_URL = "http://localhost:8080"
# BASE_URL = "http://34.53.145.249"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "wordpress_normal.csv"

# ==========================================
# CONFIGURAZIONI PER L'UTENTE
# ==========================================

# 1. ESCHE DA IGNORARE: Inserisci qui le parole chiave dei path che lo spider NON deve toccare
IGNORE_PATHS = [
    "health-check",
    "logout",
    "wp-cron.php"
]

# 2. AUTENTICAZIONE WP-ADMIN:
# Per far esplorare allo spider la sezione /wp-admin, devi dargli la tua sessione.
# Vai sul browser, loggati, premi F12 -> Application -> Cookies.
# Trova il cookie che si chiama "wordpress_logged_in_[stringa-a-caso]".
# Copia il NOME ESATTO e il VALORE qui sotto:
COOKIE_NAME = "wordpress_logged_in_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7Ca91cfae2e79798a4db3a4794206b1b9c656bebac8753d27de35d50a45ff506ae"

# Aggiungo anche l'altro cookie essenziale per il backend
COOKIE_NAME_2 = "wordpress_37d007a56d816107ce5b52c10342db37"
COOKIE_VALUE_2 = "admin%7C1785481886%7CS1IKLvBPYtymno3PiH3Gqy6e0oTtrPAdrYJ5CYmtdPI%7C26a9acadbaca5844d3734b7ce0923b1d8f90ce0da2abc6ce6718e3c7a380474f"

# Vuoi che lo spider parta dritto dall'admin? Se sì, de-commenta la riga sotto:
# BASE_URL = "http://localhost:8080/wp-admin/"
# ==========================================

MAX_PAGES = 1500  # Aumentato perché il wp-admin è enorme
visited = set()
queue = [BASE_URL]
dataset = []

def extract_path_and_query(url):
    parsed = urlparse(url)
    path = parsed.path if parsed.path else "/"
    if parsed.query:
        path += "?" + parsed.query
    return path

def main():
    print(f"[*] Inizio crawling automatizzato su {BASE_URL}")
    print(f"[*] Il file {OUTPUT_FILE.name} verra' sovrascritto.")
    
    if COOKIE_NAME and COOKIE_VALUE:
        print("[*] Autenticazione WP-Admin ATTIVA!")
    else:
        print("[!] Nessun cookie impostato. Lo spider non entrera' nel wp-admin.")
    
    dataset.append(["url", "method", "content", "content_type", "label"])
    
    # Preparazione cookie dictionary
    spider_cookies = {}
    if COOKIE_NAME and COOKIE_VALUE:
        spider_cookies[COOKIE_NAME] = COOKIE_VALUE
    if COOKIE_NAME_2 and COOKIE_VALUE_2:
        spider_cookies[COOKIE_NAME_2] = COOKIE_VALUE_2

    while queue and len(visited) < MAX_PAGES:
        current_url = queue.pop(0)
        
        # 1. Filtro Blacklist / Esche
        if any(trap in current_url for trap in IGNORE_PATHS):
            print(f"      [SKIP] Esca/Blacklist evitata: {current_url}")
            continue
            
        if current_url in visited:
            continue
            
        visited.add(current_url)
        print(f"[{len(visited)}/{MAX_PAGES}] Visitando: {current_url}")
        
        try:
            response = requests.get(
                current_url, 
                timeout=5, 
                proxies={"http": None, "https": None},
                cookies=spider_cookies
            )
            
            path_query = extract_path_and_query(current_url)
            content_type = response.headers.get("Content-Type", "")
            
            # Se la pagina ci sbatte fuori (redirect non autorizzato), non loggarla come normale
            if response.status_code == 401 or response.status_code == 403:
                print("      [!] Accesso negato (401/403). Ignoro.")
                continue

            dataset.append([path_query, "GET", "", content_type, 0])
            
            # Estrazione dei nuovi link
            if "text/html" in content_type:
                soup = BeautifulSoup(response.text, "html.parser")
                tags = soup.find_all(['a', 'link', 'script', 'img'])
                for tag in tags:
                    link = tag.get('href') or tag.get('src')
                    if not link:
                        continue
                        
                    absolute_link = urljoin(current_url, link)
                    parsed_link = urlparse(absolute_link)
                    
                    if parsed_link.netloc in ["localhost:8080", "34.53.145.249"]:
                        clean_url = parsed_link._replace(fragment="").geturl()
                        if clean_url not in visited and clean_url not in queue:
                            queue.append(clean_url)
                            
        except requests.exceptions.RequestException as e:
            print(f"      [Errore] impossibile raggiungere {current_url}: {e}")
            continue

    print(f"\n[*] Crawling completato. Visitate {len(visited)} risorse uniche.")
    with open(OUTPUT_FILE, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(dataset)
        
    print(f"[*] Dataset perfetto salvato in {OUTPUT_FILE}")
    print(f"[*] Righe totali: {len(dataset)}")

if __name__ == "__main__":
    main()
