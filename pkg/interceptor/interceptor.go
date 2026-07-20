package interceptor

import (
	"log"
	"net/http"
)

// ============================================================================
// INTERFACCE DEI SOTTOSISTEMI (Livello 3 - Modello C4)
// ============================================================================

type AIClient interface {
	GetRiskScore(r *http.Request) (float64, error)
}

type URLInjector interface {
	IsHoneyURL(path string) bool
	Inject(body []byte) []byte
}

type Router interface {
	Forward(w http.ResponseWriter, r *http.Request)
	TarpitAndTrap(w http.ResponseWriter, r *http.Request)
}

type Telemetry interface {
	LogAsync(r *http.Request, riskScore float64, isPoisoned bool)
}

// ============================================================================
// SECURITY INTERCEPTOR (Il Vigile Urbano)
// ============================================================================

// DefaultRiskThreshold è usata solo se non viene passato un valore esplicito
// a NewSecurityInterceptor. ATTENZIONE: deve combaciare con la soglia
// "paranoica" calcolata in fase di training (ai-service/models/risk_threshold.joblib,
// attualmente 0.7134 dopo il tuning degli iperparametri per portare il recall
// dal 9.2% al 12.3% a parità di FPR 1%). Se riallenate il modello e la soglia
// cambia, aggiornate questo valore o passatelo esplicitamente via env var.
const DefaultRiskThreshold = 0.7134

type SecurityInterceptor struct {
	ai            AIClient
	injector      URLInjector
	router        Router
	telemetry     Telemetry
	riskThreshold float64
}

// NewSecurityInterceptor inietta le dipendenze. Se riskThreshold <= 0, usa
// DefaultRiskThreshold.
func NewSecurityInterceptor(ai AIClient, inj URLInjector, r Router, t Telemetry, riskThreshold float64) *SecurityInterceptor {
	if riskThreshold <= 0 {
		riskThreshold = DefaultRiskThreshold
	}
	return &SecurityInterceptor{
		ai:            ai,
		injector:      inj,
		router:        r,
		telemetry:     t,
		riskThreshold: riskThreshold,
	}
}

func (i *SecurityInterceptor) serveWithInjection(w http.ResponseWriter, r *http.Request, handler func(http.ResponseWriter, *http.Request)) {
	if i.injector == nil {
		handler(w, r)
		return
	}

	iw := newInjectingResponseWriter(w, i.injector)
	defer iw.finalize()
	handler(iw, r)
}

func (i *SecurityInterceptor) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// 1. Controllo Deterministico (Cyber Deception)
	if i.injector != nil && i.injector.IsHoneyURL(r.URL.Path) {
		log.Printf("[!] Attacco rilevato (Honey-URL): %s", r.URL.Path)
		i.telemetry.LogAsync(r, 1.0, true)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.TarpitAndTrap(writer, req)
		})
		return
	}

	// 2. Analisi Comportamentale (AI Inference) - Fail-Open su errore/timeout
	score, err := i.ai.GetRiskScore(r)
	if err != nil {
		log.Printf("[!] Errore IA, fail-open: %v", err)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.Forward(writer, req)
		})
		return
	}

	// 3. Routing Basato su Soglia (paranoica, FPR<=1% calcolata in training)
	if score > i.riskThreshold {
		log.Printf("[!] Anomalia rilevata (IA Score %.4f > soglia %.4f): %s", score, i.riskThreshold, r.URL.Path)
		i.telemetry.LogAsync(r, score, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.TarpitAndTrap(writer, req)
		})
	} else {
		i.telemetry.LogAsync(r, score, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.Forward(writer, req)
		})
	}
}
