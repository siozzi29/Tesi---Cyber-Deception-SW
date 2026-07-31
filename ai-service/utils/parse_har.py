import json
import csv
import os

HAR_FILE = "data/training.har"
CSV_FILE = "data/wordpress_normal.csv"

def extract_from_har():
    print(f"[*] Lettura del file {HAR_FILE}...")
    with open(HAR_FILE, "r", encoding="utf-8") as f:
        har_data = json.load(f)

    entries = har_data.get("log", {}).get("entries", [])
    print(f"[*] Trovate {len(entries)} richieste nel file HAR.")

    added = 0
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        
        for entry in entries:
            req = entry.get("request", {})
            url = req.get("url", "")
            method = req.get("method", "GET")
            
            # Filtriamo solo le richieste verso localhost o il backend, ignoriamo roba esterna (google fonts ecc)
            if "localhost" not in url and "34.53.145.249" not in url:
                continue
                
            # Rimuoviamo il dominio per avere solo il path+query come nel dataset originale
            # Es: http://localhost:8080/wp-admin/ -> /wp-admin/
            if "://" in url:
                try:
                    url_path = "/" + url.split("/", 3)[3]
                except IndexError:
                    url_path = "/"
            else:
                url_path = url

            # Content Type
            content_type = ""
            for header in req.get("headers", []):
                if header.get("name", "").lower() == "content-type":
                    content_type = header.get("value", "")
                    break
            
            # Content (Body)
            post_data = req.get("postData", {})
            content = post_data.get("text", "")
            
            writer.writerow([url_path, method, content, content_type])
            added += 1

    print(f"[+] Estratte e accodate {added} richieste valide a {CSV_FILE}.")

if __name__ == "__main__":
    extract_from_har()
