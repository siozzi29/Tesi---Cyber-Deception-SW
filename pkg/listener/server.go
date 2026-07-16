package listener

import (
	"context"
	"log"
	"net/http"
	"time"
)

// InterceptorHandler definisce il contratto che il Security Interceptor deve rispettare
// per ricevere il traffico dal Listener.
type InterceptorHandler interface {
	http.Handler
}

// Server è la nostra struct per l'HTTP Listener.
// Incapsula il server HTTP standard di Go.
type Server struct {
	httpServer *http.Server
}

// NewServer inizializza l'HTTP Listener con parametri di sicurezza stringenti.
func NewServer(addr string, interceptor InterceptorHandler) *Server {
	return &Server{
		httpServer: &http.Server{
			Addr:    addr,
			Handler: interceptor, // Tutto il traffico passa al Security Interceptor

			// SISTEMI DI SICUREZZA ANTI-DOS (Non facciamo crashare l'azienda)
			ReadTimeout:  5 * time.Second,  // Tempo max per leggere l'intera request
			WriteTimeout: 10 * time.Second, // Tempo max per scrivere la response
			IdleTimeout:  15 * time.Second, // Tempo max per mantenere vive le connessioni Keep-Alive
		},
	}
}

// Start avvia il server in ascolto in modo bloccante.
func (s *Server) Start() error {
	log.Printf("HTTP Listener avviato con successo. In ascolto su %s", s.httpServer.Addr)
	// ListenAndServe bloccherà la goroutine principale finché non si verifica un errore o uno shutdown
	if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// Stop esegue un "graceful shutdown" (spegnimento morbido) del server.
// Dà il tempo (es. 5 secondi) alle richieste sane in volo di essere completate.
func (s *Server) Stop(ctx context.Context) error {
	log.Println("Avvio spegnimento dell'HTTP Listener (Graceful Shutdown)...")
	return s.httpServer.Shutdown(ctx)
}
