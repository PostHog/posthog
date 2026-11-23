package app

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

func TestRequestBudgetIsSharedAndBounded(t *testing.T) {
	now := time.Now()
	limits := newRequestLimits(2)
	limits.now = func() time.Time { return now }
	expires := now.Add(time.Minute)
	var accepted, reported atomic.Int32
	var requests sync.WaitGroup
	for range requestBurst * 2 {
		requests.Go(func() {
			allowed, report := limits.admit("relay-a", expires)
			if allowed {
				accepted.Add(1)
			}
			if report {
				reported.Add(1)
			}
		})
	}
	requests.Wait()
	if accepted.Load() != requestBurst || reported.Load() != 1 {
		t.Fatalf("accepted=%d reported=%d", accepted.Load(), reported.Load())
	}
	if allowed, report := limits.admit("relay-a", expires.Add(time.Hour)); allowed || report {
		t.Fatal("renewing the certificate reset the budget or audit interval")
	}
	if allowed, _ := limits.admit("relay-b", expires); !allowed {
		t.Fatal("one relay exhausted another relay's budget")
	}
	if allowed, _ := limits.admit("relay-c", expires); allowed {
		t.Fatal("a new relay evicted a live budget")
	}
	now = now.Add(time.Second)
	for range requestsPerSecond {
		if allowed, _ := limits.admit("relay-a", expires); !allowed {
			t.Fatal("budget did not refill")
		}
	}
	if allowed, report := limits.admit("relay-a", expires); allowed || report {
		t.Fatal("budget overfilled or repeated its audit event")
	}
	now = expires
	if allowed, _ := limits.admit("relay-c", now.Add(time.Minute)); !allowed {
		t.Fatal("expired budgets were not reclaimed")
	}
	if len(limits.entries) != 2 || limits.entries["relay-a"] == nil {
		t.Fatal("reclamation removed a renewed relay budget")
	}
}

func TestProxyRejectsExcessRequestsBeforeRegistryAndAudit(t *testing.T) {
	now := time.Now()
	peer := &x509.Certificate{RawSubjectPublicKeyInfo: []byte("synthetic-relay-key"), NotAfter: now.Add(time.Hour)}
	key := identity.KeySHA256(peer)
	limits := newRequestLimits(2)
	limits.now = func() time.Time { return now }
	for range requestBurst {
		limits.admit(key, peer.NotAfter)
	}
	var output bytes.Buffer
	audit, err := telemetry.NewAudit(&output, 2)
	if err != nil {
		t.Fatal(err)
	}
	defer audit.Close(context.Background())
	metrics := telemetry.NewMetrics()
	proxy := &Proxy{config: ProxyConfig{ServerConfig: ServerConfig{RequestTimeoutSeconds: 30}}, limits: limits, audit: audit, metrics: metrics}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.TLS = &tls.ConnectionState{VerifiedChains: [][]*x509.Certificate{{peer}}}
		proxy.ServeHTTP(w, r)
	}))
	defer server.Close()
	for i := range 64 {
		request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, server.URL+"/v1/probe", nil)
		if err != nil {
			t.Fatal(err)
		}
		request.Header.Set("Authorization", "Bearer synthetic-"+strconv.Itoa(i))
		request.Header.Set("X-Execution-ID", strconv.Itoa(i))
		response, err := server.Client().Do(request)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, response.Body)
		response.Body.Close()
		if response.StatusCode != http.StatusTooManyRequests || response.Header.Get("Retry-After") != "1" {
			t.Fatalf("status=%d; wanted 429 without contacting registry", response.StatusCode)
		}
	}
	if err := audit.Close(context.Background()); err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(&output)
	for _, phase := range []string{"admission", "completion"} {
		var event telemetry.Event
		if err := decoder.Decode(&event); err != nil {
			t.Fatal(err)
		}
		if event.RelayKeySHA256 != key || event.RequestID == "" || event.Outcome != "rate_limited" || event.Phase != phase {
			t.Fatalf("unexpected audit event: %+v", event)
		}
	}
	if err := decoder.Decode(new(telemetry.Event)); err != io.EOF {
		t.Fatal("rate-limit denials flooded the audit queue")
	}
	response := httptest.NewRecorder()
	metrics.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if !strings.Contains(response.Body.String(), `egress_requests_total{outcome="rate_limited"} 64`) {
		t.Fatal("rate-limit denials were not counted")
	}
}
