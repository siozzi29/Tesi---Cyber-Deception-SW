import streamlit as st
import subprocess
import requests
import random
import time

# Configurazione della pagina
st.set_page_config(page_title="WAAP Cyber Deception", layout="wide")
st.title("🛡️ Dashboard di Controllo WAAP")

# Dizionari di payload pre-impostati
BENIGN_PAYLOADS = [
    {"url": "/home", "method": "GET", "content": "", "content_type": ""},
    {"url": "/api/users?id=123", "method": "GET", "content": "", "content_type": ""},
    {"url": "/login", "method": "POST", "content": "user=simone&pass=1234", "content_type": "application/x-www-form-urlencoded"}
]

MALICIOUS_PAYLOADS = [
    {"url": "/login?user=admin' OR 1=1--", "method": "GET", "content": "", "content_type": ""},
    {"url": "/api/v1/search?query=union select * from information_schema -- ../../../../etc/passwd <script>alert(1)</script>", "method": "POST", "content": "username=admin or 1=1 --&cmd=xp_cmdshell", "content_type": "application/x-www-form-urlencoded"},
    {"url": "/index.php?page=../../../../etc/shadow", "method": "GET", "content": "", "content_type": ""}
]

# Gestione dello stato del server
if 'server_process' not in st.session_state:
    st.session_state.server_process = None

col1, col2 = st.columns(2)

with col1:
    st.header("1. Gestione Motore AI")
    st.write("Avvia l'Isolation Forest su FastAPI.")
    
    # Pulsante per accendere il server
    if st.button("🚀 Avvia Server FastAPI"):
        if st.session_state.server_process is None:
            # Lancia il server richiamando il modulo uvicorn partendo dalla cartella ai-service
            st.session_state.server_process = subprocess.Popen(
                ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
            )
            st.success("Server in fase di avvio sulla porta 8000! Attendi 2-3 secondi prima di testare.")
        else:
            st.warning("Il server è già in esecuzione!")
            
    # Pulsante per spegnere il server
    if st.button("🛑 Ferma Server"):
        if st.session_state.server_process:
            st.session_state.server_process.terminate()
            st.session_state.server_process = None
            st.success("Server fermato correttamente.")

with col2:
    st.header("2. Simulazione Traffico")
    tipo_attacco = st.radio("Seleziona la tipologia di traffico:", ("Traffico Legittimo", "Attacco Informatico"))
    
    if st.button("⚡ Invia Payload"):
        if st.session_state.server_process is None:
            st.error("Devi prima avviare il server!")
        else:
            # Scelta casuale del payload
            payload = random.choice(BENIGN_PAYLOADS) if tipo_attacco == "Traffico Legittimo" else random.choice(MALICIOUS_PAYLOADS)
            
            st.write("**Richiesta in uscita:**")
            st.json(payload)
            
            try:
                # Contatta l'API FastAPI locale
                response = requests.post("http://127.0.0.1:8000/score", json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    st.write("**Risposta dall'Intelligenza Artificiale:**")
                    
                    # Logica visiva in base al risultato
                    if data["is_anomalous"]:
                        st.error(f"🚨 MINACCIA BLOCCATA! Risk Score: {data['risk_score']:.4f} (Soglia: {data['threshold']:.4f})")
                    else:
                        st.success(f"✅ TRAFFICO CONSENTITO. Risk Score: {data['risk_score']:.4f} (Soglia: {data['threshold']:.4f})")
                    
                    st.json(data)
                else:
                    st.error(f"Errore dal server: {response.status_code}")
            except requests.exceptions.ConnectionError:
                st.error("Impossibile contattare il server. Sicuro che abbia finito di avviarsi?")