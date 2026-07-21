package aiclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// maxRequestBodyBytes è il tetto anti-memory-leak sulla porzione di body
// letta per l'estrazione feature. Lo stesso principio già applicato in
// pkg/interceptor/injecting_writer.go (maxBufferableBodySize): un attaccante
// non deve poter esaurire la RAM del proxy mandando un POST enorme proprio
// al componente che dovrebbe rilevare l'attacco. 1MB è ampiamente sufficiente
// per le feature estratte da ai-service/features.py (che lavorano su path,
// query string e contenuto testuale del body, non su file binari).
const maxRequestBodyBytes = 1 << 20 // 1MB

// maxErrorBodyBytes limita quanto leggiamo dal body di una risposta di
// errore di FastAPI, solo per loggarlo — non ci serve di più.
const maxErrorBodyBytes = 4 << 10 // 4KB

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
	timeout    time.Duration
	httpClient *http.Client
}

// NewHTTPAIClient costruisce il client con un timeout aggressivo: se FastAPI
// non risponde in tempo, l'interceptor deve poter fare fail-open senza
// bloccare il traffico legittimo.
//
// IMPORTANTE sul vincolo di latenza <2ms: quel vincolo copre l'overhead
// PURO del proxy (routing, buffering, injection) sul traffico che NON deve
// aspettare l'IA — non la chiamata sincrona a FastAPI, che ha un budget di
// latenza SEPARATO e volutamente più ampio (qui di default 20ms). È un
// trade-off esplicito latenza/accuratezza: ogni richiesta scorata in modo
// sincrono paga questo costo aggiuntivo. Se in futuro serve rispettare i
// <2ms anche per il traffico che passa dall'IA, l'unica strada reale è
// disaccoppiare lo scoring dal path sincrono (es. scoring asincrono con
// decisione differita, o pre-scoring/caching) — fuori scope per ora, ma
// va dichiarato chiaramente in tesi per non contraddirsi.
func NewHTTPAIClient(endpoint string, timeout time.Duration) *HTTPAIClient {
	if timeout <= 0 {
		timeout = 20 * time.Millisecond
	}
	return &HTTPAIClient{
		endpoint: endpoint,
		timeout:  timeout,
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
	// Corpo della richiesta: lo leggiamo (con un cap anti-memory-leak) e lo
	// rimettiamo subito a posto (r.Body è uno stream leggibile una volta
	// sola) così il resto della pipeline (es. il Router che poi farà il
	// forward reale) possa comunque leggerlo integro.
	//
	// NB: se il body originale supera maxRequestBodyBytes, lo scoring lavora
	// solo sulla porzione troncata (fail-safe: meglio un'analisi parziale
	// che un OOM), ma il body ORIGINALE completo viene comunque ripristinato
	// intatto su r.Body per non rompere il forwarding a WordPress.
	var bodyBytes []byte
	var scoringBody []byte
	if r.Body != nil {
		raw, err := io.ReadAll(io.LimitReader(r.Body, maxRequestBodyBytes+1))
		if err != nil {
			return 0, fmt.Errorf("aiclient: errore lettura body: %w", err)
		}
		bodyBytes = raw
		r.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))

		if len(raw) > maxRequestBodyBytes {
			scoringBody = raw[:maxRequestBodyBytes]
		} else {
			scoringBody = raw
		}
	}

	payload := requestPayload{
		URL:         r.URL.RequestURI(), // path + query, es. "/tienda1/x.jsp?id=1"
		Method:      r.Method,
		Content:     string(scoringBody),
		ContentType: r.Header.Get("Content-Type"),
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return 0, fmt.Errorf("aiclient: errore serializzazione payload: %w", err)
	}

	// Context con timeout derivato dalla richiesta originale: se il client
	// a monte si disconnette, la chiamata a FastAPI viene cancellata subito
	// invece di continuare fino al timeout "a vuoto".
	ctx, cancel := context.WithTimeout(r.Context(), c.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return 0, fmt.Errorf("aiclient: errore creazione richiesta: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		// Include i casi di timeout e di context cancellato: il chiamante
		// farà fail-open.
		return 0, fmt.Errorf("aiclient: errore chiamata a FastAPI: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		respBody, _ := io.ReadAll(io.LimitReader(resp.Body, maxErrorBodyBytes))
		return 0, fmt.Errorf("aiclient: FastAPI ha risposto %d: %s", resp.StatusCode, string(respBody))
	}

	var result scoreResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, fmt.Errorf("aiclient: errore decodifica risposta: %w", err)
	}

	return result.RiskScore, nil
}
