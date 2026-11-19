package app_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
)

func TestHealthcheckReportsStatusWithoutFollowingRedirects(t *testing.T) {
	for _, mode := range []string{"proxy", "relay"} {
		for _, status := range []int{http.StatusNoContent, http.StatusOK, http.StatusServiceUnavailable, http.StatusFound} {
			t.Run(mode+"/"+http.StatusText(status), func(t *testing.T) {
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if r.URL.Path != "/readyz" || r.Method != http.MethodGet {
						t.Errorf("unexpected health request: %s %s", r.Method, r.URL.Path)
						w.WriteHeader(http.StatusNoContent)
						return
					}
					w.Header().Set("Location", "/redirect")
					w.WriteHeader(status)
				}))
				defer server.Close()
				config, err := json.Marshal(map[string]string{"admin_address": server.Listener.Addr().String()})
				if err != nil {
					t.Fatal(err)
				}
				path := writeTestFile(t, "config.json", config)
				err = app.CheckHealth(t.Context(), mode, path, "ready")
				if (err == nil) != (status == http.StatusNoContent) {
					t.Fatalf("status %d returned %v", status, err)
				}
				ctx, cancel := context.WithCancel(t.Context())
				cancel()
				if app.CheckHealth(ctx, mode, path, "ready") == nil {
					t.Fatal("cancelled check succeeded")
				}
				server.Close()
				if app.CheckHealth(t.Context(), mode, path, "ready") == nil {
					t.Fatal("stopped service passed health check")
				}
			})
		}
	}
}
