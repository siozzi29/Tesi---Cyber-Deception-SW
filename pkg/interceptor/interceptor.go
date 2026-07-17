package interceptor

import (
	"log"
	"net/http"
)

// ============================================================================
// INTERFACCE DEI SOTTOSISTEMI (Livello 3 - Modello C4)
// ============================================================================

// AIClient gestisce le chiamate di rete verso l'IA in Python (FastAPI).
type AIClient interface {
	GetRiskScore(r *http.Request) (float64, error)
}

// URLInjector modifica lo stream del DOM iniettando esche invisibili.
type URLInjector interface {
	IsHoneyURL(path string) bool
	Inject(body []byte) []byte
}

// Router instrada il traffico: o inoltro trasparente o deviazione verso la Trappola.
type Router interface {
	Forward(w http.ResponseWriter, r *http.Request)
	TarpitAndTrap(w http.ResponseWriter, r *http.Request)
}

// Telemetry spedisce asincronamente i log JSON a Fluent Bit.
type Telemetry interface {
	LogAsync(r *http.Request, riskScore float64, isPoisoned bool)
}

// ============================================================================
// SECURITY INTERCEPTOR (Il Vigile Urbano)
// ============================================================================

// SecurityInterceptor coordina i controlli e decide il routing.
type SecurityInterceptor struct {
	ai        AIClient
	injector  URLInjector
	router    Router
	telemetry Telemetry
}

// NewSecurityInterceptor inietta le dipendenze per non creare un monolite.
func NewSecurityInterceptor(ai AIClient, inj URLInjector, r Router, t Telemetry) *SecurityInterceptor {
	return &SecurityInterceptor{
		ai:        ai,
		injector:  inj,
		router:    r,
		telemetry: t,
	}
}

// ServeHTTP soddisfa l'interfaccia http.Handler richiesta dal nostro Listener.
// Qui dentro avverrà la vera magia del WAAP.
func (i *SecurityInterceptor) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// 1. Controllo Deterministico (Cyber Deception)
	if i.injector.IsHoneyURL(r.URL.Path) {
		log.Printf("[!] Attacco rilevato (Honey-URL): %s", r.URL.Path)
		// Marchiamo la sessione come avvelenata per la nostra Pipeline Anti-Poisoning
		i.telemetry.LogAsync(r, 1.0, true)
		i.router.TarpitAndTrap(w, r)
		return
	}

	// 2. Analisi Comportamentale (AI Inference)
	score, err := i.ai.GetRiskScore(r)
	if err != nil {
		log.Printf("[!] Errore IA, fail-open: %v", err)
		i.router.Forward(w, r)
		return
	}

	// 3. Routing Basato su Soglia
	if score > 0.8 { // Soglia di rischio: se > 0.8, sospettiamo fortemente
		log.Printf("[!] Anomalia rilevata (IA Score %.2f): %s", score, r.URL.Path)
		i.telemetry.LogAsync(r, score, false)
		i.router.TarpitAndTrap(w, r)
	} else {
		// Traffico Sano: instradiamo attraverso l'injecting response writer,
		// che inietta l'esca invisibile SOLO se la risposta è HTML, senza
		// aggiungere overhead alle risposte non-HTML (JSON, immagini, ecc.).
		i.telemetry.LogAsync(r, score, false)
		iw := newInjectingResponseWriter(w, i.injector)
		i.router.Forward(iw, r)
		iw.finalize()
	}
}
