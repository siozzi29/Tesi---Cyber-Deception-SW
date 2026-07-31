package interceptor

import (
	"bytes"
	"log"
	"net/http"
	"strconv"
	"strings"
)

// ============================================================================
// INJECTING RESPONSE WRITER
// Collega l'URLInjector al flusso live: buferizza SOLO le risposte HTML per
// iniettare l'esca, lascia passare tutto il resto (JSON, immagini, API) in
// streaming diretto senza overhead aggiuntivo.
// ============================================================================

// maxBufferableBodySize è il tetto oltre il quale rinunciamo all'injection
// per proteggere la memoria del proxy da risposte enormi (o costruite ad
// arte da un attaccante per esaurire la RAM del processo).
const maxBufferableBodySize = 5 * 1024 * 1024 // 5MB

// injectingResponseWriter implementa http.ResponseWriter e opzionalmente
// http.Flusher (passthrough) per non rompere risposte streaming legittime.
type injectingResponseWriter struct {
	underlying    http.ResponseWriter
	injector      URLInjector
	headerWritten bool
	buffering     bool
	tooLarge      bool
	statusCode    int
	buf           bytes.Buffer
}

// newInjectingResponseWriter crea il wrapper. La decisione buffering-o-no
// viene presa al primo WriteHeader, quando conosciamo il Content-Type reale
// impostato dal backend a monte (via ReverseProxy).
func newInjectingResponseWriter(w http.ResponseWriter, inj URLInjector) *injectingResponseWriter {
	return &injectingResponseWriter{
		underlying: w,
		injector:   inj,
		statusCode: http.StatusOK,
	}
}

// Header ritorna la mappa header reale: ReverseProxy la popola con gli
// header del backend PRIMA di chiamare WriteHeader, quindi non serve
// duplicarla qui.
func (iw *injectingResponseWriter) Header() http.Header {
	return iw.underlying.Header()
}

// shouldBufferResponse decide se una risposta va bufferizzata per l'injection.
// In caso di Content-Type assente o ancora non disponibile al momento del
// WriteHeader, usiamo un fallback conservativo e bufferizziamo: meglio
// tentare l'injection su HTML potenziale che saltarla completamente.
func shouldBufferResponse(contentType string) bool {
	contentType = strings.TrimSpace(contentType)
	if contentType == "" {
		return true
	}
	return strings.HasPrefix(contentType, "text/html") ||
		strings.HasPrefix(contentType, "application/xhtml+xml")
}

// WriteHeader decide la modalità (buffering vs passthrough) in base al
// Content-Type e, solo in passthrough, inoltra subito gli header reali.
func (iw *injectingResponseWriter) WriteHeader(code int) {
	if iw.headerWritten {
		return
	}
	iw.headerWritten = true
	iw.statusCode = code

	ct := iw.underlying.Header().Get("Content-Type")
	iw.buffering = shouldBufferResponse(ct)

	if !iw.buffering {
		// Traffico non-HTML: nessun buffering, scriviamo subito e via.
		iw.underlying.WriteHeader(code)
	}
	// Se buffering, ritardiamo la scrittura reale finché non abbiamo tutto
	// il body: dobbiamo ricalcolare Content-Length dopo l'injection.
}

// Write buferizza solo in modalità HTML, con tetto anti-memory-leak.
// Superata la soglia, degradiamo con grazia: molliamo l'injection e
// passiamo il resto in streaming diretto, senza rompere la risposta.
func (iw *injectingResponseWriter) Write(p []byte) (int, error) {
	if !iw.headerWritten {
		iw.WriteHeader(http.StatusOK)
	}

	if iw.buffering {
		if iw.buf.Len()+len(p) > maxBufferableBodySize {
			log.Printf("[INJECTOR] Body HTML oltre %d byte: injection saltata, passo in streaming diretto", maxBufferableBodySize)
			iw.buffering = false
			iw.tooLarge = true

			iw.underlying.WriteHeader(iw.statusCode)
			if iw.buf.Len() > 0 {
				iw.underlying.Write(iw.buf.Bytes())
				iw.buf.Reset()
			}
			return iw.underlying.Write(p)
		}
		return iw.buf.Write(p)
	}

	return iw.underlying.Write(p)
}

// Flush passa il flush al writer reale solo fuori dal buffering: mentre
// buferizziamo non ha senso flushare, aspettiamo il body completo.
func (iw *injectingResponseWriter) Flush() {
	if iw.buffering {
		return
	}
	if f, ok := iw.underlying.(http.Flusher); ok {
		f.Flush()
	}
}

// finalize va chiamato dall'interceptor DOPO che router.Forward è tornato.
// Se eravamo in modalità buffering, qui iniettiamo l'esca, ricalcoliamo
// Content-Length e scriviamo davvero sul client.
func (iw *injectingResponseWriter) finalize() {
	if !iw.headerWritten {
		// Handler che non ha mai scritto nulla: garantiamo comunque una
		// risposta valida invece di lasciare la connessione appesa.
		iw.WriteHeader(http.StatusOK)
	}
	if !iw.buffering {
		// Passthrough (non-HTML) o già degradato per body troppo grande:
		// tutto è già stato scritto in streaming, niente da fare.
		return
	}

	original := iw.buf.Bytes()
	finalBody := original

	if enc := iw.underlying.Header().Get("Content-Encoding"); enc == "" {
		finalBody = iw.injector.Inject(original)
	} else {
		// Body compresso a monte (gzip/br/deflate): iniettare byte grezzi
		// lo corromperebbe. Meglio una risposta integra senza esca che una
		// risposta rotta per un utente legittimo.
		log.Printf("[INJECTOR] Content-Encoding=%q rilevato, injection saltata per non corrompere il body", enc)
	}

	iw.underlying.Header().Set("Content-Length", strconv.Itoa(len(finalBody)))
	iw.underlying.WriteHeader(iw.statusCode)
	if _, err := iw.underlying.Write(finalBody); err != nil {
		log.Printf("[INJECTOR] Errore scrittura body finale: %v", err)
	}
}
