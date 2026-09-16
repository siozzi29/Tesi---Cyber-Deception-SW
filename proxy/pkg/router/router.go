package router

import (
	"bytes"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
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

	// Riscriviamo i link assoluti generati da WordPress e l'header Location per prevenire il blocco Mixed Content (HTTP su HTTPS).
	proxy.ModifyResponse = func(resp *http.Response) error {
		reqHost := resp.Request.Host // es. waap-proxy-175735032844.europe-west1.run.app

		// Riconosciamo se la richiesta originale dal browser è HTTPS (Cloud Run, apuliasoft.com o TLS diretto)
		isHTTPS := resp.Request.TLS != nil ||
			strings.EqualFold(resp.Request.Header.Get("X-Forwarded-Proto"), "https") ||
			strings.Contains(reqHost, "run.app") ||
			strings.Contains(reqHost, "apuliasoft.com")

		scheme := "http://"
		if isHTTPS {
			scheme = "https://"
		}

		targetHostname := target.Hostname()

		if loc := resp.Header.Get("Location"); loc != "" {
			newLoc := loc
			if isHTTPS {
				newLoc = strings.ReplaceAll(newLoc, "http://"+target.Host+":8080", scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://"+target.Host, scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://"+targetHostname+":8080", scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://"+targetHostname, scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://"+reqHost, scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://localhost:8080", scheme+reqHost)
				newLoc = strings.ReplaceAll(newLoc, "http://localhost", scheme+reqHost)
			} else {
				newLoc = strings.ReplaceAll(newLoc, target.Host+":8080", reqHost)
				newLoc = strings.ReplaceAll(newLoc, target.Host, reqHost)
				newLoc = strings.ReplaceAll(newLoc, targetHostname, reqHost)
			}
			resp.Header.Set("Location", newLoc)
		}

		contentType := resp.Header.Get("Content-Type")
		if strings.Contains(contentType, "text/") || strings.Contains(contentType, "application/json") || strings.Contains(contentType, "application/javascript") || strings.Contains(contentType, "application/xml") || strings.Contains(contentType, "xml") {
			bodyBytes, err := io.ReadAll(resp.Body)
			if err == nil {
				resp.Body.Close()

				var newBody []byte
				if isHTTPS {
					// Sostituiamo tutti i link assoluti HTTP verso il backend, l'host o vecchi riferimenti localhost con HTTPS
					b := bytes.ReplaceAll(bodyBytes, []byte("http://"+target.Host+":8080"), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://"+target.Host), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://"+targetHostname+":8080"), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://"+targetHostname), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://"+reqHost), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://localhost:8080"), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("http://localhost"), []byte(scheme+reqHost))
					b = bytes.ReplaceAll(b, []byte("//"+target.Host), []byte("//"+reqHost))
					b = bytes.ReplaceAll(b, []byte("//"+targetHostname), []byte("//"+reqHost))
					b = bytes.ReplaceAll(b, []byte(target.Host), []byte(reqHost))
					b = bytes.ReplaceAll(b, []byte(targetHostname), []byte(reqHost))
					newBody = b
				} else {
					b := bytes.ReplaceAll(bodyBytes, []byte(target.Host+":8080"), []byte(reqHost))
					b = bytes.ReplaceAll(b, []byte(target.Host), []byte(reqHost))
					b = bytes.ReplaceAll(b, []byte(targetHostname), []byte(reqHost))
					newBody = b
				}

				resp.Body = io.NopCloser(bytes.NewBuffer(newBody))
				// BUG FIX: usare Del() invece di Set("") per evitare header HTTP non validi!
				resp.Header.Del("Content-Length")
				resp.ContentLength = int64(len(newBody))
			}
		}
		return nil
	}

	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Header.Set("Accept-Encoding", "identity") // Chiede il testo in chiaro per la riscrittura

		clientIP, _, err := net.SplitHostPort(req.RemoteAddr)
		if err == nil {
			if req.Header.Get("X-Real-IP") == "" {
				req.Header.Set("X-Real-IP", clientIP)
			}
		}

		// Header inoltrati a WordPress affinché sappia che è dietro un reverse proxy HTTPS
		if req.Header.Get("X-Forwarded-Host") == "" {
			req.Header.Set("X-Forwarded-Host", req.Host)
		}
		if req.Header.Get("X-Forwarded-Proto") == "" {
			if req.TLS != nil || strings.Contains(req.Host, "run.app") || strings.Contains(req.Host, "apuliasoft.com") {
				req.Header.Set("X-Forwarded-Proto", "https")
			} else {
				req.Header.Set("X-Forwarded-Proto", "http")
			}
		}
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
