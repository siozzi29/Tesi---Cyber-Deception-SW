package router

import (
	"context"
	"log"
	"math/rand"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

// ============================================================================
// LEGIT TRAFFIC ROUTER (Livello 3 - Modello C4)
// Inoltro trasparente < 2ms + Tarpit "a goccia" per attaccanti intrappolati.
// ============================================================================

const (
	// Intervallo randomizzato tra un byte e l'altro nel tarpit.
	tarpitByteMinDelay = 80 * time.Millisecond
	tarpitByteMaxDelay = 250 * time.Millisecond

	// Rete di sicurezza: se la cancellazione del context non si propaga,
	// non vogliamo tenere impegnata una goroutine all'infinito. NOTA: questo
	// cap funziona SOLO perché in TarpitAndTrap estendiamo esplicitamente il
	// write deadline della risposta via http.ResponseController — altrimenti
	// il WriteTimeout globale del server (10s, vedi pkg/listener) tronca la
	// connessione ben prima di arrivare qui.
	tarpitHardCap = 10 * time.Minute

	// Timeout stringenti sul Transport verso il backend reale.
	dialTimeout           = 500 * time.Millisecond
	responseHeaderTimeout = 2 * time.Second
)

var decoyPayload = []byte(`<!DOCTYPE html>
<html><head><title>Admin Panel</title></head>
<body><h1>Loading dashboard...</h1>
<div id="data">Please wait, retrieving records from database...</div>
</body></html>`)

// LegitTrafficRouter implementa l'interfaccia interceptor.Router.
type LegitTrafficRouter struct {
	proxy *httputil.ReverseProxy
}

// NewLegitTrafficRouter costruisce il router puntando al backend reale.
func NewLegitTrafficRouter(backendURL string) (*LegitTrafficRouter, error) {
	target, err := url.Parse(backendURL)
	if err != nil {
		return nil, err
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	proxy.Transport = &http.Transport{
		DialContext: (&net.Dialer{
			Timeout: dialTimeout,
		}).DialContext,
		ResponseHeaderTimeout: responseHeaderTimeout,
		MaxIdleConnsPerHost:   100,
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("[ROUTER] Backend irraggiungibile per %s: %v", r.URL.Path, err)
		w.WriteHeader(http.StatusBadGateway)
	}

	return &LegitTrafficRouter{proxy: proxy}, nil
}

// Forward inoltra la richiesta in modo trasparente verso l'infrastruttura reale.
func (rt *LegitTrafficRouter) Forward(w http.ResponseWriter, r *http.Request) {
	rt.proxy.ServeHTTP(w, r)
}

// TarpitAndTrap intrappola l'attaccante scrivendo la risposta un byte alla
// volta, con delay randomizzato.
func (rt *LegitTrafficRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		log.Printf("[TARPIT] ResponseWriter non flushable, fallback risposta immediata: %s", r.URL.Path)
		w.WriteHeader(http.StatusOK)
		w.Write(decoyPayload)
		return
	}

	// CRITICO: il WriteTimeout globale del server (pkg/listener, 10s) è
	// pensato per proteggere il traffico normale da scritture anomale, ma
	// ammazzerebbe anche il nostro tarpit, che è LENTO DI PROPOSITO.
	// Estendiamo il deadline SOLO per questa risposta, lasciando lo scudo
	// globale intatto per tutto il resto del traffico.
	rc := http.NewResponseController(w)
	if err := rc.SetWriteDeadline(time.Now().Add(tarpitHardCap)); err != nil {
		// Se il ResponseWriter non supporta deadline personalizzati (raro,
		// dipende dall'implementazione sottostante), logghiamo e proseguiamo:
		// il tarpit funzionerà comunque, ma potrebbe essere tagliato dal
		// WriteTimeout globale del server prima del nostro hard cap.
		log.Printf("[TARPIT] Impossibile estendere il write deadline (%v): il tarpit potrebbe essere interrotto anzitempo dal timeout globale", err)
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)

	ctx, cancel := context.WithTimeout(r.Context(), tarpitHardCap)
	defer cancel()

	log.Printf("[TARPIT] Attaccante intrappolato, avvio drenaggio a goccia: %s", r.URL.Path)

	i := 0
	for {
		select {
		case <-ctx.Done():
			log.Printf("[TARPIT] Connessione terminata (%v): %s", ctx.Err(), r.URL.Path)
			return
		case <-time.After(randomTarpitDelay()):
			b := decoyPayload[i%len(decoyPayload)]
			if _, err := w.Write([]byte{b}); err != nil {
				return
			}
			flusher.Flush()
			i++
		}
	}
}

func randomTarpitDelay() time.Duration {
	span := tarpitByteMaxDelay - tarpitByteMinDelay
	return tarpitByteMinDelay + time.Duration(rand.Int63n(int64(span)))
}
