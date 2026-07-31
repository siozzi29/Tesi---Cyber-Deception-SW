package injector

import (
	"strings"
	"testing"
	"time"
)

func TestGenerateTokenFormatAndUniqueness(t *testing.T) {
	inj := NewHoneyURLInjector(time.Minute)
	defer inj.Close()

	t1, err := inj.generateToken()
	if err != nil {
		t.Fatalf("errore generazione token: %v", err)
	}
	t2, err := inj.generateToken()
	if err != nil {
		t.Fatalf("errore generazione token: %v", err)
	}
	if t1 == t2 {
		t.Fatal("due token generati sono identici, entropia insufficiente")
	}
	if !strings.HasPrefix(t1, honeyURLPrefix) {
		t.Fatalf("token %q non ha il prefisso atteso %q", t1, honeyURLPrefix)
	}
}

func TestInjectRegistersHoneyURL(t *testing.T) {
	inj := NewHoneyURLInjector(time.Minute)
	defer inj.Close()

	body := []byte("<html><body><h1>Hello</h1></body></html>")
	out := inj.Inject(body)

	if len(out) <= len(body) {
		t.Fatal("il body non è stato modificato dall'iniezione")
	}
	if !strings.Contains(string(out), `aria-hidden="true"`) {
		t.Fatal("l'esca iniettata non contiene gli attributi di occultamento attesi")
	}

	honeyPath := extractHoneyPath(t, string(out))

	if !inj.IsHoneyURL(honeyPath) {
		t.Fatalf("il path iniettato %q non risulta registrato come honey-URL", honeyPath)
	}
}

func TestInjectWithoutBodyClosingTag(t *testing.T) {
	inj := NewHoneyURLInjector(time.Minute)
	defer inj.Close()

	body := []byte("plain text response, no html")
	out := inj.Inject(body)

	if !strings.HasPrefix(string(out), "plain text response, no html") {
		t.Fatal("il contenuto originale è stato alterato invece di solo accodato")
	}
	if len(out) <= len(body) {
		t.Fatal("l'esca non è stata accodata quando manca </body>")
	}
}

func TestIsHoneyURLUnknownPath(t *testing.T) {
	inj := NewHoneyURLInjector(time.Minute)
	defer inj.Close()

	if inj.IsHoneyURL("/percorso/mai/registrato") {
		t.Fatal("un path mai iniettato non deve risultare un honey-URL")
	}
}

func TestHoneyURLExpires(t *testing.T) {
	inj := NewHoneyURLInjector(50 * time.Millisecond)
	defer inj.Close()

	body := []byte("<body></body>")
	out := inj.Inject(body)
	honeyPath := extractHoneyPath(t, string(out))

	if !inj.IsHoneyURL(honeyPath) {
		t.Fatal("il token dovrebbe essere valido subito dopo l'iniezione")
	}

	time.Sleep(100 * time.Millisecond)

	if inj.IsHoneyURL(honeyPath) {
		t.Fatal("il token doveva essere scaduto ma risulta ancora valido")
	}
}

// extractHoneyPath è un helper di test che estrae l'URL iniettato nell'href
// dell'esca, per poterlo poi ripassare a IsHoneyURL nelle assertion.
func extractHoneyPath(t *testing.T, html string) string {
	t.Helper()
	const marker = `href="`
	start := strings.Index(html, marker)
	if start == -1 {
		t.Fatal("nessun href trovato nell'output iniettato")
	}
	start += len(marker)
	end := strings.Index(html[start:], `"`)
	if end == -1 {
		t.Fatal("href malformato nell'output iniettato")
	}
	return html[start : start+end]
}
