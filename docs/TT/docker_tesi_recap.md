# Architettura di Deployment e Containerizzazione: Analisi per la Tesi

Questo documento riassume le motivazioni architetturali e tecniche dietro l'utilizzo di Docker per il sistema WAAP (Web Application API Protection) sviluppato. Può essere utilizzato come traccia per il capitolo relativo al *Deployment* o alle *Scelte Architetturali* nella stesura della tesi.

---

## 1. Containerizzazione: Cos'è e perché è stata scelta

Nello sviluppo di software moderno, uno dei problemi più comuni è il noto paradosso del *"sul mio computer funziona"*. Il nostro sistema WAAP è un'infrastruttura complessa, composta da due anime tecnologiche profondamente diverse:
*   Un **Reverse Proxy** scritto in **Go** (ottimizzato per la velocità di rete e la gestione della concorrenza).
*   Un **Motore di Intelligenza Artificiale** scritto in **Python** (che fa uso del framework FastAPI e di librerie di Machine Learning come `scikit-learn` e `numpy`).

Per risolvere il problema della distribuzione e delle dipendenze, si è scelto di adottare il paradigma della **Containerizzazione tramite Docker**. 

Docker permette di creare dei *Container*, ovvero degli ambienti isolati (simili a macchine virtuali estremamente leggere) che includono al loro interno tutto il necessario per l'esecuzione del codice: il sistema operativo di base, il runtime dei linguaggi (Go e Python), il codice sorgente e le versioni esatte delle librerie necessarie.

**Vantaggi evidenziabili nella tesi:**
*   **Riproducibilità:** Il sistema è totalmente *Plug & Play*. Eseguendo il comando `docker compose up`, l'infrastruttura viene istanziata in modo identico e garantito su qualsiasi macchina (Windows, Mac, o server Cloud Linux), annullando i tempi di configurazione ambientale.
*   **Isolamento:** Le librerie Python per il Machine Learning (spesso soggette a conflitti di versione) non "sporcano" il sistema operativo host.

---

## 2. Architettura a Microservizi e Modello Ibrido

Il deployment adottato non è monolitico, ma segue un'**Architettura a Microservizi**. Attraverso Docker Compose, abbiamo definito uno *Stack* (un raggruppamento logico) chiamato `tesi---cyber-deception-sw`, composto da due microservizi indipendenti ma comunicanti:

1.  **Container `waap_reverse_proxy`:** Il punto di ingresso della rete. Intercetta il traffico in entrata, implementa la logica di Tarpitting (difesa attiva) ed espone il dashboard di monitoraggio.
2.  **Container `waap_ai_engine`:** Il cervello del sistema. Riceve i metadati dal proxy, calcola il *Risk Score* usando il modello di Isolation Forest e restituisce un verdetto in tempo reale.

Questa separazione dei ruoli offre scalabilità: se l'analisi AI dovesse diventare il collo di bottiglia, potremmo duplicare solo il container `waap_ai_engine` senza toccare il proxy di rete.

Inoltre, il sistema dimostra una grande flessibilità: lo "scudo" WAAP gira in locale all'interno di Docker, ma protegge un'applicazione (WordPress) situata remotamente su una **Virtual Machine in Google Cloud (GCP)**. Questo modello ibrido prova che il sistema può operare come gateway di sicurezza indipendente dalla posizione fisica dell'infrastruttura da difendere.

---

## 3. Analisi delle Performance (Riferimento alla schermata Docker Desktop)

L'analisi del pannello di controllo di Docker Desktop fornisce metriche cruciali per validare l'efficienza del software sviluppato. Osservando il consumo di risorse in *idle* o sotto carico standard:

*   **Consumo CPU (~ 0.12%):** L'intero stack di sicurezza impatta in maniera quasi impercettibile sul processore (nonostante il sistema operi su un host con 16 CPU logiche). Questo certifica l'efficienza di Go per il networking e l'ottimizzazione del modello di Machine Learning per l'inferenza rapida.
*   **Consumo RAM (~ 393 MB):** Meno di 400 Megabyte per mantenere attivi simultaneamente un server HTTP ad alte prestazioni e un ambiente Python completo di modello ML caricato in memoria. 

Queste metriche sono un **risultato eccellente** da portare in sede di discussione. Dimostrano che il sistema WAAP non solo è efficace nel rilevamento delle anomalie, ma è stato ingegnerizzato per essere **estremamente leggero ed efficiente (Low Overhead)**. Può essere integrato in ambienti di produzione reali senza causare rallentamenti percettibili o richiedere l'acquisto di server costosi.
