package interceptor

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"sync"
	"time"
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

// SecurityEvent è l'unità d'informazione usata dal dashboard per mostrare
// gli ultimi eventi analizzati dal proxy.
type SecurityEvent struct {
	Timestamp   time.Time `json:"timestamp"`
	Path        string    `json:"path"`
	Method      string    `json:"method"`
	RiskScore   float64   `json:"risk_score"`
	IsHoney     bool      `json:"is_honey"`
	Routed      string    `json:"routed"`
	Body        string    `json:"body"`
	ContentType string    `json:"content_type"`
}

type SecurityStats struct {
	TotalRequests int `json:"total_requests"`
	Forwarded     int `json:"forwarded"`
	Trapped       int `json:"trapped"`
	HoneyHits     int `json:"honey_hits"`
	AIErrors      int `json:"ai_errors"`
}

// ============================================================================
// SECURITY INTERCEPTOR (Il Vigile Urbano)
// ============================================================================

// DefaultRiskThreshold è usata solo se non viene passato un valore esplicito
// a NewSecurityInterceptor. ATTENZIONE: deve combaciare con la soglia
// "paranoica" calcolata in fase di training (salvata tra i file in
// ai-service/models/, attualmente 0.5908 dopo il tuning degli iperparametri
// per portare il recall dal 9.2% al 12.3% a parità di FPR 1%). Se riallenate
// il modello e la soglia cambia, aggiornate questo valore o passatelo
// esplicitamente via env var RISK_THRESHOLD — verificate anche in quale
// file esatto la soglia viene persistita lato ai-service, per tenerlo
// allineato a questo commento.
const DefaultRiskThreshold = 0.5908

type SecurityInterceptor struct {
	ai            AIClient
	injector      URLInjector
	router        Router
	telemetry     Telemetry
	riskThreshold float64

	mu        sync.Mutex
	stats     SecurityStats
	events    []SecurityEvent
	maxEvents int
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
		maxEvents:     2000,
	}
}

// logTelemetry centralizza la chiamata al Telemetry, con nil-check: se il
// componente di telemetria non è stato iniettato (es. config parziale in
// test, o non ancora cablato in qualche ambiente), evitiamo un panic invece
// di propagarlo fino al client — coerente con lo spirito fail-safe del resto
// del proxy.
func (i *SecurityInterceptor) logTelemetry(r *http.Request, riskScore float64, isPoisoned bool) {
	if i.telemetry == nil {
		return
	}
	i.telemetry.LogAsync(r, riskScore, isPoisoned)
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

func (i *SecurityInterceptor) recordEvent(event SecurityEvent) {
	i.mu.Lock()
	defer i.mu.Unlock()

	i.stats.TotalRequests++
	if event.IsHoney {
		i.stats.HoneyHits++
	}
	if event.Routed == "forwarded" {
		i.stats.Forwarded++
	}
	if event.Routed == "trapped" {
		i.stats.Trapped++
	}
	if event.Routed == "ai_error" {
		i.stats.AIErrors++
	}

	if len(i.events) >= i.maxEvents {
		i.events = i.events[1:]
	}
	i.events = append(i.events, event)
}

func (i *SecurityInterceptor) Snapshot() (SecurityStats, []SecurityEvent) {
	i.mu.Lock()
	defer i.mu.Unlock()

	copiedStats := i.stats
	copiedEvents := append([]SecurityEvent(nil), i.events...)
	return copiedStats, copiedEvents
}

func (i *SecurityInterceptor) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// 0. Estrazione Identità (Auth-Bypass Check)
	isAuthenticated := false
	for _, cookie := range r.Cookies() {
		if len(cookie.Name) >= 20 && cookie.Name[:20] == "wordpress_logged_in_" {
			isAuthenticated = true
			break
		}
	}

	// 0.5 Cattura del Body e Content-Type per il Dashboard / Training
	// Leggiamo fino a 1MB per non esaurire la memoria, poi rimpiazziamo r.Body.
	var reqBody string
	if r.Body != nil {
		raw, err := io.ReadAll(io.LimitReader(r.Body, 1<<20)) // 1MB max
		if err == nil {
			reqBody = string(raw)
			r.Body = io.NopCloser(bytes.NewBuffer(raw))
		}
	}
	reqContentType := r.Header.Get("Content-Type")

	// 1. Controllo Deterministico (Cyber Deception)
	if i.injector != nil && i.injector.IsHoneyURL(r.URL.Path) {
		log.Printf("[!] Attacco rilevato (Honey-URL): %s", r.URL.Path)
		i.logTelemetry(r, 1.0, true)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.TarpitAndTrap(writer, req)
		})
		i.recordEvent(SecurityEvent{
			Timestamp:   time.Now(),
			Path:        r.URL.RequestURI(),
			Method:      r.Method,
			RiskScore:   1.0,
			IsHoney:     true,
			Routed:      "trapped",
			Body:        reqBody,
			ContentType: reqContentType,
		})
		return
	}

	// 1.5 Whitelist per utenti autenticati (Bypass AI)
	if isAuthenticated {
		log.Printf("[!] Bypass IA per utente autenticato: %s", r.URL.Path)
		i.logTelemetry(r, 0.0, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.Forward(writer, req)
		})
		i.recordEvent(SecurityEvent{
			Timestamp:   time.Now(),
			Path:        r.URL.RequestURI(),
			Method:      r.Method,
			RiskScore:   0.0,
			IsHoney:     false,
			Routed:      "forwarded",
			Body:        reqBody,
			ContentType: reqContentType,
		})
		return
	}

	// 2. Analisi Comportamentale (AI Inference) - Fail-Open su errore/timeout
	score, err := i.ai.GetRiskScore(r)
	if err != nil {
		log.Printf("[!] Errore IA, fail-open: %v", err)
		// FIX: prima questo ramo non chiamava LogAsync — i fallimenti/timeout
		// dell'AI service (es. sotto attacco o sotto carico) sparivano dalla
		// telemetria "vera" e restavano visibili solo nelle stats locali del
		// dashboard. RiskScore -1 per distinguere in telemetria un "errore IA"
		// da uno score reale 0 (traffico giudicato sicuro).
		i.logTelemetry(r, -1, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.Forward(writer, req)
		})
		i.recordEvent(SecurityEvent{
			Timestamp:   time.Now(),
			Path:        r.URL.RequestURI(),
			Method:      r.Method,
			RiskScore:   -1,
			IsHoney:     false,
			Routed:      "ai_error",
			Body:        reqBody,
			ContentType: reqContentType,
		})
		return
	}

	// 3. Routing Basato su Soglia (paranoica, FPR<=1% calcolata in training)
	if score > i.riskThreshold {
		log.Printf("[!] Anomalia rilevata (IA Score %.4f > soglia %.4f): %s", score, i.riskThreshold, r.URL.Path)
		i.logTelemetry(r, score, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.TarpitAndTrap(writer, req)
		})
		i.recordEvent(SecurityEvent{
			Timestamp:   time.Now(),
			Path:        r.URL.RequestURI(),
			Method:      r.Method,
			RiskScore:   score,
			IsHoney:     false,
			Routed:      "trapped",
			Body:        reqBody,
			ContentType: reqContentType,
		})
	} else {
		i.logTelemetry(r, score, false)
		i.serveWithInjection(w, r, func(writer http.ResponseWriter, req *http.Request) {
			i.router.Forward(writer, req)
		})
		i.recordEvent(SecurityEvent{
			Timestamp:   time.Now(),
			Path:        r.URL.RequestURI(),
			Method:      r.Method,
			RiskScore:   score,
			IsHoney:     false,
			Routed:      "forwarded",
			Body:        reqBody,
			ContentType: reqContentType,
		})
	}
}
