package aiclient

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func stringsReader(s string) *strings.Reader { return strings.NewReader(s) }

func TestGetRiskScoreSuccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"risk_score": 0.42, "is_anomalous": false, "threshold": 0.8}`))
	}))
	defer server.Close()

	client := NewHTTPAIClient(server.URL, 100*time.Millisecond)
	req := httptest.NewRequest(http.MethodGet, "/home", nil)

	score, err := client.GetRiskScore(req)
	if err != nil {
		t.Fatalf("errore inatteso: %v", err)
	}
	if score != 0.42 {
		t.Fatalf("score atteso 0.42, ottenuto %v", score)
	}
}

func TestGetRiskScoreTimeoutReturnsError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(50 * time.Millisecond) // più lento del timeout del client
		w.Write([]byte(`{"risk_score": 0.1}`))
	}))
	defer server.Close()

	client := NewHTTPAIClient(server.URL, 5*time.Millisecond)
	req := httptest.NewRequest(http.MethodGet, "/home", nil)

	_, err := client.GetRiskScore(req)
	if err == nil {
		t.Fatal("atteso un errore di timeout, nessun errore ricevuto")
	}
}

func TestGetRiskScoreRestoresRequestBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"risk_score": 0}`))
	}))
	defer server.Close()

	client := NewHTTPAIClient(server.URL, 100*time.Millisecond)
	req := httptest.NewRequest(http.MethodPost, "/login", stringsReader("user=admin"))

	client.GetRiskScore(req)

	// Il body deve essere ancora leggibile dopo la chiamata (per il forward successivo)
	buf := make([]byte, 20)
	n, _ := req.Body.Read(buf)
	if string(buf[:n]) != "user=admin" {
		t.Fatalf("body non ripristinato correttamente, letto: %q", buf[:n])
	}
}
