package router

import (
	"io"
	"net/http"
	"net/http/httptest"
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
