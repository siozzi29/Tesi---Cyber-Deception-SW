package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"

	"cyber-deception-waap/pkg/aiclient"
	"cyber-deception-waap/pkg/injector"
	"cyber-deception-waap/pkg/interceptor"
	"cyber-deception-waap/pkg/listener"
	"cyber-deception-waap/pkg/router"
)

// =====================================================================
// TELEMETRY PLACEHOLDER
// =====================================================================

type MockTelemetry struct{}

func (m *MockTelemetry) LogAsync(r *http.Request, riskScore float64, isPoisoned bool) {
	log.Printf("[MOCK TELEMETRY] Log inviato a Fluent Bit. Score: %.4f, Poisoned: %v\n", riskScore, isPoisoned)
}

// =====================================================================
// MAIN
// =====================================================================
func main() {
	log.Println("Inizializzazione Reverse Proxy WAAP...")

	// --- Router verso WordPress ---
	// FIX: niente più fallback silenzioso su un IP che potrebbe non esistere
	// in produzione. Se WORDPRESS_BACKEND non è settata, meglio un crash
	// esplicito all'avvio (fail-fast) che un 502 silenzioso su tutto il
	// traffico legittimo scoperto in produzione da un utente arrabbiato.
	wordpressBackend := os.Getenv("WORDPRESS_BACKEND")
	if wordpressBackend == "" {
		log.Fatal("WORDPRESS_BACKEND non impostata: obbligatoria, niente fallback. " +
			"Esempio: WORDPRESS_BACKEND=http://10.132.0.2:80 (IP interno VPC di wordpress-1-vm)")
	}
	legitRouter, err := router.NewLegitRouter(wordpressBackend)
	if err != nil {
		log.Fatalf("Errore creazione router verso WordPress: %v", err)
	}

	// --- Client verso il servizio FastAPI (Isolation Forest) ---
	aiEndpoint := os.Getenv("AI_SERVICE_ENDPOINT")
	if aiEndpoint == "" {
		aiEndpoint = "http://localhost:8000/score" // stessa VM per default
		log.Printf("[WARN] AI_SERVICE_ENDPOINT non impostata, uso fallback: %s", aiEndpoint)
	}
	// Default aggiornato: vedi commento in aiclient.NewHTTPAIClient sul
	// trade-off latenza/accuratezza (non è più 150ms, ora 20ms di default).
	aiTimeoutMs := 0 // 0 => aiclient usa il suo default interno (20ms)
	if v := os.Getenv("AI_TIMEOUT_MS"); v != "" {
		parsed, err := strconv.Atoi(v)
		if err != nil {
			log.Printf("[WARN] AI_TIMEOUT_MS=%q non valido (%v), uso il default interno", v, err)
		} else {
			aiTimeoutMs = parsed
		}
	}
	realAI := aiclient.NewHTTPAIClient(aiEndpoint, time.Duration(aiTimeoutMs)*time.Millisecond)

	// --- Soglia di rischio (deve combaciare con quanto persistito lato ai-service) ---
	riskThreshold := interceptor.DefaultRiskThreshold
	if v := os.Getenv("RISK_THRESHOLD"); v != "" {
		parsed, err := strconv.ParseFloat(v, 64)
		if err != nil {
			log.Printf("[WARN] RISK_THRESHOLD=%q non valido (%v), uso il default %.4f", v, err, interceptor.DefaultRiskThreshold)
		} else {
			riskThreshold = parsed
		}
	}

	// TTL 0 => l'injector usa il proprio default interno (defaultTTL, 30min),
	// così la durata dei honeytoken resta definita in un solo posto (injector.go).
	realInj := injector.NewHoneyURLInjector(0)
	defer realInj.Close()

	mockTel := &MockTelemetry{}

	vigile := interceptor.NewSecurityInterceptor(realAI, realInj, legitRouter, mockTel, riskThreshold)

	// --- Listener pubblico (dietro il Load Balancer) ---
	publicAddr := os.Getenv("LISTEN_ADDR")
	if publicAddr == "" {
		publicAddr = ":8080"
	}
	srv := listener.NewServer(publicAddr, vigile)

	// --- Listener dashboard (SEPARATO, non esposto dal Load Balancer) ---
	// FIX: prima il dashboard viveva sullo stesso mux del traffico pubblico
	// (pkg/listener/server.go), quindi era raggiungibile da internet senza
	// auth attraverso wordpress-lb -> instance-group-waap-proxy:8080. Ora è
	// un http.Server indipendente, su un indirizzo diverso (di default solo
	// localhost) che il LB non tocca. Va comunque protetto anche a livello
	// di firewall GCP se lo esponete sull'IP interno della VPC.
	dashboardAddr := os.Getenv("DASHBOARD_ADDR")
	if dashboardAddr == "" {
		dashboardAddr = "127.0.0.1:9090"
		log.Printf("[WARN] DASHBOARD_ADDR non impostata, uso fallback locale: %s", dashboardAddr)
	}
	dashboardSrv := listener.NewDashboardServer(dashboardAddr, vigile)

	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := srv.Start(); err != nil {
			log.Fatalf("Errore critico del server pubblico: %v", err)
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		if err := dashboardSrv.StartDashboard(); err != nil {
			log.Fatalf("Errore critico del server dashboard: %v", err)
		}
	}()

	<-stopChan
	log.Println("\nSegnale ricevuto. Inizio Graceful Shutdown...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Stop(ctx); err != nil {
		log.Printf("[ERR] Errore durante lo shutdown del server pubblico: %v", err)
	}
	if err := dashboardSrv.StopDashboard(ctx); err != nil {
		log.Printf("[ERR] Errore durante lo shutdown del server dashboard: %v", err)
	}

	wg.Wait()
	log.Println("Server spenti correttamente.")
}
