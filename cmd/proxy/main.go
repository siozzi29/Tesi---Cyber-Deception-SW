package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"cyber-deception-waap/pkg/interceptor"
	"cyber-deception-waap/pkg/listener"
	"cyber-deception-waap/pkg/router"
)

// =====================================================================
// MOCK RESIDUI (Router e AIClient sono ora reali, questi restano finché
// non implementiamo anche URLInjector e Telemetry)
// =====================================================================

type MockAI struct{}

func (m *MockAI) GetRiskScore(r *http.Request) (float64, error) {
	log.Println("[MOCK AI] Simulazione inferenza... Risk Score calcolato: 0.1 (Sano)")
	return 0.1, nil
}

type MockInjector struct{}

func (m *MockInjector) IsHoneyURL(path string) bool { return false }
func (m *MockInjector) Inject(body []byte) []byte   { return body }

type MockTelemetry struct{}

func (m *MockTelemetry) LogAsync(r *http.Request, riskScore float64, isPoisoned bool) {
	log.Printf("[MOCK TELEMETRY] Log inviato a Fluent Bit. Score: %.2f, Poisoned: %v\n", riskScore, isPoisoned)
}

// =====================================================================
// MAIN
// =====================================================================
func main() {
	log.Println("Inizializzazione Reverse Proxy WAAP...")

	// ⚠️ SOSTITUISCI CON L'IP INTERNO REALE DELLA TUA VM WORDPRESS
	// (Console GCP -> Compute Engine -> istanza WordPress -> IP interno)
	wordpressBackend := os.Getenv("WORDPRESS_BACKEND")
	if wordpressBackend == "" {
		wordpressBackend = "http://10.128.0.4:80" // fallback di sviluppo, DA CAMBIARE
		log.Printf("[WARN] WORDPRESS_BACKEND non impostata, uso fallback: %s", wordpressBackend)
	}

	legitRouter, err := router.NewLegitRouter(wordpressBackend)
	if err != nil {
		log.Fatalf("Errore creazione router verso WordPress: %v", err)
	}

	mockAI := &MockAI{}
	mockInj := &MockInjector{}
	mockTel := &MockTelemetry{}

	vigile := interceptor.NewSecurityInterceptor(mockAI, mockInj, legitRouter, mockTel)

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