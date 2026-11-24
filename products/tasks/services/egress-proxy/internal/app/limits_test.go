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
	"net/http/httptrace"
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
	for _, tc := range []struct {
		name          string
		http2         bool
		contentLength int64
	}{
		{"HTTP1 bodyless", false, 0},
		{"HTTP1 declared body", false, 1},
		{"HTTP1 streaming body", false, -1},
		{"HTTP2 bodyless", true, 0},
		{"HTTP2 declared body", true, 1},
		{"HTTP2 streaming body", true, -1},
	} {
		t.Run(tc.name, func(t *testing.T) {
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
			holdContext, release := context.WithCancel(t.Context())
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/hold" {
					w.WriteHeader(http.StatusOK)
					_ = http.NewResponseController(w).Flush()
					select {
					case <-holdContext.Done():
						_, _ = io.WriteString(w, "complete")
					case <-r.Context().Done():
					}
					return
				}
				r.TLS = &tls.ConnectionState{VerifiedChains: [][]*x509.Certificate{{peer}}}
				proxy.ServeHTTP(w, r)
			}))
			server.EnableHTTP2 = tc.http2
			server.StartTLS()
			defer server.Close()
			defer release()
			client := server.Client()
			client.Timeout = 5 * time.Second
			var held *http.Response
			if tc.http2 {
				held, err = client.Get(server.URL + "/hold")
				if err != nil {
					t.Fatal(err)
				}
				defer held.Body.Close()
			}
			requests := 64
			if tc.contentLength != 0 {
				requests = 2
			}
			for i := range requests {
				reused := false
				ctx := httptrace.WithClientTrace(t.Context(), &httptrace.ClientTrace{
					GotConn: func(info httptrace.GotConnInfo) { reused = info.Reused },
				})
				var body io.Reader
				if tc.contentLength != 0 {
					reader, writer := io.Pipe()
					defer reader.Close()
					defer writer.Close()
					body = reader
				}
				request, err := http.NewRequestWithContext(ctx, http.MethodGet, server.URL+"/v1/probe", body)
				if err != nil {
					t.Fatal(err)
				}
				request.ContentLength = tc.contentLength
				request.Header.Set("Authorization", "Bearer synthetic-"+strconv.Itoa(i))
				request.Header.Set("X-Execution-ID", strconv.Itoa(i))
				response, err := client.Do(request)
				if err != nil {
					t.Fatal(err)
				}
				_, readErr := io.Copy(io.Discard, response.Body)
				response.Body.Close()
				if readErr != nil {
					t.Fatal(readErr)
				}
				if response.StatusCode != http.StatusTooManyRequests || response.Header.Get("Retry-After") != "1" {
					t.Fatalf("status=%d; wanted 429 without contacting registry", response.StatusCode)
				}
				if (response.ProtoMajor == 2) != tc.http2 {
					t.Fatalf("unexpected protocol: %s", response.Proto)
				}
				if want := tc.http2 || i > 0 && tc.contentLength == 0; reused != want {
					t.Fatalf("request %d: connection reused=%t, want %t", i, reused, want)
				}
			}
			if held != nil {
				release()
				body, err := io.ReadAll(held.Body)
				if err != nil || string(body) != "complete" {
					t.Fatalf("concurrent stream interrupted: body=%q error=%v", body, err)
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
			if !strings.Contains(response.Body.String(), `egress_requests_total{outcome="rate_limited"} `+strconv.Itoa(requests)) {
				t.Fatal("rate-limit denials were not counted")
			}
		})
	}
}
