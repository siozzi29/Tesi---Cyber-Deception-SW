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
//
// Usa httputil.ReverseProxy della standard library: nessuna dipendenza
// esterna, overhead minimo, perfetto per il vincolo <2ms di latenza.
type LegitRouter struct {
	proxy *httputil.ReverseProxy
}

// NewLegitRouter costruisce il router puntando all'IP INTERNO della VM
// WordPress (non l'IP pubblico: il traffico deve restare dentro la VPC).
//
// Esempio: backendAddr = "http://10.128.0.4:80"
func NewLegitRouter(backendAddr string) (*LegitRouter, error) {
	target, err := url.Parse(backendAddr)
	if err != nil {
		return nil, err
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	// Transport custom: timeout aggressivi per non impattare la latenza
	// e per non lasciare connessioni appese in caso il backend sia lento/giù.
	proxy.Transport = &http.Transport{
		DialContext: (&net.Dialer{
			Timeout:   2 * time.Second, // tempo max per stabilire la connessione TCP
			KeepAlive: 30 * time.Second,
		}).DialContext,
		TLSHandshakeTimeout:   2 * time.Second,
		ResponseHeaderTimeout: 5 * time.Second, // tempo max di attesa della risposta di WordPress
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   100, // riuso connessioni: evita l'overhead di aprirne di nuove ad ogni richiesta
		IdleConnTimeout:       90 * time.Second,
	}

	// Se WordPress risponde con errore di rete (down, timeout...) non vogliamo
	// che il proxy crashi: logghiamo e rispondiamo 502, fail-safe.
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("[ROUTER] Errore forwarding verso il backend: %v", err)
		w.WriteHeader(http.StatusBadGateway)
	}

	return &LegitRouter{proxy: proxy}, nil
}

// Forward inoltra la richiesta sana verso WordPress in modo trasparente.
func (lr *LegitRouter) Forward(w http.ResponseWriter, r *http.Request) {
	lr.proxy.ServeHTTP(w, r)
}

// TarpitAndTrap rallenta deliberatamente la risposta verso un attaccante
// sospetto (tarpitting) prima di restituire una pagina civetta, per
// massimizzare il tempo che l'attaccante "spreca" sul nostro sistema di
// deception invece che sull'infrastruttura reale.
func (lr *LegitRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	// Ritardo deliberato: tiene impegnato lo scanner/bot dell'attaccante.
	// Va tarato in produzione (troppo alto = rischio di esaurire i worker
	// del server con connessioni lente aperte, occhio al DoS accidentale).
	time.Sleep(3 * time.Second)

	w.Header().Set("Content-Type", "text/html")
	w.WriteHeader(http.StatusOK) // 200 per non insospettire l'attaccante
	w.Write([]byte(`<html><body><h1>Servizio momentaneamente non disponibile</h1></body></html>`))

	log.Printf("[TARPIT] Attaccante intrappolato: %s %s", r.Method, r.URL.Path)
}