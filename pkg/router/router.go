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
	// Range volutamente ampio e non deterministico per non essere fingerprintabile
	// da bot che misurano la varianza dei tempi di risposta.
	tarpitByteMinDelay = 80 * time.Millisecond
	tarpitByteMaxDelay = 250 * time.Millisecond

	// Rete di sicurezza: se per qualche motivo la cancellazione del context
	// non si propaga (es. proxy intermedi che bufferizzano), non vogliamo
	// tenere impegnata una goroutine e un file descriptor all'infinito.
	tarpitHardCap = 10 * time.Minute

	// Timeout stringenti sul Transport verso il backend reale: se il backend
	// è lento o giù, vogliamo fallire velocemente, non impilare richieste.
	dialTimeout           = 500 * time.Millisecond
	responseHeaderTimeout = 2 * time.Second
)

// decoyPayload è il contenuto fittizio che viene "sgocciolato" all'attaccante.
// Sembra una pagina di amministrazione plausibile, così da tenerlo impegnato
// a parsare/aspettare invece di fargli capire subito che è finito in trappola.
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
// backendURL DEVE essere già validato a monte (fail-fast in main.go se assente).
func NewLegitTrafficRouter(backendURL string) (*LegitTrafficRouter, error) {
	target, err := url.Parse(backendURL)
	if err != nil {
		return nil, err
	}

	proxy := httputil.NewSingleHostReverseProxy(target)

	// Transport con timeout aggressivi: niente code, niente attese infinite.
	proxy.Transport = &http.Transport{
		DialContext: (&net.Dialer{
			Timeout: dialTimeout,
		}).DialContext,
		ResponseHeaderTimeout: responseHeaderTimeout,
		// Manteniamo le connessioni keep-alive per non pagare l'handshake
		// TCP/TLS ad ogni richiesta verso il backend reale.
		MaxIdleConnsPerHost: 100,
	}

	// ErrorHandler: se il backend è giù, 502 secco e via. Nessun retry qui:
	// i retry sono responsabilità del client o dell'orchestratore (K8s),
	// mai del reverse proxy, per evitare thundering herd sulla RAM.
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		log.Printf("[ROUTER] Backend irraggiungibile per %s: %v", r.URL.Path, err)
		w.WriteHeader(http.StatusBadGateway)
	}

	return &LegitTrafficRouter{proxy: proxy}, nil
}

// Forward inoltra la richiesta in modo trasparente verso l'infrastruttura reale.
// Overhead minimo: nessuna elaborazione aggiuntiva, il lavoro pesante lo fa
// httputil.ReverseProxy che è ottimizzato dalla stdlib.
func (rt *LegitTrafficRouter) Forward(w http.ResponseWriter, r *http.Request) {
	rt.proxy.ServeHTTP(w, r)
}

// TarpitAndTrap intrappola l'attaccante scrivendo la risposta un byte alla
// volta, con delay randomizzato. Obiettivo: massimizzare il tempo/risorse
// che l'attaccante spende sulla connessione, senza fargli capire se è un
// tarpit o un backend semplicemente lento.
func (rt *LegitTrafficRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		// Fallback difensivo: se il ResponseWriter non supporta il flush
		// (caso raro, es. certi middleware di test), non possiamo fare
		// streaming a goccia. Rispondiamo comunque in modo da non lasciare
		// la connessione appesa senza risposta.
		log.Printf("[TARPIT] ResponseWriter non flushable, fallback risposta immediata: %s", r.URL.Path)
		w.WriteHeader(http.StatusOK)
		w.Write(decoyPayload)
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)

	// Cap di sicurezza sopra al context della richiesta: qualunque cosa
	// succeda, la goroutine muore entro tarpitHardCap.
	ctx, cancel := context.WithTimeout(r.Context(), tarpitHardCap)
	defer cancel()

	log.Printf("[TARPIT] Attaccante intrappolato, avvio drenaggio a goccia: %s", r.URL.Path)

	i := 0
	for {
		select {
		case <-ctx.Done():
			// L'attaccante ha chiuso la connessione, o abbiamo raggiunto
			// l'hard cap. In entrambi i casi: usciamo, niente leak.
			log.Printf("[TARPIT] Connessione terminata (%v): %s", ctx.Err(), r.URL.Path)
			return
		case <-time.After(randomTarpitDelay()):
			b := decoyPayload[i%len(decoyPayload)]
			if _, err := w.Write([]byte{b}); err != nil {
				// Client disconnesso a metà scrittura: usciamo silenziosamente.
				return
			}
			flusher.Flush()
			i++
		}
	}
}

// randomTarpitDelay genera un delay non deterministico tra i byte, per
// rendere il pattern di streaming meno fingerprintabile.
func randomTarpitDelay() time.Duration {
	span := tarpitByteMaxDelay - tarpitByteMinDelay
	return tarpitByteMinDelay + time.Duration(rand.Int63n(int64(span)))
}
