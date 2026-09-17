# Cyber Deception WAAP — Architecture & Project Context

> **Tesi di Laurea Triennale in Informatica**  
> **Candidato:** Simone Iozzi  
> **Azienda Ospitante:** Apuliasoft  
> **Titolo:** Progettazione e implementazione di un Web Application & API Protection (WAAP) integrato con Cyber Deception dinamica e rilevamento anomalie basato su Machine Learning (Isolation Forest).

---

## 1. Executive Summary & Motivazioni

I Web Application Firewall (WAF) tradizionali basati su regole e firme statiche (es. OWASP Core Rule Set) soffrono di due limiti strutturali:
1. **Inefficacia contro attacchi Zero-Day**: non riconoscono pattern d'attacco nuovi o payload pesantemente offuscati.
2. **Asimmetria a favore dell'attaccante**: restituendo subito un errore HTTP `403 Forbidden`, informano l'hacker della presenza di un filtro e gli permettono di automatizzare tentativi di bypass a costo computazionale nullo.

Questo progetto risolve entrambi i problemi combinando:
- **Cyber Deception Dinamica**: iniezione a runtime di trappole invisibili agli utenti reali (*Honey-Tokens / Honey-URLs*) nel DOM HTML, che identificano scanner, crawler e bot automatizzati con **accuratezza del 100% e zero falsi positivi**.
- **Intelligenza Artificiale Comportamentale**: modello *Isolation Forest* non supervisionato addestrato sul traffico normale di WordPress, in grado di quantificare in tempo reale il grado di anomalia (*Risk Score*) di qualsiasi richiesta HTTP non nota.
- **Risposta Reattiva Asimmetrica (Tarpitting)**: rallentamento deliberato di 3 secondi imposto all'attaccante prima di servire una pagina civetta di finto errore, invertendo il consumo di risorse contro l'attaccante (*Slowloris inverso*).

---

## 2. Architettura di Sistema (C4 Container View)

```
                            INTERNET (Utenti & Attaccanti)
                                          │
                                          ▼
                ┌───────────────────────────────────────────────────┐
                │             waap-proxy (Google Cloud Run)         │
                │   • Listener HTTP/HTTPS pubblico                  │
                │   • Security Interceptor (Logica di instradamento)│
                │   • Honey-URL Injector & Memory Tracker           │
                │   • Client OIDC Google Cloud (Service-to-Service) │
                │   • Dashboard di telemetria (/dashboard)         │
                └───────────────┬───────────────────┬───────────────┘
                                │                   │
           (Token OIDC Privato) │                   │ (Traffico Verificato Sano)
                                ▼                   ▼
┌───────────────────────────────────────────────┐ ┌──────────────────────────────────────────┐
│      waap-ai-engine (Cloud Run Privato)       │ │     wordpress-1-vm (Compute Engine VM)   │
│   • FastAPI REST Microservice (/score)        │ │   • Sito target reale (WordPress 6.x)    │
│   • Feature Extractor (44 dimensioni)         │ │   • Apache Web Server + MySQL Database   │
│   • Isolation Forest Model (.joblib)          │ │   • Protetto da accesso pubblico diretto │
└───────────────────────────────────────────────┘ └──────────────────────────────────────────┘
```

---

## 3. Mappatura Dettagliata dei File del Repository

### 📁 Modulo Reverse Proxy (`/proxy`) — *Linguaggio: Go 1.22*

* **[`proxy/cmd/proxy/main.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/cmd/proxy/main.go)**:
  * **Ruolo**: Entry-point del servizio proxy. Inizializza tutti i sottosistemi iniettando le dipendenze (AI Client, Injector, Legit Router, Telemetry, Interceptor).
  * **Design**: Gestione *fail-fast* all'avvio su variabili obbligatorie (`WORDPRESS_BACKEND`), gestione del graceful shutdown su segnali `SIGINT`/`SIGTERM` con drain delle connessioni in volo (5 secondi).
* **[`proxy/pkg/listener/server.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/listener/server.go)**:
  * **Ruolo**: Gestione del listener HTTP e configurazione dei timeout di rete anti-DoS (`ReadHeaderTimeout: 3s` contro attacchi Slowloris, `ReadTimeout: 5s`, `WriteTimeout: 10s`, `IdleTimeout: 15s`).
  * **Single-Port Routing**: Integra l'endpoint `/dashboard` sulla stessa porta principale `$PORT` per compatibilità con l'architettura serverless a porta singola di Cloud Run.
* **[`proxy/pkg/interceptor/interceptor.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/interceptor/interceptor.go)**:
  * **Ruolo**: Il "Vigile Urbano" centrale (`SecurityInterceptor`). Coordina l'analisi di sicurezza e decide l'instradamento di ogni singola richiesta HTTP.
  * **Workflow di Decisione**:
    1. *Auth Bypass*: Utenti loggati su WordPress (`wordpress_logged_in_*`) bypassano l'AI.
    2. *Controllo Deception*: Se l'URL corrisponde a un Honey-URL attivo $\rightarrow$ Tarpit immediato (Score = 1.0).
    3. *Whitelist*: Esenzione per rotta statica front-end (`GET /`), form di login (`/wp-login.php`) e asset statici (`.css`, `.js`, `.png`, `.woff2`, ecc.).
    4. *Inferenza AI*: Chiamata a `waap-ai-engine`. Se l'AI fallisce/va in timeout $\rightarrow$ logica **Fail-Open** (non interrompe il servizio agli utenti sani).
    5. *Routing Soglia*: Se `Score > 0.4760` $\rightarrow$ Tarpit + Civetta. Altrimenti $\rightarrow$ Inoltro trasparente a WordPress.
* **[`proxy/pkg/injector/injector.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/injector/injector.go)**:
  * **Ruolo**: Gestisce il ciclo di vita degli Honey-Tokens.
  * **Dettagli tecnici**:
    * Genera token crittografici casuali a 16 caratteri hex con prefisso mimetico `/sys/health-check-<token>`.
    * Memoria concorrente sicura (`sync.RWMutex`) con TTL (30 minuti) e goroutine di pulizia periodica (*sweep* ogni 5 minuti).
    * Protezione anti memory-leak con tetto massimo di 50.000 token attivi contemporanei.
* **[`proxy/pkg/interceptor/injecting_writer.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/interceptor/injecting_writer.go)**:
  * **Ruolo**: `http.ResponseWriter` decoratore che intercetta lo stream di risposta HTML di WordPress e inietta l'esca `<a href="..." style="display:none!important;..." tabindex="-1" aria-hidden="true">.` appena prima del tag di chiusura `</body>`.
* **[`proxy/pkg/router/router.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/router/router.go)**:
  * **Ruolo**: Gestisce l'effettivo inoltro di rete al backend WordPress e l'esecuzione del Tarpit.
  * **Funzionalità chiave**:
    * `ModifyResponse`: Riscrive al volo tutti gli URL generati da WordPress (`http://` $\rightarrow$ `https://`), risolvendo categoricamente il blocco *Mixed Content* nei browser moderni sia su domini Cloud Run che su domini custom (`apuliasoft.com`).
    * `Director`: Inoltra gli header corretti (`X-Forwarded-Proto: https`, `X-Forwarded-Host`, `X-Real-IP`).
    * `TarpitAndTrap`: Sospende la goroutine per 3 secondi (`time.Sleep`) prima di inviare la risposta di errore civetta.
* **[`proxy/pkg/aiclient/aiclient.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/aiclient/aiclient.go)**:
  * **Ruolo**: Client HTTP verso il microservizio FastAPI.
  * **Sicurezza Cloud**: Interroga il GCP Metadata Server (`http://metadata.google.internal/...`) per ottenere token di identità OIDC firmati, memorizzandoli in cache con scadenza per autenticare in modo trasparente e sicuro le chiamate private Service-to-Service su Cloud Run.
* **[`proxy/pkg/interceptor/dashboard.go`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/pkg/interceptor/dashboard.go)**:
  * **Ruolo**: Handler Web (`/dashboard`, `/dashboard/stats`, `/dashboard/events`) con interfaccia grafica reattiva per il monitoraggio in tempo reale e supporto Human-in-the-Loop (HITL) per l'esportazione di campioni.
* **[`proxy/Dockerfile`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/proxy/Dockerfile)**:
  * Build multi-stage ottimizzata (`golang:1.22-alpine` $\rightarrow$ `alpine:latest`), container snello e privo di dipendenze inutili.

---

### 📁 Modulo Intelligenza Artificiale (`/ai-service`) — *Linguaggio: Python 3.11/FastAPI*

* **[`ai-service/src/main.py`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/src/main.py)**:
  * **Ruolo**: API REST asincrona con FastAPI.
  * **Endpoints**:
    * `POST /score`: Riceve i 4 campi canonici (`url`, `method`, `content`, `content_type`), estrae il vettore di feature, calcola l'anomaly score con l'Isolation Forest, normalizza tra $[0, 1]$ e restituisce `risk_score`, `is_anomalous` e `threshold`.
    * `GET /health`: Health-check per il monitoraggio di Cloud Run.
    * `POST /retrain`: Endpoint di riaddestramento automatico on-the-fly.
* **[`ai-service/src/features.py`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/src/features.py)**:
  * **Ruolo**: **Unica fonte di verità** per la trasformazione della richiesta HTTP grezza in un vettore numerico a 44 dimensioni:
    1. *Strutturali*: Lunghezza URL/Path/Query, numero e dimensione parametri, profondità path.
    2. *Tipografiche*: Conteggio cifre, caratteri speciali, rapporto simboli/alfanumerici.
    3. *Entropiche*: Entropia di Shannon su URL, Path, Query e Body (identificazione offuscamento).
    4. *Firme di Attacco*: Keyword SQL Injection (`UNION`, `SELECT`, `OR 1=1`), token XSS (`<script>`, `onerror=`), Path Traversal (`../`, `%2e%2e/`), Command Injection (`rm`, `wget`, `;`).
    5. *Evasione WAF*: Percentuale caratteri encoded, doppio URL-encoding (`%2527`), Null-Byte (`%00`), HTTP Parameter Pollution.
    6. *Coerenza Protocollo*: Mismatch tra metodo e presenza body (es. GET con body), mismatch con `Content-Type`.
* **[`ai-service/src/preprocess.py`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/src/preprocess.py)**:
  * **Ruolo**: Pulizia, normalizzazione, parsing e deduplicazione dei dataset eterogenei (CSIC 2010, CSIC ECML, traffico WordPress reale).
* **[`ai-service/src/train.py`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/src/train.py)**:
  * **Ruolo**: Pipeline di addestramento e validazione del modello Isolation Forest.
  * **Strategia Domain-Specific**:
    * Si isolano gli attacchi noti dai dataset CSIC.
    * Si allena il modello non supervisionato **esclusivamente sul traffico normale reale di WordPress** (ottenuto tramite spider e generatori di sessione).
    * Esegue una Grid Search sul set di validazione imponendo un vincolo paranoico di **False Positive Rate (FPR) $\le 1\%$** per determinare la soglia di rischio ottimale ($\tau = 0.4760 / 0.5908$).
    * Salva gli artefatti in `models/`: `isolation_forest.joblib`, `risk_threshold.joblib`, `score_bounds.joblib`.
* **[`ai-service/src/spider_wordpress.py`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/src/spider_wordpress.py)**, **`bot_post_wordpress.py`**, **`augment_*.py`**:
  * **Ruolo**: Script di crawling e simulazione comportamentale per popolare il dataset di traffico lecito con chiamate realistiche all'applicazione WordPress.
* **[`ai-service/Dockerfile`](file:///c:/Users/simon/Desktop/Tesi---Cyber-Deception-SW/ai-service/Dockerfile)**:
  * Container basato su `python:3.11-slim`, configurato per leggere la porta dinamica `$PORT` di Cloud Run e lanciare il server Uvicorn.

---

## 4. Flusso Operativo End-to-End di una Richiesta

```
[Richiesta HTTP dal Client]
         │
         ▼
[1. Proxy Listener: Controllo Timeout Anti-DoS (3s / 5s / 10s)]
         │
         ▼
[2. Interceptor: L'utente è autenticato su WordPress?]
         ├─► SÌ  ──► [Inoltro Diretto a WordPress]
         │
         ▼ NO
[3. L'URL è un Honey-Token attivo registrato?]
         ├─► SÌ  ──► [CYBER DECEPTION HIT: Log Telemetria -> TARPIT (3s) -> Pagina Civetta]
         │
         ▼ NO
[4. La rotta è in Whitelist statica (GET /, Login, .css, .js, .png)?]
         ├─► SÌ  ──► [Inoltro a WordPress + Iniezione Honey-URL nel body HTML]
         │
         ▼ NO
[5. Chiamata ad AI Engine (/score) con Token OIDC]
         │
         ├─► [Errore/Timeout AI?] ──► [Logica FAIL-OPEN: Inoltro a WordPress con Score -1]
         │
         ▼ [Score Ricevuto]
[6. Valutazione Soglia di Rischio: Score > 0.4760?]
         ├─► SÌ (Attacco Rilevato) ──► [TARPIT (3s) -> Risposta Finto Errore]
         │
         └─► NO (Traffico Sano)   ──► [Inoltro a WordPress + Riscrittura HTTPS + Iniezione Honey-URL]
```

---

## 5. Configurazione e Deploy su Google Cloud Platform

### Parametri dei Servizi Cloud Run

1. **`waap-ai-engine` (Microservizio AI)**:
   * **Visibilità**: **Privata** (Nessun accesso `allUsers`).
   * **Autenticazione**: Richiede il ruolo IAM `roles/run.invoker` assegnato al Service Account `175735032844-compute@developer.gserviceaccount.com`.
   * **Risorse**: CPU 1, RAM 1 GiB.

2. **`waap-proxy` (Reverse Proxy WAAP)**:
   * **Visibilità**: **Pubblica** (`--allow-unauthenticated`).
   * **Porta**: 8080 (mappata automaticamente da `$PORT`).
   * **Variabili d'Ambiente**:
     * `WORDPRESS_BACKEND`: `http://34.53.145.249:80` (IP interno o VM di WordPress).
     * `AI_SERVICE_ENDPOINT`: `https://waap-ai-engine-175735032844.europe-west1.run.app/score`.
     * `RISK_THRESHOLD`: `0.4760`.
   * **Risorse**: CPU 1, RAM 512 MiB.

3. **`wordpress-1-vm` (Backend Target)**:
   * Istanza Compute Engine con Apache2 e WordPress.
   * **Protezione WAF Bypass**: Accesso pubblico sulla porta 80 chiuso da Firewall GCP, raggiungibile unicamente attraverso le chiamate inoltrate da `waap-proxy`.

---

## 6. Risultati della Validazione Sperimentale

| Scenario di Test | Richiesta Effettuata | Risk Score | Comportamento del WAAP | Risultato |
| :--- | :--- | :---: | :--- | :---: |
| **Navigazione Lecita** | `GET /?p=126` | `0.0000` | Inoltrato a WordPress in ~35ms | ✅ Successo (Grafica e asset caricati) |
| **Attacco Cross-Site Scripting (XSS)** | `GET /?s=<script>alert('xss')</script>` | `0.5032` | Intrappolato nel Tarpit (3.000ms) | ✅ Rilevato & Bloccato |
| **Attacco SQL Injection** | `GET /?p=1+UNION+SELECT+user,pass...` | `0.6070` | Intrappolato nel Tarpit (3.000ms) | ✅ Rilevato & Bloccato |
| **Visita Trappola Honey-URL** | `GET /sys/health-check-704c08...` | `1.0000` | Intrappolato nel Tarpit (3.000ms) | ✅ Rilevamento Deterministico 100% |
| **Crash/Timeout AI Simulata** | Chiamata con servizio AI offline | `-1.0000` | Inoltro trasparente (Fail-Open) | ✅ Continuità del servizio garantita |

---

## 7. Comandi di Esecuzione e Test Rapidi

### Esecuzione Suite di Test Unitaria (Go)
```bash
cd proxy
go test -v ./...
```

### Riaddestramento Modello AI in Locale
```bash
cd ai-service
python -m src.train
```

### Deploy Aggiornamenti su Cloud Shell
```bash
# Deploy AI Engine
gcloud run deploy waap-ai-engine \
  --source ./ai-service \
  --region europe-west1 \
  --memory 1Gi \
  --cpu 1 \
  --no-allow-unauthenticated

# Deploy Proxy
gcloud run deploy waap-proxy \
  --source ./proxy \
  --region europe-west1 \
  --memory 512Mi \
  --cpu 1 \
  --set-env-vars="WORDPRESS_BACKEND=http://34.53.145.249,AI_SERVICE_ENDPOINT=https://waap-ai-engine-175735032844.europe-west1.run.app/score,RISK_THRESHOLD=0.4760" \
  --allow-unauthenticated
```
