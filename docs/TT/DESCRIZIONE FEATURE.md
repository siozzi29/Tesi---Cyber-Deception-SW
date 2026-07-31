# Documentazione delle Feature (Isolation Forest)

Per addestrare il modello Isolation Forest su traffico puramente HTTP (URL, Metodo, Body, Content-Type), sono state ingegnerizzate 40 feature specifiche. Il modello usa l'analisi dimensionale, tipografica, entropica e comportamentale per individuare anomalie (Zero-Day) ed evasioni WAF, senza basarsi esclusivamente su firme fisse.

## 1. Analisi Strutturale e Dimensionale (URL e Query)
Studia le lunghezze e la geometria della richiesta. Gli attacchi buffer overflow o payload complessi generano stringhe fuori dalla norma.
- **`url_length`**: Lunghezza totale dell'URL. Un URL eccezionalmente lungo può indicare un tentativo di buffer overflow o un payload massivo.
- **`path_length`**: Lunghezza del percorso (URI).
- **`query_length`**: Lunghezza della stringa di query. 
- **`num_query_params`**: Numero totale di parametri nella query. Molti parametri possono indicare Parameter Pollution.
- **`avg_query_param_len`**: Lunghezza media dei parametri. Valori alti suggeriscono payload iniettati al posto di parametri standard.
- **`max_query_param_len`**: Lunghezza del parametro più grande, fondamentale per scovare SQLi isolate.
- **`num_path_segments`**: Numero di cartelle nel percorso. Valori elevati indicano esplorazioni profonde o anomalie nel routing.

## 2. Analisi Tipografica (Caratteri speciali)
I payload malevoli (SQLi, XSS) richiedono sintassi specifiche fatte di apici, parentesi e operatori logici.
- **`num_digits_url`**: Quantità di numeri nell'URL.
- **`num_special_chars_url`**: Quantità totale di caratteri non alfanumerici.
- **`special_char_ratio_url`**: Rapporto tra caratteri speciali e testo. Altissimo negli attacchi XSS e SQLi rispetto alla normale lingua inglese.

## 3. Analisi Entropica (Disordine)
Calcola l'entropia di Shannon. Testo leggibile ha entropia bassa, mentre hash, codice offuscato o crittografia hanno entropia alta.
- **`url_entropy`**: Disordine globale dell'URL. Segnala shell codificate o offuscamento (es. Base64).
- **`path_entropy`**: Entropia del solo URI.
- **`query_entropy`**: Entropia della sola Query String.

## 4. Analisi del Payload (Body della richiesta)
Ripete i controlli strutturali ed entropici sul corpo della richiesta (tipico per POST e PUT).
- **`method_code`**: Codifica categorica del verbo HTTP (es. 0=GET, 1=POST).
- **`content_type_code`**: Codifica del formato dei dati (JSON, XML, Form).
- **`has_body`**: Flag (0 o 1) se la richiesta ha un payload.
- **`body_length`**: Dimensione totale in byte.
- **`num_body_params`**: Numero di parametri (se form-urlencoded).
- **`avg_body_param_len`**: Lunghezza media dei parametri nel body.
- **`num_digits_body`**: Quantità di numeri.
- **`num_special_chars_body`**: Quantità di caratteri speciali. Spikes indicano iniezioni o codice compilato.
- **`special_char_ratio_body`**: Densità di caratteri speciali nel body.
- **`body_entropy`**: Entropia di Shannon sul body. Un body molto "rumoroso" indica crittografia (malware C2) o file compressi anomali.

## 5. Tecniche di Evasione Avanzate (WAF Bypass)
Le evasioni consistono nel nascondere il payload codificandolo in modi che un Web Server standard tradurrà, ma un filtro debole no.
- **`ratio_encoded_chars_url`**: Percentuale di caratteri URL-encoded (`%XX`). Un abuso indica evasione.
- **`has_double_encoding`**: Rileva doppi encoding (`%25XX`). Tecnica classica per bypassare filtri che decodificano l'URL una volta sola.
- **`has_null_byte`**: Presenza di `%00` (o varianti), storicamente usati in C/PHP per troncare il path checks (Poison Null Byte).
- **`num_duplicate_params`**: Parametri con lo stesso nome ripetuti più volte (HTTP Parameter Pollution).
- **`max_path_segment_len`**: Un singolo frammento di cartella eccessivamente lungo.
- **`num_uppercase_in_query`**: Uso anomalo di maiuscole, tecnica per bypassare regex case-sensitive.
- **`body_to_url_length_ratio`**: Rapporto tra dimensione Body e URL. Uno squilibrio netto (Body enorme per URL inesistente) alza il sospetto.
- **`has_base64_pattern`**: Ricerca euristica di pattern Base64.
- **`num_semicolons_body`**: Abuso del carattere `;`, usato tipicamente in Command Injection (Linux bash concatenation).

## 6. Coerenza Strutturale del Protocollo
Verifica che la richiesta rispetti lo standard RFC dell'HTTP.
- **`method_body_mismatch`**: Un verbo `GET` che presenta un Body (non standard, usato in attacchi Smuggling).
- **`content_type_body_mismatch`**: Body presente senza un `Content-Type` specificato (o viceversa).

## 7. Pattern Malevoli e Firme Ibride
Sebbene l'Isolation Forest sia un sistema non-supervisionato, contare occorrenze di pattern aiuta il modello a "raggruppare" (clusterizzare) questi eventi rari nello spazio vettoriale. L'IA decide in autonomia il peso di questi conteggi.
- **`path_traversal_tokens_url` / `_body`**: Conteggio di `../` o `%2e%2e/` (Directory Traversal).
- **`sql_keyword_count_url` / `_body`**: Conteggio parole chiave SQL (es. UNION, SELECT, OR 1=1).
- **`xss_token_count_url` / `_body`**: Conteggio di tag script, `onerror`, ecc.
- **`os_cmd_token_count_url` / `_body`**: Comandi di sistema Linux/Windows (es. rm, wget, curl, powershell).
- **`suspicious_ext_count_url` / `_body`**: Estensioni sensibili o backup (.bak, .sh, .ini, .conf).
