package listener

import (
	"context"
	"cyber-deception-waap/pkg/interceptor"
	"log"
	"net/http"
	"time"
)

// InterceptorHandler definisce il contratto che il Security Interceptor deve rispettare
// per ricevere il traffico dal Listener.
type InterceptorHandler interface {
	http.Handler
}

// Server incapsula i due listener HTTP dell'applicazione:
//   - httpServer: il listener PUBBLICO (dietro il Load Balancer), serve SOLO
//     il traffico che passa dal SecurityInterceptor. Nessun'altra rotta.
//   - dashboardServer: listener SEPARATO e INTERNO (es. 127.0.0.1 o IP privato
//     della VPC), che espone /dashboard, /dashboard/stats, /dashboard/events.
//
// Il dashboard NON deve mai finire sullo stesso mux del traffico pubblico:
// espone telemetria di detection (score IA, honey-hit, path colpiti) e se
// il LB lo inoltra per sbaglio diventa un data leak enorme per un sistema
// di cyber deception. Va tenuto su una porta/interfaccia che il LB non tocca
// (e idealmente protetta anche a livello di firewall GCP).
type Server struct {
	httpServer      *http.Server
	dashboardServer *http.Server
}

// NewServer inizializza il Listener pubblico con parametri di sicurezza
// stringenti. Il mux pubblico serve ESCLUSIVAMENTE l'handler passato
// (il SecurityInterceptor): nessuna rotta di servizio, nessun dashboard.
func NewServer(addr string, handler InterceptorHandler) *Server {
	mux := http.NewServeMux()
	
	// Supporto Cloud Run: espone /dashboard anche sulla porta principale
	if si, ok := handler.(*interceptor.SecurityInterceptor); ok {
		mux.HandleFunc("/dashboard", si.DashboardHandler)
		mux.HandleFunc("/dashboard/", si.DashboardHandler)
	}
	mux.Handle("/", handler)

	return &Server{
		httpServer: &http.Server{
			Addr:    addr,
			Handler: mux,

			// SISTEMI DI SICUREZZA ANTI-DOS (Non facciamo crashare l'azienda)
			ReadHeaderTimeout: 3 * time.Second,  // anti slowloris: tempo max per ricevere gli HEADER
			ReadTimeout:       5 * time.Second,  // tempo max per leggere l'intera request (header + body)
			WriteTimeout:      10 * time.Second, // tempo max per scrivere la response
			IdleTimeout:       15 * time.Second, // tempo max per mantenere vive le connessioni Keep-Alive
		},
	}
}

// NewDashboardServer inizializza il Listener del dashboard su un indirizzo
// SEPARATO da quello pubblico (es. "127.0.0.1:9090" o l'IP interno della VM
// waap-proxy). Passare dashboardAddr == "" per disabilitarlo del tutto.
//
// Va chiamato con l'interceptor concreto (non l'interfaccia InterceptorHandler)
// perché ci serve il metodo DashboardHandler, specifico di *interceptor.SecurityInterceptor.
func NewDashboardServer(dashboardAddr string, si *interceptor.SecurityInterceptor) *Server {
	if dashboardAddr == "" || si == nil {
		return nil
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/dashboard", si.DashboardHandler)
	mux.HandleFunc("/dashboard/", si.DashboardHandler)

	return &Server{
		dashboardServer: &http.Server{
			Addr:    dashboardAddr,
			Handler: mux,

			ReadHeaderTimeout: 3 * time.Second,
			ReadTimeout:       5 * time.Second,
			WriteTimeout:      10 * time.Second,
			IdleTimeout:       15 * time.Second,
		},
	}
}

// Start avvia il server PUBBLICO in ascolto in modo bloccante.
func (s *Server) Start() error {
	if s.httpServer == nil {
		return nil
	}
	log.Printf("HTTP Listener (pubblico) avviato con successo. In ascolto su %s", s.httpServer.Addr)
	if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// StartDashboard avvia il server del DASHBOARD in ascolto in modo bloccante.
// Va lanciato in una goroutine separata dal main (come si fa già per Start()),
// così i due listener vivono indipendentemente.
func (s *Server) StartDashboard() error {
	if s.dashboardServer == nil {
		return nil
	}
	log.Printf("HTTP Listener (dashboard, interno) avviato con successo. In ascolto su %s", s.dashboardServer.Addr)
	if err := s.dashboardServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

// Stop esegue un "graceful shutdown" (spegnimento morbido) del server pubblico.
// Dà il tempo (es. 5 secondi) alle richieste sane in volo di essere completate.
func (s *Server) Stop(ctx context.Context) error {
	if s.httpServer == nil {
		return nil
	}
	log.Println("Avvio spegnimento dell'HTTP Listener pubblico (Graceful Shutdown)...")
	return s.httpServer.Shutdown(ctx)
}

// StopDashboard esegue lo shutdown del server dashboard, se attivo.
func (s *Server) StopDashboard(ctx context.Context) error {
	if s.dashboardServer == nil {
		return nil
	}
	log.Println("Avvio spegnimento dell'HTTP Listener dashboard (Graceful Shutdown)...")
	return s.dashboardServer.Shutdown(ctx)
}
