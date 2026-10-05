@echo off
chcp 65001 > nul
title WAAP Demo - Avvio Sistema

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║         WAAP - Cyber Deception ^& Machine Learning            ║
echo ║         Demo per Presentazione di Laurea                     ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.

:: Verifica che Docker sia avviato
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRORE] Docker non è in esecuzione!
    echo Avvia Docker Desktop e riprova.
    pause
    exit /b 1
)

echo [1/3] Arresto di eventuali container precedenti...
docker compose down --remove-orphans > nul 2>&1

echo [2/3] Build e avvio dei container (potrebbe richiedere qualche minuto al primo avvio)...
echo.
docker compose up --build -d

if %errorlevel% neq 0 (
    echo.
    echo [ERRORE] Qualcosa è andato storto. Verifica i log con:
    echo   docker compose logs
    pause
    exit /b 1
)

echo.
echo [3/3] Attendo che i servizi siano pronti...
timeout /t 8 /nobreak > nul

echo.
echo ╔══════════════════════════════════════════════════════════════╗
echo ║  SISTEMA AVVIATO — URL per il demo:                         ║
echo ║                                                              ║
echo ║  WAAP Proxy (sito protetto):                                 ║
echo ║    http://localhost:8080                                     ║
echo ║                                                              ║
echo ║  Dashboard Telemetria (statistiche live):                    ║
echo ║    http://localhost:9090/dashboard                           ║
echo ║                                                              ║
echo ║  AI Engine (Swagger UI):                                     ║
echo ║    http://localhost:8000/docs                                ║
echo ║                                                              ║
echo ║  Backend Demo diretto (senza protezione):                    ║
echo ║    http://localhost:8888                                     ║
echo ╚══════════════════════════════════════════════════════════════╝
echo.
echo Apro il browser automaticamente...
timeout /t 2 /nobreak > nul
start http://localhost:8080
start http://localhost:9090/dashboard

echo.
echo Premi un tasto per fermare tutti i container a fine demo.
pause > nul

echo.
echo Arresto dei container...
docker compose down
echo Sistema fermato. Arrivederci!
timeout /t 2 /nobreak > nul
