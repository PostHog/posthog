package api

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthEndpoints(t *testing.T) {
	srv := NewServer()

	cases := []struct {
		path string
	}{
		{"/_readiness"},
		{"/_liveness"},
	}

	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tc.path, nil)
			rec := httptest.NewRecorder()
			srv.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Fatalf("got %d, want %d", rec.Code, http.StatusOK)
			}
			if got, want := rec.Header().Get("Content-Type"), "application/json"; got != want {
				t.Fatalf("Content-Type = %q, want %q", got, want)
			}
		})
	}
}

func TestMetricsEndpoint(t *testing.T) {
	srv := NewServer()

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d, want %d", rec.Code, http.StatusOK)
	}
	// promhttp exposes go_* and process_* metrics by default.
	if rec.Body.Len() == 0 {
		t.Fatal("expected metrics body, got empty response")
	}
}
