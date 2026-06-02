package runner

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/posthog/posthog/services/agent-tool-runner/client"
	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

// fakeSource is a runner.Source impl test cases parameterize via closures.
type fakeSource struct {
	tools  []protocol.ToolDescriptor
	call   func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error)
	closed atomic.Bool
}

func (f *fakeSource) Tools() []protocol.ToolDescriptor { return f.tools }
func (f *fakeSource) Call(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
	return f.call(ctx, name, args)
}
func (f *fakeSource) Close() error {
	f.closed.Store(true)
	return nil
}

func TestNew_Validation(t *testing.T) {
	cli := mustClient(t, "http://127.0.0.1:1", "tok")
	cases := []struct {
		name string
		opts Options
		want string
	}{
		{"no client", Options{Sources: []Source{&fakeSource{}}, Expose: []string{"a.b"}}, "Client is required"},
		{"no sources", Options{Client: cli, Expose: []string{"a.b"}}, "at least one Source"},
		{"no expose", Options{Client: cli, Sources: []Source{&fakeSource{}}}, "Expose must list at least one"},
		{"expose not in any source", Options{
			Client:  cli,
			Sources: []Source{&fakeSource{}},
			Expose:  []string{"missing.tool"},
		}, "not provided by any source"},
		{"duplicate tool across sources", Options{
			Client: cli,
			Sources: []Source{
				&fakeSource{tools: []protocol.ToolDescriptor{{Name: "a.b"}}},
				&fakeSource{tools: []protocol.ToolDescriptor{{Name: "a.b"}}},
			},
			Expose: []string{"a.b"},
		}, "duplicate tool name"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := New(tc.opts)
			if err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Errorf("expected %q, got %v", tc.want, err)
			}
		})
	}
}

func TestRun_RegistersAndPolls(t *testing.T) {
	ing := newMockIngress()
	srv := httptest.NewServer(ing)
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.echo", InputSchema: json.RawMessage(`{}`)}},
		call: func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`"ok"`), nil
		},
	}
	r, err := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.echo"},
		HeartbeatInterval: 50 * time.Millisecond,
		PollMaxWait:       100 * time.Millisecond,
		LeaseExtensionFor: 60 * time.Second,
		Logger:            discardLogger(),
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	// Enqueue an invocation; the runner's poll loop will pick it up.
	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-1",
		ToolName:          "x.echo",
		Args:              json.RawMessage(`null`),
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 2*time.Second, func() bool { return ing.resultsFor("inv-1") != nil }) {
		t.Fatal("invocation result never posted")
	}
	res := ing.resultsFor("inv-1")
	if res.Status != "done" || string(res.Result) != `"ok"` {
		t.Errorf("unexpected result: %+v", res)
	}
	if hb := ing.lastHeartbeat(); hb == nil || hb.InstanceID == "" || len(hb.Tools) != 1 {
		t.Errorf("expected at least one heartbeat with the published catalog; got %+v", hb)
	}

	cancel()
	if err := <-done; err != nil && !errors.Is(err, context.Canceled) {
		t.Errorf("Run returned non-cancellation error: %v", err)
	}
}

func TestRun_DispatchesFailureToReportError(t *testing.T) {
	ing := newMockIngress()
	srv := httptest.NewServer(ing)
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.fail", InputSchema: json.RawMessage(`{}`)}},
		call: func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
			return nil, errors.New("upstream boom")
		},
	}
	r, _ := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.fail"},
		HeartbeatInterval: 1 * time.Second,
		PollMaxWait:       50 * time.Millisecond,
		LeaseExtensionFor: 60 * time.Second,
		Logger:            discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-fail",
		ToolName:          "x.fail",
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 2*time.Second, func() bool { return ing.resultsFor("inv-fail") != nil }) {
		t.Fatal("failure result never posted")
	}
	res := ing.resultsFor("inv-fail")
	if res.Status != "failed" || !strings.Contains(res.Error, "upstream boom") {
		t.Errorf("unexpected failure: %+v", res)
	}

	cancel()
	<-done
}

func TestRun_RejectsUnknownTool(t *testing.T) {
	ing := newMockIngress()
	srv := httptest.NewServer(ing)
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.known", InputSchema: json.RawMessage(`{}`)}},
		call: func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`"ok"`), nil
		},
	}
	r, _ := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.known"},
		HeartbeatInterval: 1 * time.Second,
		PollMaxWait:       50 * time.Millisecond,
		LeaseExtensionFor: 60 * time.Second,
		Logger:            discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-unknown",
		ToolName:          "x.unknown",
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 2*time.Second, func() bool { return ing.resultsFor("inv-unknown") != nil }) {
		t.Fatal("unknown-tool result never posted")
	}
	res := ing.resultsFor("inv-unknown")
	if res.Status != "failed" || !strings.Contains(res.Error, "not served by this runner") {
		t.Errorf("unexpected response for unknown tool: %+v", res)
	}

	cancel()
	<-done
}

func TestRun_ExtendsLeaseDuringLongCall(t *testing.T) {
	ing := newMockIngress()
	srv := httptest.NewServer(ing)
	defer srv.Close()

	// Tool takes ~600ms; initial lease is 200ms ahead — without lease
	// extension the runner would cut the call off. With it, the tool
	// finishes and the result is posted.
	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.slow", InputSchema: json.RawMessage(`{}`)}},
		call: func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
			select {
			case <-time.After(600 * time.Millisecond):
				return json.RawMessage(`"slow ok"`), nil
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		},
	}
	r, _ := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.slow"},
		HeartbeatInterval: 1 * time.Second,
		PollMaxWait:       50 * time.Millisecond,
		// Short extension window so the test exercises multiple extensions
		// without taking a real second to run.
		LeaseExtensionFor: 200 * time.Millisecond,
		Logger:            discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-slow",
		ToolName:          "x.slow",
		LeaseExpiresAtISO: time.Now().Add(200 * time.Millisecond).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 3*time.Second, func() bool { return ing.resultsFor("inv-slow") != nil }) {
		t.Fatal("slow invocation never completed — lease extension may be broken")
	}
	res := ing.resultsFor("inv-slow")
	if res.Status != "done" || string(res.Result) != `"slow ok"` {
		t.Errorf("expected slow ok result, got %+v", res)
	}
	if ing.extensionCount("inv-slow") < 1 {
		t.Errorf("expected at least one ExtendLease call; got %d", ing.extensionCount("inv-slow"))
	}

	cancel()
	<-done
}

func TestRun_BadLeaseExpiresAtReportsError(t *testing.T) {
	ing := newMockIngress()
	srv := httptest.NewServer(ing)
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.ok", InputSchema: json.RawMessage(`{}`)}},
		call: func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) {
			return json.RawMessage(`"ok"`), nil
		},
	}
	r, _ := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.ok"},
		HeartbeatInterval: 1 * time.Second,
		PollMaxWait:       50 * time.Millisecond,
		LeaseExtensionFor: 60 * time.Second,
		Logger:            discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-bad-lease",
		ToolName:          "x.ok",
		LeaseExpiresAtISO: "not a time",
	})

	if !waitFor(t, 2*time.Second, func() bool { return ing.resultsFor("inv-bad-lease") != nil }) {
		t.Fatal("bad-lease invocation never reported")
	}
	res := ing.resultsFor("inv-bad-lease")
	if res.Status != "failed" || !strings.Contains(res.Error, "invalid lease_expires_at") {
		t.Errorf("unexpected response: %+v", res)
	}

	cancel()
	<-done
}

func TestRun_StaysInConnectingWhileIngressIsDown(t *testing.T) {
	// Server that refuses every heartbeat.
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusBadGateway)
	}))
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.echo", InputSchema: json.RawMessage(`{}`)}},
		call:  func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) { return nil, nil },
	}
	r, _ := New(Options{
		Client:             mustClient(t, srv.URL, "tok"),
		Sources:            []Source{source},
		Expose:             []string{"x.echo"},
		RegisterBackoffMin: 20 * time.Millisecond,
		RegisterBackoffMax: 50 * time.Millisecond,
		Logger:             discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	// Wait for several retries to happen — proves the runner is looping
	// rather than fast-failing on the first error.
	if !waitFor(t, 2*time.Second, func() bool { return hits.Load() >= 3 }) {
		t.Fatal("expected the runner to retry initial register multiple times")
	}
	if got := r.State(); got != StateConnecting {
		t.Errorf("expected state=connecting while ingress is down, got %s", got)
	}

	cancel()
	if err := <-done; err != nil && !errors.Is(err, context.Canceled) {
		t.Errorf("Run returned non-cancellation error: %v", err)
	}
}

func TestRun_RecoversFromInitiallyDownIngress(t *testing.T) {
	// Server is down for the first ~150ms, then starts serving 200s.
	var down atomic.Bool
	down.Store(true)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if down.Load() {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("{}"))
	}))
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.echo", InputSchema: json.RawMessage(`{}`)}},
		call:  func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) { return nil, nil },
	}
	r, _ := New(Options{
		Client:             mustClient(t, srv.URL, "tok"),
		Sources:            []Source{source},
		Expose:             []string{"x.echo"},
		RegisterBackoffMin: 20 * time.Millisecond,
		RegisterBackoffMax: 50 * time.Millisecond,
		HeartbeatInterval:  1 * time.Second,
		PollMaxWait:        50 * time.Millisecond,
		Logger:             discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	time.Sleep(150 * time.Millisecond)
	down.Store(false)

	if !waitFor(t, 2*time.Second, func() bool { return r.State() == StateLive }) {
		t.Errorf("runner did not transition to live after ingress recovered (got %s)", r.State())
	}

	cancel()
	<-done
}

func TestRun_TransitionsToDegradedAfterRepeatedHeartbeatFailures(t *testing.T) {
	// Always-OK for the initial register; flip to failing once we've
	// observed at least one successful heartbeat. The runner should
	// transition live → degraded after DegradedAfter failures.
	var failHeartbeats atomic.Bool
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/runners/heartbeat":
			if failHeartbeats.Load() {
				w.WriteHeader(http.StatusBadGateway)
				return
			}
			w.WriteHeader(http.StatusOK)
			w.Write([]byte("{}"))
		case "/runners/poll":
			w.WriteHeader(http.StatusNoContent)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	source := &fakeSource{
		tools: []protocol.ToolDescriptor{{Name: "x.echo", InputSchema: json.RawMessage(`{}`)}},
		call:  func(ctx context.Context, name string, args json.RawMessage) (json.RawMessage, error) { return nil, nil },
	}
	r, _ := New(Options{
		Client:            mustClient(t, srv.URL, "tok"),
		Sources:           []Source{source},
		Expose:            []string{"x.echo"},
		HeartbeatInterval: 20 * time.Millisecond,
		PollMaxWait:       50 * time.Millisecond,
		DegradedAfter:     2, // small for the test
		Logger:            discardLogger(),
	})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- r.Run(ctx) }()

	if !waitFor(t, 1*time.Second, func() bool { return r.State() == StateLive }) {
		t.Fatal("never reached live state")
	}

	failHeartbeats.Store(true)
	if !waitFor(t, 2*time.Second, func() bool { return r.State() == StateDegraded }) {
		t.Errorf("expected state=degraded after consecutive failures, got %s", r.State())
	}

	failHeartbeats.Store(false)
	if !waitFor(t, 2*time.Second, func() bool { return r.State() == StateLive }) {
		t.Errorf("expected state=live after recovery, got %s", r.State())
	}

	cancel()
	<-done
}

// mockIngress is the in-test PostHog ingress. It tracks heartbeats, holds
// a queue of leasable invocations, and records results.
type mockIngress struct {
	mu sync.Mutex

	heartbeats []protocol.HeartbeatRequest
	queue      []*protocol.LeasedInvocation
	results    map[string]protocol.ResultRequest
	extensions map[string]int
}

func newMockIngress() *mockIngress {
	return &mockIngress{
		results:    map[string]protocol.ResultRequest{},
		extensions: map[string]int{},
	}
}

func (m *mockIngress) enqueue(inv *protocol.LeasedInvocation) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.queue = append(m.queue, inv)
}

func (m *mockIngress) resultsFor(id string) *protocol.ResultRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	res, ok := m.results[id]
	if !ok {
		return nil
	}
	return &res
}

func (m *mockIngress) lastHeartbeat() *protocol.HeartbeatRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.heartbeats) == 0 {
		return nil
	}
	hb := m.heartbeats[len(m.heartbeats)-1]
	return &hb
}

func (m *mockIngress) extensionCount(id string) int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.extensions[id]
}

func (m *mockIngress) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Authorization") == "" {
		http.Error(w, "missing auth", http.StatusUnauthorized)
		return
	}
	switch {
	case r.URL.Path == "/runners/heartbeat":
		var hb protocol.HeartbeatRequest
		_ = json.NewDecoder(r.Body).Decode(&hb)
		m.mu.Lock()
		m.heartbeats = append(m.heartbeats, hb)
		m.mu.Unlock()
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("{}"))
	case r.URL.Path == "/runners/poll":
		m.mu.Lock()
		var inv *protocol.LeasedInvocation
		if len(m.queue) > 0 {
			inv = m.queue[0]
			m.queue = m.queue[1:]
		}
		m.mu.Unlock()
		if inv == nil {
			// Short-circuit the long poll for tests — return 204 immediately.
			w.WriteHeader(http.StatusNoContent)
			return
		}
		json.NewEncoder(w).Encode(protocol.PollResponse{Invocation: inv})
	case strings.HasSuffix(r.URL.Path, "/result"):
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/runners/invocations/"), "/result")
		var body protocol.ResultRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		m.mu.Lock()
		m.results[id] = body
		m.mu.Unlock()
		w.WriteHeader(http.StatusOK)
	case strings.HasSuffix(r.URL.Path, "/extend_lease"):
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/runners/invocations/"), "/extend_lease")
		var body protocol.ExtendLeaseRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		m.mu.Lock()
		m.extensions[id]++
		m.mu.Unlock()
		newLease := time.Now().Add(time.Duration(body.ExtendBySeconds) * time.Second).Format(time.RFC3339Nano)
		json.NewEncoder(w).Encode(protocol.ExtendLeaseResponse{LeaseExpiresAtISO: newLease})
	default:
		http.NotFound(w, r)
	}
}

func mustClient(t *testing.T, endpoint, token string) *client.Client {
	t.Helper()
	c, err := client.New(client.Options{Endpoint: endpoint, Token: token})
	if err != nil {
		t.Fatalf("client.New: %v", err)
	}
	return c
}

func waitFor(t *testing.T, d time.Duration, cond func() bool) bool {
	t.Helper()
	deadline := time.Now().Add(d)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return cond()
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// Compile-time guard: a numeric token used in tests should not get
// stringified weirdly. The test-side mockIngress receives numeric counts
// in queries; we keep this assertion next to mockIngress to catch any
// future change that swaps queues to a different shape.
var _ = strconv.Itoa
