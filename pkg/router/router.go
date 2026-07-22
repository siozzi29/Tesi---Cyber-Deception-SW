package router

import (
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"
)

// LegitRouter instrada il traffico sano verso l'infrastruttura reale (WordPress
// su Compute Engine) e gestisce il tarpitting per il traffico sospetto.
type LegitRouter struct {
	proxy       *httputil.ReverseProxy
	tarpitDelay time.Duration
}

// NewLegitRouter costruisce il router puntando all'IP INTERNO della VM
// WordPress (non l'IP pubblico: il traffico deve restare dentro la VPC).
//
// Esempio: backendAddr = "http://10.132.0.2:80" (wordpress-1-vm)
func NewLegitRouter(backendAddr string) (*LegitRouter, error) {
	target, err := url.Parse(backendAddr)
	if err != nil {
		return nil, err
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	proxy.Transport = &http.Transport{
		DialContext: (&net.Dialer{
			Timeout:   2 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		TLSHandshakeTimeout:   2 * time.Second,
		ResponseHeaderTimeout: 5 * time.Second,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   100,
		IdleConnTimeout:       90 * time.Second,
	}

	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("[ROUTER] Errore forwarding verso il backend: %v", err)
		w.WriteHeader(http.StatusBadGateway)
	}

	return &LegitRouter{proxy: proxy, tarpitDelay: 3 * time.Second}, nil
}

// Forward inoltra la richiesta sana verso WordPress in modo trasparente.
func (lr *LegitRouter) Forward(w http.ResponseWriter, r *http.Request) {
	lr.proxy.ServeHTTP(w, r)
}

// TarpitAndTrap rallenta deliberatamente la risposta verso un attaccante
// sospetto prima di restituire una pagina civetta.
func (lr *LegitRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	time.Sleep(lr.tarpitDelay)

	w.Header().Set("Content-Type", "text/html")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`<html><body><h1>Servizio momentaneamente non disponibile</h1></body></html>`))

	log.Printf("[TARPIT] Attaccante intrappolato: %s %s", r.Method, r.URL.Path)
}
