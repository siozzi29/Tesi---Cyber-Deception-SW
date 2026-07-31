package interceptor

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

// --- Mock dei 4 sottosistemi, per testare l'orchestrazione in isolamento ---

type mockAI struct {
	score float64
	err   error
}

func (m *mockAI) GetRiskScore(r *http.Request) (float64, error) { return m.score, m.err }

type mockInjector struct {
	isHoney bool
}

func (m *mockInjector) IsHoneyURL(path string) bool { return m.isHoney }
func (m *mockInjector) Inject(body []byte) []byte   { return body }

type mockRouter struct {
	forwarded bool
	trapped   bool
}

func (m *mockRouter) Forward(w http.ResponseWriter, r *http.Request) {
	m.forwarded = true
	w.WriteHeader(http.StatusOK)
}
func (m *mockRouter) TarpitAndTrap(w http.ResponseWriter, r *http.Request) {
	m.trapped = true
	w.WriteHeader(http.StatusOK)
}

type mockTelemetry struct{ calls int }

func (m *mockTelemetry) LogAsync(r *http.Request, riskScore float64, isPoisoned bool) { m.calls++ }

func newRequest(path string) *http.Request {
	req := httptest.NewRequest(http.MethodGet, path, nil)
	return req
}

func TestHoneyURLGoesToTarpit(t *testing.T) {
	router := &mockRouter{}
	si := NewSecurityInterceptor(&mockAI{score: 0}, &mockInjector{isHoney: true}, router, &mockTelemetry{}, 0.5)

	w := httptest.NewRecorder()
	si.ServeHTTP(w, newRequest("/sys/health-check-abc"))

	if !router.trapped || router.forwarded {
		t.Fatal("richiesta su honey-URL doveva finire in tarpit, non in forward")
	}
}

func TestHighRiskScoreGoesToTarpit(t *testing.T) {
	router := &mockRouter{}
	si := NewSecurityInterceptor(&mockAI{score: 0.9}, &mockInjector{}, router, &mockTelemetry{}, 0.5)

	w := httptest.NewRecorder()
	si.ServeHTTP(w, newRequest("/login"))

	if !router.trapped {
		t.Fatal("score sopra soglia doveva finire in tarpit")
	}
}

func TestLowRiskScoreGetsForwarded(t *testing.T) {
	router := &mockRouter{}
	si := NewSecurityInterceptor(&mockAI{score: 0.1}, &mockInjector{}, router, &mockTelemetry{}, 0.5)

	w := httptest.NewRecorder()
	si.ServeHTTP(w, newRequest("/home"))

	if !router.forwarded {
		t.Fatal("score sotto soglia doveva essere forwardato")
	}
}

func TestAIErrorFailsOpen(t *testing.T) {
	router := &mockRouter{}
	si := NewSecurityInterceptor(&mockAI{err: http.ErrHandlerTimeout}, &mockInjector{}, router, &mockTelemetry{}, 0.5)

	w := httptest.NewRecorder()
	si.ServeHTTP(w, newRequest("/home"))

	if !router.forwarded {
		t.Fatal("errore IA doveva fare fail-open (forward), non bloccare il traffico")
	}
}

func TestStatsIncrementCorrectly(t *testing.T) {
	router := &mockRouter{}
	si := NewSecurityInterceptor(&mockAI{score: 0.1}, &mockInjector{}, router, &mockTelemetry{}, 0.5)

	si.ServeHTTP(httptest.NewRecorder(), newRequest("/home"))
	stats, _ := si.Snapshot()

	if stats.TotalRequests != 1 || stats.Forwarded != 1 {
		t.Fatalf("stats inattese: %+v", stats)
	}
}
