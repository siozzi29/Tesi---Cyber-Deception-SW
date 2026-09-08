package aiclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

// maxRequestBodyBytes è il tetto anti-memory-leak sulla porzione di body
// letta per l'estrazione feature.
const maxRequestBodyBytes = 1 << 20 // 1MB

// maxErrorBodyBytes limita quanto leggiamo dal body di una risposta di errore.
const maxErrorBodyBytes = 4 << 10 // 4KB

// requestPayload rispecchia esattamente il modello Pydantic RequestPayload
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

type tokenCache struct {
	mu        sync.RWMutex
	token     string
	expiresAt time.Time
}

// HTTPAIClient implementa l'interfaccia AIClient (definita in pkg/interceptor)
// chiamando il servizio FastAPI con il modello Isolation Forest.
type HTTPAIClient struct {
	endpoint   string // es. "http://localhost:8000/score" o "https://waap-ai-engine-..."
	timeout    time.Duration
	httpClient *http.Client
	tokenCache tokenCache
}

// getGoogleIDToken recupera un token OIDC dal Google Cloud Metadata Server
// per consentire l'invocazione sicura Service-to-Service tra Cloud Run privati.
func (c *HTTPAIClient) getGoogleIDToken(ctx context.Context, endpointURL string) (string, error) {
	if !strings.HasPrefix(endpointURL, "https://") {
		return "", nil // Se locale (HTTP), nessun token richiesto
	}

	c.tokenCache.mu.RLock()
	if c.tokenCache.token != "" && time.Now().Before(c.tokenCache.expiresAt) {
		token := c.tokenCache.token
		c.tokenCache.mu.RUnlock()
		return token, nil
	}
	c.tokenCache.mu.RUnlock()

	c.tokenCache.mu.Lock()
	defer c.tokenCache.mu.Unlock()

	if c.tokenCache.token != "" && time.Now().Before(c.tokenCache.expiresAt) {
		return c.tokenCache.token, nil
	}

	// Estrae l'audience base (es. https://waap-ai-engine-xxxx.run.app)
	parts := strings.Split(endpointURL, "/")
	if len(parts) < 3 {
		return "", fmt.Errorf("endpoint invalido")
	}
	baseAudience := parts[0] + "//" + parts[2]

	metaURL := fmt.Sprintf("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience=%s", baseAudience)
	metaReq, err := http.NewRequestWithContext(ctx, http.MethodGet, metaURL, nil)
	if err != nil {
		return "", err
	}
	metaReq.Header.Set("Metadata-Flavor", "Google")

	metaClient := &http.Client{Timeout: 2 * time.Second}
	metaResp, err := metaClient.Do(metaReq)
	if err != nil {
		return "", err
	}
	defer metaResp.Body.Close()

	if metaResp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("metadata server code: %d", metaResp.StatusCode)
	}

	tokenBytes, err := io.ReadAll(metaResp.Body)
	if err != nil {
		return "", err
	}

	token := strings.TrimSpace(string(tokenBytes))
	c.tokenCache.token = token
	c.tokenCache.expiresAt = time.Now().Add(45 * time.Minute)

	return token, nil
}

// NewHTTPAIClient costruisce il client con un timeout aggressivo: se FastAPI
// non risponde in tempo, l'interceptor deve poter fare fail-open senza
// bloccare il traffico legittimo.
//
// IMPORTANTE sul vincolo di latenza <2ms: quel vincolo copre l'overhead
// PURO del proxy (routing, buffering, injection) sul traffico che NON deve
// aspettare l'IA — non la chiamata sincrona a FastAPI, che ha un budget di
// latenza SEPARATO e volutamente più ampio (qui di default 5s). È un
// trade-off esplicito latenza/accuratezza: ogni richiesta scorata in modo
// sincrono paga questo costo aggiuntivo. Se in futuro serve rispettare i
// <2ms anche per il traffico che passa dall'IA, l'unica strada reale è
// disaccoppiare lo scoring dal path sincrono (es. scoring asincrono con
// decisione differita, o pre-scoring/caching) — fuori scope per ora, ma
// va dichiarato chiaramente in tesi per non contraddirsi.
func NewHTTPAIClient(endpoint string, timeout time.Duration) *HTTPAIClient {
	if timeout <= 0 {
		timeout = 5 * time.Second
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

	// Service-to-Service auth su Google Cloud Run
	if token, err := c.getGoogleIDToken(ctx, c.endpoint); err == nil && token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

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
