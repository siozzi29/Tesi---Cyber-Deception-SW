package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"cyber-deception-waap/pkg/injector"
	"cyber-deception-waap/pkg/interceptor"
	"cyber-deception-waap/pkg/listener"
	"cyber-deception-waap/pkg/router"
)

// =====================================================================
// MOCK DEI SOTTOSISTEMI (Livello 3 - Modello C4)
// Usiamo queste struct finte solo per i moduli non ancora implementati
// =====================================================================

type MockAI struct{}

func (m *MockAI) GetRiskScore(r *http.Request) (float64, error) {
	log.Println("[MOCK AI] Simulazione inferenza... Risk Score calcolato: 0.1 (Sano)")
	return 0.1, nil
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

	// 1. Router reale: fail-fast se manca la configurazione del backend
	backendURL := os.Getenv("BACKEND_URL")
	if backendURL == "" {
		panic("BACKEND_URL non impostata: il proxy non ha nulla a cui inoltrare il traffico")
	}

	realRouter, err := router.NewLegitTrafficRouter(backendURL)
	if err != nil {
		panic(fmt.Sprintf("BACKEND_URL non valida: %v", err))
	}

	// 2. Injector reale: genera honeytoken dinamici con TTL 30 minuti.
	// Close() va chiamato nello shutdown ordinato, non con un defer qui in
	// cima, altrimenti il goroutine di cleanup resta vivo fino alla fine
	// naturale di main() invece che nel punto giusto dello spegnimento.
	realInjector := injector.NewHoneyURLInjector(30 * time.Minute)

	// 3. Moduli ancora mock, in attesa di implementazione (IA e Telemetry)
	mockAI := &MockAI{}
	mockTel := &MockTelemetry{}

	// 4. Creiamo il VERO Security Interceptor, iniettandogli i moduli reali
	//    disponibili (router, injector) più i mock ancora da sostituire
	vigile := interceptor.NewSecurityInterceptor(mockAI, realInjector, realRouter, mockTel)

	// 5. Passiamo il vigile al Listener che hai già scritto in precedenza
	srv := listener.NewServer(":8080", vigile)

	// 6. Prepariamo il canale per il Graceful Shutdown
	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	// 7. Avviamo il server in background
	go func() {
		if err := srv.Start(); err != nil {
			log.Fatalf("Errore critico del server: %v", err)
		}
	}()

	// 8. Restiamo in attesa del segnale di stop (CTRL+C)
	<-stopChan
	log.Println("\nSegnale ricevuto. Inizio Graceful Shutdown...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Stop(ctx); err != nil {
		log.Fatalf("Errore durante lo shutdown: %v", err)
	}

	// 9. Fermiamo il goroutine di cleanup dell'injector solo DOPO che il
	// listener ha smesso di accettare traffico, per non rischiare di
	// spegnerlo mentre una richiesta è ancora in volo.
	realInjector.Close()

	log.Println("Server spento correttamente.")
}
