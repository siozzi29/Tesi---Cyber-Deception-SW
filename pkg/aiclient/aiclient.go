package aiclient

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// requestPayload rispecchia esattamente il modello Pydantic RequestPayload
// definito in ai-service/main.py. Se cambi uno dei due, aggiorna anche l'altro.
type requestPayload struct {
	URL         string `json:"url"`
	Method      string `json:"method"`
	Content     string `json:"content"`
	ContentType string `json:"content_type"`
}

// scoreResponse rispecchia il modello Pydantic ScoreResponse di main.py.
type scoreResponse struct {
	RiskScore   float64 `json:"risk_score"`
	IsAnomalous bool    `json:"is_anomalous"`
	Threshold   float64 `json:"threshold"`
}

// HTTPAIClient implementa l'interfaccia AIClient (definita in pkg/interceptor)
// chiamando il servizio FastAPI con il modello Isolation Forest.
type HTTPAIClient struct {
	endpoint   string // es. "http://localhost:8000/score"
	httpClient *http.Client
}

// NewHTTPAIClient costruisce il client con un timeout aggressivo: se FastAPI
// non risponde in tempo, l'interceptor deve poter fare fail-open senza
// bloccare il traffico legittimo (vincolo di latenza <2ms per il traffico
// sano — qui accettiamo un margine più ampio SOLO per l'analisi IA, ma mai
// abbastanza da impattare l'esperienza utente in caso di guasto).
func NewHTTPAIClient(endpoint string, timeout time.Duration) *HTTPAIClient {
	if timeout <= 0 {
		timeout = 150 * time.Millisecond
	}
	return &HTTPAIClient{
		endpoint: endpoint,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}

// GetRiskScore estrae i dati rilevanti dalla richiesta HTTP in ingresso e
// interroga FastAPI. Ritorna un errore se la chiamata fallisce o va in
// timeout: l'interceptor, ricevendo un errore, farà fail-open (Forward)
// invece di bloccare — coerente con la logica già in pkg/interceptor.
func (c *HTTPAIClient) GetRiskScore(r *http.Request) (float64, error) {
	// Corpo della richiesta: lo leggiamo e lo rimettiamo subito a posto
	// (r.Body è uno stream leggibile una volta sola) così il resto della
	// pipeline (es. il Router che poi farà il forward reale) possa
	// comunque leggerlo integro.
	var bodyBytes []byte
	if r.Body != nil {
		bodyBytes, _ = io.ReadAll(r.Body)
		r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
	}

	payload := requestPayload{
		URL:         r.URL.RequestURI(), // path + query, es. "/tienda1/x.jsp?id=1"
		Method:      r.Method,
		Content:     string(bodyBytes),
		ContentType: r.Header.Get("Content-Type"),
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return 0, fmt.Errorf("aiclient: errore serializzazione payload: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("aiclient: errore creazione richiesta: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		// Include i casi di timeout: il chiamante farà fail-open.
		return 0, fmt.Errorf("aiclient: errore chiamata a FastAPI: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(resp.Body)
		return 0, fmt.Errorf("aiclient: FastAPI ha risposto %d: %s", resp.StatusCode, string(respBody))
	}

	var result scoreResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("aiclient: errore decodifica risposta: %w", err)
	}

	return result.RiskScore, nil
}
