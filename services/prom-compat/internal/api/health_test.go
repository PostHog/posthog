package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHealthEndpoints(t *testing.T) {
	srv := NewServer(Deps{})

	cases := []string{"/_readiness", "/_liveness"}

	for _, path := range cases {
		t.Run(path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			rec := httptest.NewRecorder()
			srv.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Fatalf("got %d, want %d", rec.Code, http.StatusOK)
			}
			if got, want := rec.Header().Get("Content-Type"), "application/json"; got != want {
				t.Fatalf("Content-Type = %q, want %q", got, want)
			}
			var body readinessBody
			if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
				t.Fatalf("decode body: %v", err)
			}
			if body.Status != "ok" {
				t.Fatalf("status = %q, want %q", body.Status, "ok")
			}
		})
	}
}

func TestReadinessOmitsClickHouseWhenStorageNil(t *testing.T) {
	srv := NewServer(Deps{})
	req := httptest.NewRequest(http.MethodGet, "/_readiness", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if got := rec.Body.String(); strings.Contains(got, "clickhouse") {
		t.Fatalf("expected no clickhouse field when Storage is nil, got: %s", got)
	}
}

func TestMetricsEndpoint(t *testing.T) {
	srv := NewServer(Deps{})
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("got %d, want %d", rec.Code, http.StatusOK)
	}
	if rec.Body.Len() == 0 {
		t.Fatal("expected metrics body, got empty response")
	}
}
