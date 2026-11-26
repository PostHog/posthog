package gitread

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

func TestGrantClientContract(t *testing.T) {
	fixture, err := os.ReadFile("testdata/grant.json")
	if err != nil {
		t.Fatal(err)
	}
	var contract struct {
		Registration identity.Registration `json:"registration"`
		Repository   string                `json:"repository"`
	}
	if err := json.Unmarshal(fixture, &contract); err != nil {
		t.Fatal(err)
	}
	contract.Registration.LeaseExpiresAt = time.Now().Add(time.Minute)
	key := "synthetic-grant-client-signing-key-0000"
	for _, test := range []struct {
		name   string
		status int
		change func(map[string]any)
		want   error
	}{
		{name: "published", status: 200},
		{name: "missing", status: 404, want: ErrDenied},
		{name: "auth failure", status: 403, want: ErrUnavailable},
		{name: "outage", status: 503, want: ErrUnavailable},
		{name: "redirect", status: 302, want: ErrUnavailable},
		{name: "foreign repo", status: 200, change: func(v map[string]any) { v["repository"] = "example/other" }, want: ErrUnavailable},
		{name: "foreign team", status: 200, change: func(v map[string]any) { v["registration"].(map[string]any)["team_id"] = 99 }, want: ErrUnavailable},
		{name: "foreign execution", status: 200, change: func(v map[string]any) {
			v["registration"].(map[string]any)["execution_id"] = "44444444-4444-4444-8444-444444444444"
		}, want: ErrUnavailable},
		{name: "foreign region", status: 200, change: func(v map[string]any) { v["registration"].(map[string]any)["region"] = "other-region" }, want: ErrUnavailable},
		{name: "missing revoked", status: 200, change: func(v map[string]any) { delete(v["registration"].(map[string]any), "revoked") }, want: ErrUnavailable},
		{name: "revoked", status: 200, change: func(v map[string]any) { v["registration"].(map[string]any)["revoked"] = true }, want: ErrDenied},
		{name: "expired", status: 200, change: func(v map[string]any) { v["expires_at"] = time.Now().Add(-time.Second).Format(time.RFC3339) }, want: ErrDenied},
		{name: "expired lease", status: 200, change: func(v map[string]any) {
			v["registration"].(map[string]any)["lease_expires_at"] = time.Now().Add(-time.Second).Format(time.RFC3339)
		}, want: ErrDenied},
		{name: "oversized", status: 200, change: func(v map[string]any) { v["token"] = strings.Repeat("x", 20<<10) }, want: ErrUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			var payload map[string]any
			if err := json.Unmarshal(fixture, &payload); err != nil {
				t.Fatal(err)
			}
			payload["registration"].(map[string]any)["lease_expires_at"] = time.Now().Add(30 * time.Second).Format(time.RFC3339)
			payload["expires_at"] = time.Now().Add(time.Minute).Format(time.RFC3339)
			if test.change != nil {
				test.change(payload)
			}
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/api/projects/42/internal/agent_egress/runs/"+contract.Registration.RunID+"/executions/"+contract.Registration.ExecutionID+"/git_read_grant/" {
					t.Errorf("unexpected path %s", r.URL.Path)
				}
				claims := jwt.MapClaims{}
				_, err := jwt.ParseWithClaims(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), claims,
					func(*jwt.Token) (any, error) { return []byte(key), nil },
					jwt.WithValidMethods([]string{"HS256"}), jwt.WithAudience("posthog:agent_egress_credentials"), jwt.WithExpirationRequired())
				if err != nil || claims["operation"] != "git_read_grant" || claims["sub"] != contract.Registration.RunID ||
					claims["execution_id"] != contract.Registration.ExecutionID || claims["team_id"] != float64(42) ||
					claims["region"] != "test-region" || claims["repository"] != contract.Repository ||
					claims["exp"].(float64)-claims["iat"].(float64) != 30 {
					t.Error("incorrect scoped authentication")
				}
				w.Header().Set("Location", "/must-not-follow")
				w.WriteHeader(test.status)
				_ = json.NewEncoder(w).Encode(payload)
			}))
			defer server.Close()
			client, err := NewClient(ClientConfig{BaseURL: server.URL, Region: "test-region", SigningKey: key, Timeout: time.Second, HTTPClient: server.Client()})
			if err != nil {
				t.Fatal(err)
			}
			grant, err := client.Lookup(context.Background(), LookupRequest{Identity: contract.Registration, Repository: contract.Repository})
			if !errors.Is(err, test.want) {
				t.Fatalf("lookup error = %v, want %v", err, test.want)
			}
			if test.want == nil && (grant.Token != "synthetic-git-read-token" || grant.CredentialVersion != "33333333-3333-4333-8333-333333333333") {
				t.Error("published credential not returned")
			}
			if test.want != nil && grant.Token != "" {
				t.Error("failure returned a credential")
			}
		})
	}
}

func TestGrantClientReusesConnectionsAfterErrors(t *testing.T) {
	registration := registration()
	registration.RunID, registration.ExecutionID = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
	for _, test := range []struct {
		name        string
		status      int
		body        string
		connections int32
		want        error
	}{
		{"denied", 404, `{"detail":"Git grant not found."}`, 1, ErrDenied},
		{"unavailable", 503, `{"detail":"Git grant unavailable."}`, 1, ErrUnavailable},
		{"oversized error", 503, strings.Repeat("x", 32<<10), 2, ErrUnavailable},
	} {
		t.Run(test.name, func(t *testing.T) {
			var connections atomic.Int32
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(test.status)
				_, _ = w.Write([]byte(test.body))
			}))
			server.Config.ConnState = func(_ net.Conn, state http.ConnState) {
				if state == http.StateNew {
					connections.Add(1)
				}
			}
			server.StartTLS()
			defer server.Close()
			client, err := NewClient(ClientConfig{BaseURL: server.URL, Region: "test-region", SigningKey: strings.Repeat("x", 32), Timeout: 10 * time.Second, HTTPClient: server.Client()})
			if err != nil {
				t.Fatal(err)
			}
			for range 2 {
				if _, err := client.Lookup(t.Context(), LookupRequest{Identity: registration, Repository: "example/repo"}); !errors.Is(err, test.want) {
					t.Fatalf("lookup error = %v, want %v", err, test.want)
				}
			}
			if connections.Load() != test.connections {
				t.Fatalf("error responses used %d connections, want %d", connections.Load(), test.connections)
			}
		})
	}
}

func TestGrantClientTLSAndCancellation(t *testing.T) {
	if _, err := NewClient(ClientConfig{BaseURL: "http://registry.example.com", Region: "test-region", SigningKey: strings.Repeat("x", 32), Timeout: time.Second}); err == nil {
		t.Fatal("accepted plaintext credential transport")
	}
	started, canceled := make(chan struct{}), make(chan struct{})
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		w.(http.Flusher).Flush()
		close(started)
		<-r.Context().Done()
		close(canceled)
	}))
	defer server.Close()
	client, err := NewClient(ClientConfig{BaseURL: server.URL, Region: "test-region", SigningKey: strings.Repeat("x", 32), Timeout: time.Second, HTTPClient: server.Client()})
	if err != nil {
		t.Fatal(err)
	}
	registration := registration()
	registration.RunID, registration.ExecutionID = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		_, err := client.Lookup(ctx, LookupRequest{Identity: registration, Repository: "example/repo"})
		done <- err
	}()
	select {
	case <-started:
	case <-time.After(5 * time.Second):
		t.Fatal("lookup did not start")
	}
	cancel()
	if err := <-done; !errors.Is(err, ErrUnavailable) {
		t.Fatalf("canceled lookup = %v", err)
	}
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("registry request not canceled")
	}
}
