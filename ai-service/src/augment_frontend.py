import random
import string
import os

def generate_random_string(min_len, max_len):
    length = random.randint(min_len, max_len)
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def generate_random_frontend_query():
    patterns = [
        "p={num}",
        "page_id={num}",
        "author={num}",
        "cat={num}",
        "m={year}{month}",
        "s={text}",
        "tag={text}",
        "p={num}&preview=true",
        "lang={text}"
    ]
    
    pattern = random.choice(patterns)
    
    num = random.randint(1, 9999)
    year = random.randint(2010, 2026)
    month = str(random.randint(1, 12)).zfill(2)
    text = generate_random_string(3, 15)
    
    query = pattern.format(num=num, year=year, month=month, text=text)
    return f"/?{query}"

def main():
    file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'wordpress_normal.csv')
    
    if not os.path.exists(file_path):
        print(f"Errore: File {file_path} non trovato.")
        return
        
    print("Inizio data augmentation per parametri frontend...")
    with open(file_path, 'a', encoding='utf-8') as f:
        for _ in range(15000):
            url = generate_random_frontend_query()
            line = f"{url},GET,,text/html; charset=UTF-8,0\n"
            f.write(line)
            
    print("Data augmentation completata. Aggiunte 15.000 righe sintetiche.")

if __name__ == '__main__':
    main()
