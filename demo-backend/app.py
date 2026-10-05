"""
Demo Backend — simula un sito web target (stile WordPress) per il video di presentazione.
Espone pagine HTML realistiche su http://localhost:8888 in modo che il WAAP proxy
possa inoltrarvi le richieste "legittime" e dimostrare il flusso completo.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse

# ─────────────────────────────────────────────────────────
# Template HTML dell'homepage (stile blog)
# ─────────────────────────────────────────────────────────
PAGE_STYLE = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
  header { background: #1a1a2e; color: white; padding: 18px 32px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 1.4rem; }
  header span { background: #e94560; border-radius: 4px; padding: 2px 10px; font-size: .75rem; }
  nav { background: #16213e; padding: 0 32px; }
  nav a { color: #aaa; text-decoration: none; display: inline-block; padding: 10px 16px; font-size: .9rem; }
  nav a:hover { color: white; }
  .hero { background: linear-gradient(135deg, #1a1a2e, #16213e); color: white; padding: 60px 32px; text-align: center; }
  .hero h2 { font-size: 2rem; margin-bottom: 12px; }
  .hero p { color: #aaa; max-width: 600px; margin: auto; }
  .container { max-width: 900px; margin: 32px auto; padding: 0 24px; }
  .card { background: white; border-radius: 8px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,.08); }
  .card h3 { color: #1a1a2e; margin-bottom: 8px; }
  .card p { color: #666; line-height: 1.6; }
  .tag { background: #e8f4fd; color: #1565c0; font-size: .75rem; padding: 2px 8px; border-radius: 12px; margin-right: 4px; }
  footer { text-align: center; padding: 24px; color: #999; font-size: .8rem; background: #1a1a2e; color: #aaa; margin-top: 40px; }
  .search-bar { background: white; padding: 16px; border-radius: 8px; margin-bottom: 20px; display: flex; gap: 8px; }
  .search-bar input { flex: 1; border: 1px solid #ddd; padding: 8px 12px; border-radius: 4px; font-size: .95rem; }
  .search-bar button { background: #e94560; color: white; border: none; padding: 8px 20px; border-radius: 4px; cursor: pointer; }
</style>
"""

def make_page(title: str, body: str) -> bytes:
    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} — TechBlog Demo</title>
  {PAGE_STYLE}
</head>
<body>
  <header>
    <h1>TechBlog</h1>
    <span>DEMO</span>
  </header>
  <nav>
    <a href="/">Home</a>
    <a href="/?cat=security">Sicurezza</a>
    <a href="/?cat=ai">Intelligenza Artificiale</a>
    <a href="/?page_id=2">Chi siamo</a>
    <a href="/wp-login.php">Accedi</a>
  </nav>
  {body}
  <footer>
    &copy; 2026 TechBlog Demo &mdash; Progetto Tesi: WAAP con Cyber Deception &amp; ML
  </footer>
</body>
</html>"""
    return html.encode("utf-8")


HOMEPAGE_BODY = """
<div class="hero">
  <h2>Benvenuto su TechBlog</h2>
  <p>Articoli su sicurezza informatica, intelligenza artificiale e sviluppo software.</p>
</div>
<div class="container">
  <form class="search-bar" method="get" action="/">
    <input type="text" name="s" placeholder="Cerca articoli...">
    <button type="submit">Cerca</button>
  </form>
  <div class="card">
    <h3><a href="/?p=1">Cos'è un Web Application Firewall?</a></h3>
    <p>I WAF tradizionali filtrano il traffico HTTP/HTTPS basandosi su regole e firme statiche.
       Scopri perché non bastano contro le minacce moderne...</p>
    <p style="margin-top:10px"><span class="tag">Sicurezza</span><span class="tag">WAF</span></p>
  </div>
  <div class="card">
    <h3><a href="/?p=2">Machine Learning per il rilevamento delle anomalie</a></h3>
    <p>L'Isolation Forest è un algoritmo non supervisionato ideale per identificare richieste HTTP anomale
       senza bisogno di esempi di attacco etichettati...</p>
    <p style="margin-top:10px"><span class="tag">Machine Learning</span><span class="tag">Anomaly Detection</span></p>
  </div>
  <div class="card">
    <h3><a href="/?p=3">Cyber Deception: ingannare l'attaccante</a></h3>
    <p>La Cyber Deception usa trappole (honeypot, honeytoken) per identificare e ingannare l'attaccante
       prima che possa causare danni reali all'infrastruttura...</p>
    <p style="margin-top:10px"><span class="tag">Cyber Deception</span><span class="tag">Honeypot</span></p>
  </div>
</div>
"""

ARTICLE_BODY = {
    "1": ("<h2>Cos'è un Web Application Firewall?</h2>",
          "Un WAF analizza il traffico HTTP/HTTPS in ingresso e blocca le richieste che corrispondono a pattern di attacco noti. "
          "OWASP CRS è il ruleset più utilizzato al mondo. Tuttavia, i WAF a firme statiche non riconoscono varianti zero-day "
          "o payload offuscati. La prossima generazione di WAAP combina regole con Machine Learning comportamentale."),
    "2": ("<h2>Machine Learning per il rilevamento delle anomalie</h2>",
          "L'Isolation Forest costruisce un insieme di alberi di isolamento. Le istanze anomale, essendo rare e diverse "
          "dal traffico normale, vengono isolate più rapidamente (percorso più corto nell'albero). "
          "Il sistema WAAP descritto in questa tesi estrae 44 feature da ogni richiesta HTTP e assegna un Risk Score in millisecondi."),
    "3": ("<h2>Cyber Deception: ingannare l'attaccante</h2>",
          "Gli honeytoken sono risorse false, invisibili all'utente reale, che attirano scanner e bot automatizzati. "
          "Quando un attaccante accede a un honeytoken, viene immediatamente identificato con il 100% di accuratezza "
          "e zero falsi positivi. Il WAAP implementato in questa tesi inietta dinamicamente honey-URL nel DOM HTML "
          "di ogni pagina servita al client."),
}

LOGIN_PAGE = """
<div class="container" style="max-width:420px; padding-top:60px;">
  <div class="card">
    <h3 style="margin-bottom:20px">Accedi a TechBlog</h3>
    <form method="post" action="/wp-login.php">
      <div style="margin-bottom:12px">
        <label style="display:block;margin-bottom:4px;font-size:.9rem">Username</label>
        <input type="text" name="log" style="width:100%;border:1px solid #ddd;padding:8px 12px;border-radius:4px;font-size:.95rem">
      </div>
      <div style="margin-bottom:16px">
        <label style="display:block;margin-bottom:4px;font-size:.9rem">Password</label>
        <input type="password" name="pwd" style="width:100%;border:1px solid #ddd;padding:8px 12px;border-radius:4px;font-size:.95rem">
      </div>
      <button type="submit" style="background:#1a1a2e;color:white;border:none;padding:10px 24px;border-radius:4px;cursor:pointer;width:100%">Accedi</button>
    </form>
  </div>
</div>
"""

ABOUT_BODY = """
<div class="hero">
  <h2>Chi siamo</h2>
  <p>TechBlog è un sito demo sviluppato per la presentazione della tesi di laurea in Informatica.</p>
</div>
<div class="container">
  <div class="card">
    <h3>Il Progetto WAAP</h3>
    <p>Questo sito è il <strong>backend protetto</strong> dal sistema WAAP sviluppato in tesi.
       Tutte le richieste che stai vedendo vengono filtrate dal Reverse Proxy in Go,
       analizzate dall'AI Engine (Isolation Forest in Python/FastAPI) e — se sicure —
       inoltrate a questa pagina.</p>
  </div>
  <div class="card">
    <h3>Candidato</h3>
    <p><strong>Simone Iozzi</strong> — Laurea Triennale in Informatica<br>
       In collaborazione con <strong>Apuliasoft S.r.l.</strong></p>
  </div>
</div>
"""


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Stampa log su stdout con formato leggibile
        print(f"[DEMO-BACKEND] {self.address_string()} — {format % args}")

    def send_html(self, status: int, title: str, body: str):
        content = make_page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # Login page
        if parsed.path == "/wp-login.php":
            self.send_html(200, "Accedi", LOGIN_PAGE)
            return

        # Articolo specifico (?p=N)
        if "p" in params:
            pid = params["p"][0]
            if pid in ARTICLE_BODY:
                h, body = ARTICLE_BODY[pid]
                article_body = f"""
                <div class="container">
                  <div class="card">
                    {h}
                    <p style="color:#999;font-size:.85rem;margin:8px 0 16px">Pubblicato il 15 Settembre 2026</p>
                    <p style="line-height:1.8">{body}</p>
                  </div>
                </div>"""
                self.send_html(200, h.replace("<h2>", "").replace("</h2>", ""), article_body)
                return

        # Pagina statica (?page_id=2 → about)
        if params.get("page_id", [""])[0] == "2":
            self.send_html(200, "Chi siamo", ABOUT_BODY)
            return

        # Ricerca (?s=query)
        if "s" in params:
            query = params["s"][0]
            search_body = f"""
            <div class="container">
              <div class="card">
                <h3>Risultati per: "{query}"</h3>
                <p style="margin-top:12px;color:#666">Trovati 3 articoli corrispondenti alla tua ricerca.</p>
              </div>
            </div>
            {HOMEPAGE_BODY.split('<div class="container">')[1].rsplit('</div>', 1)[0]}
            </div>"""
            self.send_html(200, f"Ricerca: {query}", search_body)
            return

        # Homepage
        self.send_html(200, "Home", HOMEPAGE_BODY)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        # Leggi body (non lo usiamo, ma dobbiamo consumarlo)
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        if parsed.path == "/wp-login.php":
            # Redirect finto verso homepage dopo login
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return

        self.send_html(405, "Errore", '<div class="container"><div class="card"><h3>Metodo non consentito</h3></div></div>')


if __name__ == "__main__":
    HOST, PORT = "0.0.0.0", 8888
    server = HTTPServer((HOST, PORT), DemoHandler)
    print(f"[DEMO-BACKEND] Sito demo in ascolto su http://{HOST}:{PORT}")
    print("[DEMO-BACKEND] Premi Ctrl+C per fermare.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[DEMO-BACKEND] Server fermato.")
