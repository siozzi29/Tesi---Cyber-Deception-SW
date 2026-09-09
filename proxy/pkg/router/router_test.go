package router

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestForwardProxiesToBackend(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/home" {
			t.Errorf("path atteso /home, ricevuto %s", r.URL.Path)
		}
		w.Write([]byte("risposta dal backend WordPress"))
	}))
	defer backend.Close()

	lr, err := NewLegitRouter(backend.URL)
	if err != nil {
		t.Fatalf("errore creazione router: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/home", nil)
	w := httptest.NewRecorder()

	lr.Forward(w, req)

	resp := w.Result()
	body, _ := io.ReadAll(resp.Body)
	if string(body) != "risposta dal backend WordPress" {
		t.Fatalf("body inatteso: %q", body)
	}
}

func TestForwardBackendUnreachableReturns502(t *testing.T) {
	// Indirizzo che sicuramente non risponde: la ErrorHandler deve scattare.
	lr, err := NewLegitRouter("http://127.0.0.1:1")
	if err != nil {
		t.Fatalf("errore creazione router: %v", err)
	}

	req := httptest.NewRequest(http.MethodGet, "/home", nil)
	w := httptest.NewRecorder()

	lr.Forward(w, req)

	if w.Result().StatusCode != http.StatusBadGateway {
		t.Fatalf("status atteso 502, ottenuto %d", w.Result().StatusCode)
	}
}

func TestTarpitAndTrapRespondsAfterDelay(t *testing.T) {
	// Delay minuscolo solo per il test: il campo è nello stesso package,
	// quindi accessibile direttamente senza passare da NewLegitRouter.
	lr := &LegitRouter{tarpitDelay: 10 * time.Millisecond}

	req := httptest.NewRequest(http.MethodGet, "/sys/health-check-abc", nil)
	w := httptest.NewRecorder()

	start := time.Now()
	lr.TarpitAndTrap(w, req)
	elapsed := time.Since(start)

	if elapsed < 10*time.Millisecond {
		t.Fatalf("il tarpit doveva attendere almeno il delay configurato, atteso %v", elapsed)
	}

	resp := w.Result()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status atteso 200, ottenuto %d", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if len(body) == 0 {
		t.Fatal("il body della pagina civetta non deve essere vuoto")
	}
	if resp.Header.Get("Content-Type") != "text/html" {
		t.Fatalf("Content-Type atteso text/html, ottenuto %q", resp.Header.Get("Content-Type"))
	}
}

func TestTarpitAndTrapDoesNotBlockAboveConfiguredDelay(t *testing.T) {
	// Verifica che il delay sia rispettato ma non ecceduto in modo abnorme
	// (utile per accorgersi se qualcuno reintroduce un valore hardcoded).
	lr := &LegitRouter{tarpitDelay: 20 * time.Millisecond}

	req := httptest.NewRequest(http.MethodGet, "/x", nil)
	w := httptest.NewRecorder()

	start := time.Now()
	lr.TarpitAndTrap(w, req)
	elapsed := time.Since(start)

	if elapsed > 200*time.Millisecond {
		t.Fatalf("il tarpit ha impiegato %v, molto più del delay configurato (20ms) — hardcoded residuo?", elapsed)
	}
}

func TestModifyResponseRewritesHTTPToHTTPSForCloudRun(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Header().Set("Location", "http://10.132.0.2:80/wp-admin/")
		w.Write([]byte(`<html><head><link rel="stylesheet" href="http://10.132.0.2/wp-content/themes/twentytwentyfive/style.css"><link rel="stylesheet" href="http://localhost:8080/style.css"></head><body><img src="http://10.132.0.2:80/image.png"><a href="http://waap-proxy.run.app/page">Link</a></body></html>`))
	}))
	defer backend.Close()

	lr, err := NewLegitRouter("http://10.132.0.2:80")
	if err != nil {
		t.Fatalf("errore creazione router: %v", err)
	}
	lr.proxy.Transport = &http.Transport{
		// Indirizziamo le chiamate di test al server backend finto
		DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
			return net.Dial("tcp", backend.Listener.Addr().String())
		},
	}

	req := httptest.NewRequest(http.MethodGet, "/home", nil)
	req.Host = "waap-proxy.run.app"
	req.Header.Set("X-Forwarded-Proto", "https")
	w := httptest.NewRecorder()

	lr.Forward(w, req)

	resp := w.Result()
	body, _ := io.ReadAll(resp.Body)
	bodyStr := string(body)

	// Location deve essere HTTPS e puntare all'host pubblico
	if loc := resp.Header.Get("Location"); loc != "https://waap-proxy.run.app/wp-admin/" {
		t.Fatalf("Location atteso 'https://waap-proxy.run.app/wp-admin/', ottenuto %q", loc)
	}

	// Nessun link deve iniziare per http://
	if strings.Contains(bodyStr, "http://") {
		t.Fatalf("trovati link http:// non riscritti nel body: %s", bodyStr)
	}

	if !strings.Contains(bodyStr, `href="https://waap-proxy.run.app/wp-content/themes/twentytwentyfive/style.css"`) {
		t.Fatalf("foglio di stile non riscritto correttamente in HTTPS: %s", bodyStr)
	}

	if !strings.Contains(bodyStr, `src="https://waap-proxy.run.app/image.png"`) {
		t.Fatalf("immagine non riscritta correttamente in HTTPS: %s", bodyStr)
	}
}
