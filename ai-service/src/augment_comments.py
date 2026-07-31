import random
import string
import urllib.parse
from pathlib import Path

# Parole comuni per generare testi discorsivi
PAROLE = [
    "ciao", "questo", "articolo", "molto", "bello", "interessante", "grazie",
    "secondo", "me", "però", "dovresti", "approfondire", "il", "tema",
    "davvero", "complimenti", "ottimo", "lavoro", "spero", "di", "leggere",
    "presto", "altri", "post", "come", "questo", "non", "sono", "d'accordo",
    "ma", "rispetto", "la", "tua", "opinione", "hanno", "ucciso", "ragno",
    "perché", "caffè", "pubblicità", "sempre", "così", "fantastico",
    "assolutamente", "sì", "forse", "chissà", "boh", "magari", "sicuro"
]

PUNTEGGIATURA = [".", ",", "!", "?", "...", ":", ";", " '", "' "]

def genera_commento():
    num_parole = random.randint(10, 50)
    testo = []
    for _ in range(num_parole):
        parola = random.choice(PAROLE)
        testo.append(parola)
        if random.random() < 0.15:
            testo[-1] += random.choice(PUNTEGGIATURA)
            
    commento_raw = " ".join(testo)
    # Codifichiamo il commento come farebbe il browser in una richiesta form POST
    body = f"comment={urllib.parse.quote_plus(commento_raw)}&author=utente{random.randint(1,100)}&email=utente{random.randint(1,100)}%40gmail.com&url=&submit=Post+Comment&comment_post_ID={random.randint(1,200)}&comment_parent=0"
    return body

def main():
    base_dir = Path(__file__).resolve().parent.parent
    data_file = base_dir / "data" / "wordpress_normal.csv"
    
    nuove_righe = []
    # Generiamo 5000 commenti simulati
    for _ in range(5000):
        body = genera_commento()
        # Formato CSV: url, method, body, content_type, is_anomaly
        riga = f"/wp-comments-post.php,POST,{body},application/x-www-form-urlencoded,0\n"
        nuove_righe.append(riga)
        
    with open(data_file, "a", encoding="utf-8") as f:
        f.writelines(nuove_righe)
        
    print(f"Iniettati 5000 commenti discorsivi in {data_file}")

if __name__ == "__main__":
    main()
