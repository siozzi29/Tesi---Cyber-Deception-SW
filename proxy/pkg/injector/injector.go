package injector

import (
	"bytes"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log"
	"sync"
	"time"
)

// ============================================================================
// HONEY-URL INJECTOR (Livello 3 - Modello C4)
// Genera esche invisibili a runtime e riconosce chi ci casca.
// ============================================================================

const (
	// Prefisso mimetico: sembra un endpoint interno legittimo, non un trap
	// riconoscibile a colpo d'occhio (evitiamo nomi tipo "/honeypot/...").
	honeyURLPrefix = "/sys/health-check-"

	tokenByteLen    = 8                // 16 caratteri hex, entropia sufficiente e non-guessable
	defaultTTL      = 30 * time.Minute // durata di vita di un honeytoken
	cleanupInterval = 5 * time.Minute  // frequenza dello sweep di pulizia

	// maxActiveTokens è il tetto anti-memory-leak sul numero di honeytoken
	// vivi contemporaneamente. Tra due sweep (cleanupInterval) un sito con
	// traffico HTML alto, o un bot che fa scraping aggressivo di pagine
	// legittime, potrebbe far crescere la mappa senza limite. Oltre la
	// soglia, fail-safe: saltiamo l'injection su quella risposta invece di
	// rischiare l'esaurimento della memoria del proxy.
	maxActiveTokens = 50_000
)

// honeyEntry traccia la scadenza di un singolo honeytoken.
type honeyEntry struct {
	expiresAt time.Time
}

// HoneyURLInjector implementa interceptor.URLInjector.
type HoneyURLInjector struct {
	mu        sync.RWMutex
	tokens    map[string]honeyEntry
	ttl       time.Duration
	stopCh    chan struct{}
	closeOnce sync.Once
}

// NewHoneyURLInjector crea l'injector e avvia il goroutine di pulizia periodica
// (fondamentale per non accumulare token scaduti all'infinito -> memory leak).
func NewHoneyURLInjector(ttl time.Duration) *HoneyURLInjector {
	if ttl <= 0 {
		ttl = defaultTTL
	}
	inj := &HoneyURLInjector{
		tokens: make(map[string]honeyEntry),
		ttl:    ttl,
		stopCh: make(chan struct{}),
	}
	go inj.cleanupLoop()
	return inj
}

// Close ferma il goroutine di pulizia. Va chiamato durante il graceful
// shutdown dell'applicazione per non lasciare goroutine appese.
// Idempotente: chiamarlo più di una volta non causa panic.
func (h *HoneyURLInjector) Close() {
	h.closeOnce.Do(func() {
		close(h.stopCh)
	})
}

// cleanupLoop rimuove periodicamente i token scaduti dalla mappa.
func (h *HoneyURLInjector) cleanupLoop() {
	ticker := time.NewTicker(cleanupInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ticker.C:
			h.sweep()
		case <-h.stopCh:
			return
		}
	}
}

func (h *HoneyURLInjector) sweep() {
	now := time.Now()
	h.mu.Lock()
	defer h.mu.Unlock()
	for path, entry := range h.tokens {
		if now.After(entry.expiresAt) {
			delete(h.tokens, path)
		}
	}
}

// generateToken crea un path honeypot casuale e crittograficamente imprevedibile.
func (h *HoneyURLInjector) generateToken() (string, error) {
	buf := make([]byte, tokenByteLen)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return honeyURLPrefix + hex.EncodeToString(buf), nil
}

// IsHoneyURL implementa interceptor.URLInjector: controllo O(1) sulla mappa.
func (h *HoneyURLInjector) IsHoneyURL(path string) bool {
	h.mu.RLock()
	entry, exists := h.tokens[path]
	h.mu.RUnlock()

	if !exists {
		return false
	}
	if time.Now().After(entry.expiresAt) {
		// Scaduto ma non ancora ripulito dallo sweep: lazy delete.
		h.mu.Lock()
		delete(h.tokens, path)
		h.mu.Unlock()
		return false
	}
	return true
}

// Inject implementa interceptor.URLInjector: genera un nuovo honeytoken,
// lo registra, e lo inserisce nel body HTML come link invisibile appena
// prima di </body>. Se la generazione fallisce, O se abbiamo raggiunto il
// tetto anti-memory-leak, ritorna il body originale invariato (fail-open:
// non vogliamo rompere una risposta legittima per un problema di injection).
func (h *HoneyURLInjector) Inject(body []byte) []byte {
	h.mu.RLock()
	activeCount := len(h.tokens)
	h.mu.RUnlock()

	if activeCount >= maxActiveTokens {
		log.Printf("[INJECTOR] Tetto di %d honeytoken attivi raggiunto, skip injection su questa risposta", maxActiveTokens)
		return body
	}

	token, err := h.generateToken()
	if err != nil {
		log.Printf("[INJECTOR] Errore generazione honeytoken, skip injection: %v", err)
		return body
	}

	h.mu.Lock()
	h.tokens[token] = honeyEntry{expiresAt: time.Now().Add(h.ttl)}
	h.mu.Unlock()

	// Esca completamente invisibile: display:none per i browser, aria-hidden
	// per gli screen reader (utenti reali non ci devono MAI cliccare per
	// sbaglio), tabindex=-1 per escluderla dalla navigazione da tastiera.
	// Solo un bot/scraper che parsa il DOM grezzo e segue ogni <a href>
	// ci casca.
	bait := fmt.Sprintf(
		`<a href="%s" style="display:none!important;visibility:hidden;position:absolute;left:-9999px" tabindex="-1" aria-hidden="true">.</a>`,
		token,
	)

	closingTag := []byte("</body>")
	idx := bytes.LastIndex(body, closingTag)
	if idx == -1 {
		// Nessun tag </body> (es. risposta non-HTML): accodiamo senza
		// tentare di riparare markup che non conosciamo.
		return append(body, []byte(bait)...)
	}

	var out bytes.Buffer
	out.Write(body[:idx])
	out.WriteString(bait)
	out.Write(body[idx:])
	return out.Bytes()
}
