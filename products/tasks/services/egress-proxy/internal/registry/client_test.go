package registry_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/registry"
)

const registryTestKey = "synthetic-registry-key-00000000000000"

func registrationFixture(t *testing.T) (json.RawMessage, identity.Registration) {
	t.Helper()
	data, err := os.ReadFile("../identity/testdata/python-capability.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Registration json.RawMessage
	}
	if err := json.Unmarshal(data, &fixture); err != nil {
		t.Fatal(err)
	}
	var registration identity.Registration
	if err := json.Unmarshal(fixture.Registration, &registration); err != nil {
		t.Fatal(err)
	}
	return fixture.Registration, registration
}

func lookupFor(registration identity.Registration) identity.LookupRequest {
	return identity.LookupRequest{
		TeamID: registration.TeamID, RunID: registration.RunID, ExecutionID: registration.ExecutionID,
	}
}

func registryClient(t *testing.T, server *httptest.Server) *registry.Client {
	t.Helper()
	client, err := registry.New(registry.Config{
		BaseURL: server.URL, Region: "test-region", SigningKey: registryTestKey,
		Timeout: 10 * time.Second, HTTPClient: server.Client(),
	})
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func TestClientLookupContract(t *testing.T) {
	body, expected := registrationFixture(t)
	var response map[string]json.RawMessage
	if err := json.Unmarshal(body, &response); err != nil {
		t.Fatal(err)
	}
	response["future_field"] = json.RawMessage(`true`)
	requests := make(chan *http.Request, 1)
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests <- r.Clone(context.Background())
		_ = json.NewEncoder(w).Encode(response)
	}))
	defer server.Close()
	got, err := registryClient(t, server).Lookup(context.Background(), lookupFor(expected))
	if err != nil || got != expected {
		t.Fatalf("Lookup() = %v, %v; want %v", got, err, expected)
	}
	request := <-requests
	wantPath := "/api/projects/42/internal/agent_egress/runs/" + expected.RunID + "/executions/" + expected.ExecutionID
	if request.Method != http.MethodGet || request.URL.RequestURI() != wantPath || request.Header.Get("Accept") != "application/json" {
		t.Fatalf("unexpected registry request: %s %s, accept %q", request.Method, request.URL.RequestURI(), request.Header.Get("Accept"))
	}
	encoded, found := strings.CutPrefix(request.Header.Get("Authorization"), "Bearer ")
	if !found {
		t.Fatal("lookup request has no service bearer token")
	}
	token, err := jwt.Parse(encoded, func(_ *jwt.Token) (any, error) {
		return []byte(registryTestKey), nil
	}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithAudience("posthog:agent_egress_registry"), jwt.WithJSONNumber())
	if err != nil {
		t.Fatal(err)
	}
	claims := token.Claims.(jwt.MapClaims)
	for name, want := range map[string]any{
		"aud": "posthog:agent_egress_registry", "sub": expected.RunID,
		"team_id": json.Number("42"), "execution_id": expected.ExecutionID,
		"region": "test-region", "operation": "lookup",
	} {
		if claims[name] != want {
			t.Errorf("service claim %s = %v; want %v", name, claims[name], want)
		}
	}
	iat, iatOK := claims["iat"].(json.Number)
	exp, expOK := claims["exp"].(json.Number)
	issuedAt, iatErr := iat.Int64()
	expiresAt, expErr := exp.Int64()
	if !iatOK || !expOK || iatErr != nil || expErr != nil || expiresAt-issuedAt != 30 {
		t.Fatalf("service lifetime must use integer dates 30 seconds apart: iat=%v exp=%v", claims["iat"], claims["exp"])
	}
}

func TestClientLookupFailures(t *testing.T) {
	body, expected := registrationFixture(t)
	for _, status := range []int{401, 403, 404, 429, 500, 503} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(status)
				_, _ = w.Write(body)
			}))
			defer server.Close()
			want := identity.ErrUnavailable
			if status == 404 {
				want = identity.ErrUnauthorized
			}
			got, err := registryClient(t, server).Lookup(context.Background(), lookupFor(expected))
			if !errors.Is(err, want) || got != (identity.Registration{}) {
				t.Fatalf("Lookup() = %v, %v; want empty registration and %v", got, err, want)
			}
		})
	}
	for _, tc := range []struct {
		name  string
		field string
		value any
	}{
		{"foreign team", "team_id", 43},
		{"foreign run", "run_id", "33333333-3333-4333-8333-333333333333"},
		{"foreign execution", "execution_id", "44444444-4444-4444-8444-444444444444"},
		{"foreign region", "region", "other-region"},
		{"missing region", "region", nil},
		{"missing actor", "actor_id", nil},
		{"missing epoch", "actor_epoch", nil},
		{"missing authority", "authority", nil},
		{"missing deadline", "lease_expires_at", nil},
		{"invalid fingerprint", "relay_key_sha256", "invalid"},
		{"missing revoked", "revoked", nil},
		{"revoked", "revoked", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var response map[string]any
			if err := json.Unmarshal(body, &response); err != nil {
				t.Fatal(err)
			}
			response[tc.field] = tc.value
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_ = json.NewEncoder(w).Encode(response)
			}))
			defer server.Close()
			want := identity.ErrUnavailable
			if tc.name == "revoked" {
				want = identity.ErrUnauthorized
			}
			got, err := registryClient(t, server).Lookup(context.Background(), lookupFor(expected))
			if !errors.Is(err, want) || got != (identity.Registration{}) {
				t.Fatalf("Lookup() = %v, %v; want empty registration and %v", got, err, want)
			}
		})
	}
	for name, response := range map[string]string{
		"malformed JSON": "{",
		"trailing JSON":  string(body) + "{}",
		"oversized":      string(body) + strings.Repeat(" ", 16<<10),
	} {
		t.Run(name, func(t *testing.T) {
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				_, _ = io.WriteString(w, response)
			}))
			defer server.Close()
			got, err := registryClient(t, server).Lookup(context.Background(), lookupFor(expected))
			if !errors.Is(err, identity.ErrUnavailable) || got != (identity.Registration{}) {
				t.Fatalf("Lookup() = %v, %v; want unavailable", got, err)
			}
		})
	}
}

func TestClientDoesNotFollowRedirects(t *testing.T) {
	body, expected := registrationFixture(t)
	var followed atomic.Bool
	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirected" {
			followed.Store(true)
			_, _ = w.Write(body)
			return
		}
		http.Redirect(w, r, "/redirected", http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	_, err := registryClient(t, server).Lookup(context.Background(), lookupFor(expected))
	if !errors.Is(err, identity.ErrUnavailable) || followed.Load() {
		t.Fatalf("redirect followed=%v, error=%v; want unavailable without forwarding credentials", followed.Load(), err)
	}
}

func TestClientReusesConnectionsAfterErrors(t *testing.T) {
	_, expected := registrationFixture(t)
	for _, tc := range []struct {
		name        string
		status      int
		body        string
		connections int32
	}{
		{"not found", http.StatusNotFound, `{"detail":"Registration not found."}`, 1},
		{"unavailable", http.StatusServiceUnavailable, `{"detail":"Registration unavailable."}`, 1},
		{"oversized error", http.StatusServiceUnavailable, strings.Repeat("x", 32<<10), 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var connections atomic.Int32
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = io.WriteString(w, tc.body)
			}))
			server.Config.ConnState = func(_ net.Conn, state http.ConnState) {
				if state == http.StateNew {
					connections.Add(1)
				}
			}
			server.StartTLS()
			defer server.Close()
			client := registryClient(t, server)
			want := identity.ErrUnavailable
			if tc.status == http.StatusNotFound {
				want = identity.ErrUnauthorized
			}
			for range 2 {
				if _, err := client.Lookup(t.Context(), lookupFor(expected)); !errors.Is(err, want) {
					t.Fatalf("Lookup() = %v; want %v", err, want)
				}
			}
			if connections.Load() != tc.connections {
				t.Fatalf("error responses used %d connections; want %d", connections.Load(), tc.connections)
			}
		})
	}
}

func TestClientCancellation(t *testing.T) {
	_, expected := registrationFixture(t)
	for _, tc := range []struct {
		name         string
		status       int
		flushHeaders bool
	}{
		{"success headers", http.StatusOK, false},
		{"success body", http.StatusOK, true},
		{"error headers", http.StatusServiceUnavailable, false},
		{"error body", http.StatusServiceUnavailable, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			started := make(chan struct{})
			stopped := make(chan struct{})
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.status)
				if tc.flushHeaders {
					_, _ = io.WriteString(w, "{")
					w.(http.Flusher).Flush()
				}
				close(started)
				<-r.Context().Done()
				close(stopped)
			}))
			defer server.Close()
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			result := make(chan error, 1)
			client := registryClient(t, server)
			go func() {
				_, err := client.Lookup(ctx, lookupFor(expected))
				result <- err
			}()
			<-started
			cancel()
			if err := <-result; !errors.Is(err, identity.ErrUnavailable) {
				t.Fatalf("canceled Lookup() = %v; want unavailable", err)
			}
			<-stopped
		})
	}
}

type registryRoundTripper func(*http.Request) (*http.Response, error)

func (f registryRoundTripper) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}

func TestClientPreservesRevocationOnCancellation(t *testing.T) {
	_, expected := registrationFixture(t)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	client, err := registry.New(registry.Config{
		BaseURL: "https://registry.example.com", Region: "test-region", SigningKey: registryTestKey,
		Timeout: time.Minute,
		HTTPClient: &http.Client{Transport: registryRoundTripper(func(_ *http.Request) (*http.Response, error) {
			cancel()
			return &http.Response{StatusCode: http.StatusNotFound, Body: io.NopCloser(strings.NewReader(""))}, nil
		})},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := client.Lookup(ctx, lookupFor(expected)); !errors.Is(err, identity.ErrUnauthorized) {
		t.Fatalf("revocation received during cancellation = %v; want unauthorized", err)
	}
}

func TestClientBoundsLookupDeadline(t *testing.T) {
	_, expected := registrationFixture(t)
	for _, parentDeadline := range []bool{false, true} {
		t.Run(strconv.FormatBool(parentDeadline), func(t *testing.T) {
			ctx := context.Background()
			var parent time.Time
			if parentDeadline {
				parent = time.Now().Add(time.Minute)
				var cancel context.CancelFunc
				ctx, cancel = context.WithDeadline(ctx, parent)
				defer cancel()
			}
			client, err := registry.New(registry.Config{
				BaseURL: "https://registry.example.com", Region: "test-region", SigningKey: registryTestKey,
				Timeout: 2 * time.Minute,
				HTTPClient: &http.Client{Transport: registryRoundTripper(func(r *http.Request) (*http.Response, error) {
					deadline, ok := r.Context().Deadline()
					if !ok || (parentDeadline && !deadline.Equal(parent)) || (!parentDeadline && deadline.After(time.Now().Add(2*time.Minute))) {
						t.Errorf("lookup deadline = %v, present=%v; parent=%v", deadline, ok, parent)
					}
					return nil, context.DeadlineExceeded
				})},
			})
			if err != nil {
				t.Fatal(err)
			}
			if _, err := client.Lookup(ctx, lookupFor(expected)); !errors.Is(err, identity.ErrUnavailable) {
				t.Fatalf("timed out Lookup() = %v; want unavailable", err)
			}
		})
	}
}
