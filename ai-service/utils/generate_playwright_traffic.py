import time
import random
import csv
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8080"
OUTPUT_FILE = "data/wordpress_normal.csv"

def run(playwright):
    print("[*] Avvio browser invisibile...")
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Apriamo il file in modalità APPEND per aggiungere ai dati esistenti
    csv_file = open(OUTPUT_FILE, 'a', newline='', encoding='utf-8')
    writer = csv.writer(csv_file)

    # Contatore richieste loggate
    req_count = 0

    def handle_request(request):
        nonlocal req_count
        try:
            # Escludi traffico esterno
            if not request.url.startswith(BASE_URL):
                return
            
            parsed = urlparse(request.url)
            path = parsed.path
            if parsed.query:
                path += "?" + parsed.query
                
            method = request.method
            body = request.post_data if request.post_data else ""
            
            # Recupero header
            content_type = ""
            for name, value in request.headers.items():
                if name.lower() == "content-type":
                    content_type = value
                    break
            
            # Assegnazioni corrette: le richieste GET HTTP standard non hanno Content-Type
            if method == "GET" and not content_type:
                content_type = ""

            writer.writerow([path, method, body, content_type, 0])
            req_count += 1
            
        except Exception:
            pass

    page.on("request", handle_request)

    print("[*] Eseguo il Login come amministratore...")
    page.goto(f"{BASE_URL}/wp-login.php")
    page.fill("#user_login", "admin")
    page.fill("#user_pass", "secretpassword")
    page.click("#wp-submit")
    page.wait_for_load_state("networkidle")
    print("[+] Login completato.")

    # 1. Navigazione nel pannello di Admin (generiamo chiamate /wp-admin e /wp-json)
    print("[*] Esplorazione profonda e completa dell'area Admin...")
    admin_paths = [
        "/wp-admin/index.php",
        "/wp-admin/update-core.php",
        "/wp-admin/edit.php",
        "/wp-admin/post-new.php",
        "/wp-admin/edit-tags.php?taxonomy=category",
        "/wp-admin/edit-tags.php?taxonomy=post_tag",
        "/wp-admin/upload.php",
        "/wp-admin/media-new.php",
        "/wp-admin/edit.php?post_type=page",
        "/wp-admin/post-new.php?post_type=page",
        "/wp-admin/edit-comments.php",
        "/wp-admin/themes.php",
        "/wp-admin/theme-install.php",
        "/wp-admin/site-editor.php",
        "/wp-admin/widgets.php",
        "/wp-admin/nav-menus.php",
        "/wp-admin/plugins.php",
        "/wp-admin/plugin-install.php",
        "/wp-admin/users.php",
        "/wp-admin/user-new.php",
        "/wp-admin/profile.php",
        "/wp-admin/tools.php",
        "/wp-admin/import.php",
        "/wp-admin/export.php",
        "/wp-admin/site-health.php",
        "/wp-admin/export-personal-data.php",
        "/wp-admin/erase-personal-data.php",
        "/wp-admin/options-general.php",
        "/wp-admin/options-writing.php",
        "/wp-admin/options-reading.php",
        "/wp-admin/options-discussion.php",
        "/wp-admin/options-media.php",
        "/wp-admin/options-permalink.php",
        "/wp-admin/options-privacy.php"
    ]
    for path in admin_paths:
        try:
            print(f"    - Visito admin: {path}")
            page.goto(f"{BASE_URL}{path}")
            
            # Interazione intensiva con Gutenberg per generare salvataggi JSON reali
            if "post-new" in path:
                page.wait_for_load_state("networkidle", timeout=15000)
                # Prova a scrivere il titolo se l'editor è carico
                try:
                    page.fill('h1.editor-post-title__input', 'Test Post Generato dal Bot')
                    time.sleep(1)
                    page.keyboard.press("Enter")
                    page.keyboard.type("Questo è un paragrafo di testo per testare il salvataggio JSON.")
                    time.sleep(1)
                    # Clicca salva bozza per triggerare la POST API
                    page.click('.editor-post-save-draft')
                    time.sleep(3)
                except Exception as e:
                    pass
            elif "site-editor" in path:
                page.wait_for_load_state("networkidle", timeout=15000)
                time.sleep(4)
            else:
                time.sleep(random.uniform(0.5, 1.5))
        except Exception as e:
            print(f"      [!] Errore su {path}: {e}")

    # 2. Navigazione nel Frontend pubblico per cliccare le tue nuove pagine
    print("[*] Ritorno alla Homepage per scansionare i link del footer...")
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    
    # Raccoglie tutti i link interni della pagina
    hrefs = page.evaluate("""() => {
        let links = Array.from(document.querySelectorAll('a'));
        return links.map(a => a.href).filter(href => href.startsWith(window.location.origin));
    }""")
    hrefs = list(set(hrefs))
    
    print(f"[*] Trovati {len(hrefs)} link nella homepage da visitare (incluse le nuove pagine!).")
    for i, href in enumerate(hrefs):
        print(f"    - Visito [{i+1}/{len(hrefs)}]: {href}")
        try:
            page.goto(href)
            page.wait_for_load_state("networkidle")
            time.sleep(random.uniform(1.0, 2.0))
        except:
            pass

    csv_file.close()
    browser.close()
    print(f"\n[+] Operazione completata con successo!")
    print(f"[+] Il bot ha intercettato e registrato {req_count} nuove richieste legittime!")
    print("[+] Le richieste sono state aggiunte a 'wordpress_normal.csv'.")

with sync_playwright() as playwright:
    run(playwright)
