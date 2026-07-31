import urllib.request
from html.parser import HTMLParser
import csv
import ssl
from urllib.parse import urljoin, urlparse
import os

# Disabilita controlli SSL (nel caso in cui testassimo su https locale)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_URL = "http://localhost:8080"
visited = set()
urls_to_visit = [BASE_URL]
traffic_data = []

class MyHTMLParser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for attr, value in attrs:
            if attr in ['href', 'src'] and value:
                full_url = urljoin(BASE_URL, value)
                if full_url.startswith(BASE_URL) and full_url not in visited and "/sys/health-check" not in full_url:
                    urls_to_visit.append(full_url)

print("Inizio scansione del sito per catturare traffico normale...")

while urls_to_visit and len(traffic_data) < 150: # Catturiamo max 150 richieste
    current_url = urls_to_visit.pop(0)
    if current_url in visited:
        continue
    visited.add(current_url)
    
    try:
        req = urllib.request.Request(current_url, headers={'User-Agent': 'Mozilla/5.0 WAAP-Crawler'})
        with urllib.request.urlopen(req, context=ctx, timeout=3) as response:
            content_type = response.getheader('Content-Type') or ''
            html_content = response.read()
            
            # Se è HTML, estrae altri link da visitare
            if 'text/html' in content_type:
                parser = MyHTMLParser()
                parser.feed(html_content.decode('utf-8', errors='ignore'))
            
            # Crea l'URL relativo come lo vedrebbe il proxy (es. /wp-includes/style.css)
            parsed_url = urlparse(current_url)
            rel_url = parsed_url.path
            if parsed_url.query:
                rel_url += "?" + parsed_url.query
                
            traffic_data.append({
                "url": rel_url,
                "method": "GET",
                "content": "",
                "content_type": content_type,
                "label": 0
            })
            print(f"[{len(traffic_data)}] Catturato: {rel_url}")
    except Exception as e:
        pass

# Salva il CSV
os.makedirs("data", exist_ok=True)
csv_file = "data/wordpress_normal.csv"
with open(csv_file, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=["url", "method", "content", "content_type", "label"])
    writer.writeheader()
    writer.writerows(traffic_data)

print(f"\nFatto! Salvate {len(traffic_data)} richieste legittime in {csv_file}")