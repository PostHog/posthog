package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

func TestDemoRejectsForeignBrowserRequests(t *testing.T) {
	for _, test := range []struct {
		name, host, origin, contentType string
		forwarded                       bool
		status                          int
	}{
		{name: "foreign host", host: "example.com", contentType: "application/json", status: http.StatusForbidden},
		{name: "foreign origin", host: "127.0.0.1:8092", origin: "https://example.com", contentType: "application/json", status: http.StatusForbidden},
		{name: "opaque origin", host: "127.0.0.1:8092", origin: "null", contentType: "application/json", status: http.StatusForbidden},
		{name: "form post", host: "127.0.0.1:8092", contentType: "application/x-www-form-urlencoded", status: http.StatusUnsupportedMediaType},
		{name: "forwarded foreign origin", host: "demo.example.com", origin: "https://other.example.com", contentType: "application/json", forwarded: true, status: http.StatusForbidden},
		{name: "forwarded opaque origin", host: "demo.example.com", origin: "null", contentType: "application/json", forwarded: true, status: http.StatusForbidden},
	} {
		t.Run(test.name, func(t *testing.T) {
			request := httptest.NewRequest(http.MethodPost, "http://"+test.host+"/api/validate", strings.NewReader(`{"query":"SELECT 1"}`))
			request.Header.Set("Origin", test.origin)
			request.Header.Set("Content-Type", test.contentType)
			response := httptest.NewRecorder()
			allowedHost := "127.0.0.1:8092"
			if test.forwarded {
				allowedHost = ""
			}
			demoHandler(nil, allowedHost, nil).ServeHTTP(response, request)
			if response.Code != test.status {
				t.Fatalf("status = %d, want %d", response.Code, test.status)
			}
		})
	}
}

func TestDemoEmbeddedService(t *testing.T) {
	handler, err := newDemoHandler("127.0.0.1:8092")
	if err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		method, path, body string
		status             int
	}{
		{http.MethodGet, "/api/health", "", http.StatusOK},
		{http.MethodPost, "/api/validate", `{"query":"WITH t AS (SELECT uuid FROM events) SELECT uuid FROM t"}`, http.StatusOK},
		{http.MethodPost, "/api/autocomplete", `{"query":"SELECT events.tim FROM events","position":17}`, http.StatusOK},
		{http.MethodPost, "/api/validate", `{"query":"SELECT 1","unknown":true}`, http.StatusBadRequest},
		{http.MethodPost, "/api/validate", strings.Repeat(" ", (128<<10)+1), http.StatusRequestEntityTooLarge},
		{http.MethodPut, "/teams/1/users/1/catalog", `{}`, http.StatusMethodNotAllowed},
		{http.MethodPost, "/teams/2/users/2/validate", `{"query":"SELECT 1"}`, http.StatusMethodNotAllowed},
	} {
		t.Run(test.method+test.path+"/"+http.StatusText(test.status), func(t *testing.T) {
			request := httptest.NewRequest(test.method, "http://127.0.0.1:8092"+test.path, strings.NewReader(test.body))
			request.Header.Set("Content-Type", "application/json")
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != test.status {
				t.Fatalf("response = %d %s, want %d", response.Code, response.Body.String(), test.status)
			}
			if test.status != http.StatusOK || test.path == "/api/health" {
				return
			}
			var revision struct {
				CatalogRevision string `json:"catalogRevision"`
			}
			if err := json.Unmarshal(response.Body.Bytes(), &revision); err != nil || revision.CatalogRevision != syntheticCatalog().Revision {
				t.Fatalf("catalog revision = %q (%v)", revision.CatalogRevision, err)
			}
			if test.path == "/api/validate" {
				var result validation.Result
				if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || !result.Valid || len(result.Diagnostics) != 0 || len(result.TableNames) != 1 || result.TableNames[0] != "events" {
					t.Fatalf("validation = %s (%v)", response.Body.String(), err)
				}
			} else {
				var result completion.Result
				if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil || len(result.Suggestions) != 1 || result.Suggestions[0].Label != "timestamp" {
					t.Fatalf("completion = %s (%v)", response.Body.String(), err)
				}
			}
		})
	}
}

func TestDemoHealthForwardsServiceFailure(t *testing.T) {
	backend := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/health" {
			t.Fatalf("forwarded request = %s %s", r.Method, r.URL.Path)
		}
		http.Error(w, "unhealthy", http.StatusServiceUnavailable)
	})
	request := httptest.NewRequest(http.MethodGet, "http://127.0.0.1:8092/api/health", nil)
	response := httptest.NewRecorder()

	demoHandler(backend, "127.0.0.1:8092", nil).ServeHTTP(response, request)

	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusServiceUnavailable)
	}
}

func TestDemoForwardsLanguageRequests(t *testing.T) {
	for _, test := range []struct {
		operation, host, origin, allowedHost string
	}{
		{"validate", "127.0.0.1:8092", "http://127.0.0.1:8092", "127.0.0.1:8092"},
		{"autocomplete", "127.0.0.1:8092", "http://127.0.0.1:8092", "127.0.0.1:8092"},
		{"validate", "demo.example.com", "https://demo.example.com", ""},
		{"autocomplete", "localhost:9000", "http://localhost:9000", ""},
	} {
		t.Run(test.operation+"/"+test.host, func(t *testing.T) {
			payload := `{"query":"SELECT '😀', e. FROM events AS e","position":16,"positionEncoding":"utf-16","cursor":"MjU="}`
			backend := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				body, err := io.ReadAll(r.Body)
				if err != nil || string(body) != payload || r.URL.Path != "/teams/1/users/1/"+test.operation || r.Method != http.MethodPost {
					t.Errorf("forwarded request = %s %s %s (%v)", r.Method, r.URL.Path, body, err)
				}
				if r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
					t.Error("browser credentials forwarded to demo backend")
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusBadRequest)
				_, _ = w.Write([]byte(`{"error":"demo response"}`))
			})
			request := httptest.NewRequest(http.MethodPost, "http://"+test.host+"/api/"+test.operation, strings.NewReader(payload))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Origin", test.origin)
			request.Header.Set("Authorization", "Bearer fake-demo-token")
			request.Header.Set("Cookie", "session=fake-demo-session")
			response := httptest.NewRecorder()
			demoHandler(backend, test.allowedHost, nil).ServeHTTP(response, request)
			if response.Code != http.StatusBadRequest || response.Body.String() != `{"error":"demo response"}` {
				t.Fatalf("response = %d %s", response.Code, response.Body.String())
			}
		})
	}
}
