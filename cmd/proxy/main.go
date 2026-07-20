package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"cyber-deception-waap/pkg/aiclient"
	"cyber-deception-waap/pkg/interceptor"
	"cyber-deception-waap/pkg/listener"
	"cyber-deception-waap/pkg/router"
)

// =====================================================================
// MOCK RESIDUI (Injector e Telemetry, non ancora implementati)
// =====================================================================

type MockInjector struct{}

func (m *MockInjector) IsHoneyURL(path string) bool { return false }
func (m *MockInjector) Inject(body []byte) []byte   { return body }

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
	wordpressBackend := os.Getenv("WORDPRESS_BACKEND")
	if wordpressBackend == "" {
		wordpressBackend = "http://10.132.0.4:80" // fallback di sviluppo, DA CAMBIARE
		log.Printf("[WARN] WORDPRESS_BACKEND non impostata, uso fallback: %s", wordpressBackend)
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
	aiTimeoutMs := 150
	if v := os.Getenv("AI_TIMEOUT_MS"); v != "" {
		if parsed, err := strconv.Atoi(v); err == nil {
			aiTimeoutMs = parsed
		}
	}
	realAI := aiclient.NewHTTPAIClient(aiEndpoint, time.Duration(aiTimeoutMs)*time.Millisecond)

	// --- Soglia di rischio (deve combaciare con risk_threshold.joblib) ---
	riskThreshold := interceptor.DefaultRiskThreshold
	if v := os.Getenv("RISK_THRESHOLD"); v != "" {
		if parsed, err := strconv.ParseFloat(v, 64); err == nil {
			riskThreshold = parsed
		}
	}

	mockInj := &MockInjector{}
	mockTel := &MockTelemetry{}

	vigile := interceptor.NewSecurityInterceptor(realAI, mockInj, legitRouter, mockTel, riskThreshold)

	srv := listener.NewServer(":8080", vigile)

	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		if err := srv.Start(); err != nil {
			log.Fatalf("Errore critico del server: %v", err)
		}
	}()

	<-stopChan
	log.Println("\nSegnale ricevuto. Inizio Graceful Shutdown...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Stop(ctx); err != nil {
		log.Fatalf("Errore durante lo shutdown: %v", err)
	}

	log.Println("Server spento correttamente.")
}
