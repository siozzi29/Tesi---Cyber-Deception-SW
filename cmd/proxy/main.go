package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	// Assicurati che "cyber-deception-waap" sia il nome esatto del tuo go.mod
	"cyber-deception-waap/pkg/interceptor"
	"cyber-deception-waap/pkg/listener"
)

// =====================================================================
// MOCK DEI SOTTOSISTEMI (Livello 3 - Modello C4)
// Usiamo queste struct finte solo per testare che l'architettura compili
// =====================================================================

type MockAI struct{}

func (m *MockAI) GetRiskScore(r *http.Request) (float64, error) {
	log.Println("[MOCK AI] Simulazione inferenza... Risk Score calcolato: 0.1 (Sano)")
	return 0.1, nil
}

type MockInjector struct{}

func (m *MockInjector) IsHoneyURL(path string) bool { return false }
func (m *MockInjector) Inject(body []byte) []byte   { return body }

type MockRouter struct{}

func (m *MockRouter) Forward(w http.ResponseWriter, r *http.Request) {
	log.Println("[MOCK ROUTER] Instradamento verso l'Infrastruttura Reale in < 2ms...")
}
func (m *MockRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	log.Println("[MOCK ROUTER] Tarpitting attivato: Attaccante intrappolato!")
}

type MockTelemetry struct{}

func (m *MockTelemetry) LogAsync(r *http.Request, riskScore float64, isPoisoned bool) {
	log.Printf("[MOCK TELEMETRY] Log inviato a Fluent Bit. Score: %.2f, Poisoned: %v\n", riskScore, isPoisoned)
}

// =====================================================================
// MAIN (Il punto di ingresso dell'applicazione)
// =====================================================================
func main() {
	log.Println("Inizializzazione Reverse Proxy WAAP...")

	// 1. Instanziamo i nostri moduli "finti"
	mockAI := &MockAI{}
	mockInj := &MockInjector{}
	mockRouter := &MockRouter{}
	mockTel := &MockTelemetry{}

	// 2. Creiamo il VERO Security Interceptor, iniettandogli i mock
	vigile := interceptor.NewSecurityInterceptor(mockAI, mockInj, mockRouter, mockTel)

	// 3. Passiamo il vigile al Listener che hai già scritto in precedenza
	srv := listener.NewServer(":8080", vigile)

	// 4. Prepariamo il canale per il Graceful Shutdown
	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	// 5. Avviamo il server in background
	go func() {
		if err := srv.Start(); err != nil {
			log.Fatalf("Errore critico del server: %v", err)
		}
	}()

	// 6. Restiamo in attesa del segnale di stop (CTRL+C)
	<-stopChan
	log.Println("\nSegnale ricevuto. Inizio Graceful Shutdown...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Stop(ctx); err != nil {
		log.Fatalf("Errore durante lo shutdown: %v", err)
	}

	log.Println("Server spento correttamente.")
}
