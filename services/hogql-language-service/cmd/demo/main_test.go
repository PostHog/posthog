package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
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
			demoHandler("", allowedHost, nil).ServeHTTP(response, request)
			if response.Code != test.status {
				t.Fatalf("status = %d, want %d", response.Code, test.status)
			}
		})
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
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
			}))
			defer backend.Close()
			request := httptest.NewRequest(http.MethodPost, "http://"+test.host+"/api/"+test.operation, strings.NewReader(payload))
			request.Header.Set("Content-Type", "application/json")
			request.Header.Set("Origin", test.origin)
			request.Header.Set("Authorization", "Bearer fake-demo-token")
			request.Header.Set("Cookie", "session=fake-demo-session")
			response := httptest.NewRecorder()
			demoHandler(backend.URL, test.allowedHost, nil).ServeHTTP(response, request)
			if response.Code != http.StatusBadRequest || response.Body.String() != `{"error":"demo response"}` {
				t.Fatalf("response = %d %s", response.Code, response.Body.String())
			}
		})
	}
}
