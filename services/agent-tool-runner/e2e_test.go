// End-to-end test exercising the full main.run path:
//
//   - Real YAML config loaded from disk
//   - Real MCP fixture server (mark3labs/mcp-go) standing in for Grafana
//   - Mock PostHog ingress accepting heartbeats + serving an invocation
//   - Assertions on heartbeat catalog, leased invocation, and posted result
//
// This is the closest we can get to "in production" without leaving the
// test process. The lifecycle is: config → buildSources → Connect MCP →
// start project loop → enqueue invocation → assert result.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"

	"github.com/posthog/posthog/services/agent-tool-runner/protocol"
)

func TestE2E_FullStack(t *testing.T) {
	// 1. Stand up the upstream MCP server. It exposes one tool: `greet`,
	// which returns `hello <name>`.
	mcpSrv := server.NewMCPServer("fixture-grafana", "1")
	mcpSrv.AddTool(
		mcp.NewTool("greet",
			mcp.WithString("name", mcp.Required()),
		),
		func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
			return mcp.NewToolResultText("hello " + req.GetString("name", "world")), nil
		},
	)
	streamable := server.NewStreamableHTTPServer(mcpSrv)
	mcpHTTP := httptest.NewServer(streamable)
	defer mcpHTTP.Close()
	mcpEndpoint := mcpHTTP.URL + "/mcp"

	// 2. Stand up the mock PostHog ingress.
	ing := newE2EIngress()
	posthogHTTP := httptest.NewServer(ing)
	defer posthogHTTP.Close()

	// 3. Write a token file + config file on disk.
	tmp := t.TempDir()
	tokenPath := filepath.Join(tmp, "token")
	if err := os.WriteFile(tokenPath, []byte("phtr_test_secret"), 0o600); err != nil {
		t.Fatalf("write token: %v", err)
	}
	configYAML := fmt.Sprintf(`
projects:
  - project_id: 123
    endpoint: %s
    token_secret_ref: %s
    slug: grafana-prod
    expose:
      - grafana.greet
      - kubernetes.restart_deployment

tool_sources:
  - source: mcp
    name: grafana
    endpoint: %s

  - source: command
    name: kubernetes.restart_deployment
    description: restart a deployment by name
    args_schema:
      type: object
      required: [name]
      properties:
        name: { type: string }
    command: echo restarted=${args.name}
`, posthogHTTP.URL, tokenPath, mcpEndpoint)

	configPath := filepath.Join(tmp, "config.yaml")
	if err := os.WriteFile(configPath, []byte(configYAML), 0o600); err != nil {
		t.Fatalf("write config: %v", err)
	}

	// 4. Run main.run() in a goroutine. Cancel when assertions pass.
	// `127.0.0.1:0` binds an OS-assigned port so parallel tests don't
	// fight over :8080.
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	runDone := make(chan error, 1)
	go func() {
		runDone <- run(configPath, "127.0.0.1:0", logger)
	}()
	defer func() {
		// Send SIGINT-equivalent by terminating the process group is
		// overkill for a test — instead we send invocations + wait for
		// assertions, then send a SIGINT via the syscall in cleanup.
		// run() will exit naturally because the inner ctx is bound to
		// SIGINT. Since we can't deliver SIGINT cleanly to ourselves
		// here without affecting the whole test binary, we accept that
		// run() returns when the parent test cancels via the process
		// teardown.
	}()

	// Wait for at least one heartbeat — the runner is live.
	if !waitFor(t, 5*time.Second, func() bool { return ing.lastHeartbeat() != nil }) {
		t.Fatalf("runner never heartbeat — startup blocked. run err: %v", checkChan(runDone))
	}

	// 5. Verify the heartbeat catalog includes both expected tools.
	hb := ing.lastHeartbeat()
	gotNames := make(map[string]bool, len(hb.Tools))
	for _, tool := range hb.Tools {
		gotNames[tool.Name] = true
	}
	for _, expected := range []string{"grafana.greet", "kubernetes.restart_deployment"} {
		if !gotNames[expected] {
			t.Errorf("heartbeat catalog missing %q; got %+v", expected, gotNames)
		}
	}

	// 6. Drop an MCP-backed invocation on the queue.
	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-mcp",
		ToolName:          "grafana.greet",
		Args:              json.RawMessage(`{"name":"ben"}`),
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 5*time.Second, func() bool { return ing.resultsFor("inv-mcp") != nil }) {
		t.Fatalf("MCP invocation never returned a result. run err: %v", checkChan(runDone))
	}
	res := ing.resultsFor("inv-mcp")
	if res.Status != "done" {
		t.Errorf("MCP invocation failed: status=%s err=%s", res.Status, res.Error)
	}
	if !strings.Contains(string(res.Result), "hello ben") {
		t.Errorf("expected upstream response to contain 'hello ben'; got %s", res.Result)
	}

	// 7. Drop a command-backed invocation on the queue.
	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-cmd",
		ToolName:          "kubernetes.restart_deployment",
		Args:              json.RawMessage(`{"name":"web"}`),
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 5*time.Second, func() bool { return ing.resultsFor("inv-cmd") != nil }) {
		t.Fatalf("command invocation never returned a result. run err: %v", checkChan(runDone))
	}
	res = ing.resultsFor("inv-cmd")
	if res.Status != "done" {
		t.Errorf("command invocation failed: status=%s err=%s", res.Status, res.Error)
	}
	// The command's stdout was `restarted=web\n`; the source encodes it
	// as a JSON string.
	var stdout string
	if err := json.Unmarshal(res.Result, &stdout); err != nil {
		t.Fatalf("decode result: %v", err)
	}
	if strings.TrimSpace(stdout) != "restarted=web" {
		t.Errorf("expected `restarted=web`, got %q", stdout)
	}

	// 8. Drop an invocation whose args fail JSON Schema validation. The
	// runner should report it as `failed`, not crash.
	ing.enqueue(&protocol.LeasedInvocation{
		ID:                "inv-bad-args",
		ToolName:          "kubernetes.restart_deployment",
		Args:              json.RawMessage(`{}`), // missing required `name`
		LeaseExpiresAtISO: time.Now().Add(30 * time.Second).Format(time.RFC3339Nano),
	})

	if !waitFor(t, 5*time.Second, func() bool { return ing.resultsFor("inv-bad-args") != nil }) {
		t.Fatal("bad-args invocation never returned a result")
	}
	res = ing.resultsFor("inv-bad-args")
	if res.Status != "failed" || !strings.Contains(res.Error, "validation failed") {
		t.Errorf("expected validation failure, got %+v", res)
	}

	// run() will eventually return when the test process exits. We don't
	// signal it here — it doesn't matter for assertions, and SIGINT to
	// the test binary would kill the test runner.
}

func checkChan(c chan error) error {
	select {
	case err := <-c:
		return err
	default:
		return nil
	}
}

// e2eIngress is a fuller mock than the runner-package one — it tracks
// every heartbeat (not just the latest) and exposes invocations + results
// for assertions.
type e2eIngress struct {
	mu sync.Mutex

	heartbeats []protocol.HeartbeatRequest
	queue      []*protocol.LeasedInvocation
	results    map[string]protocol.ResultRequest
}

func newE2EIngress() *e2eIngress {
	return &e2eIngress{results: map[string]protocol.ResultRequest{}}
}

func (e *e2eIngress) enqueue(inv *protocol.LeasedInvocation) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.queue = append(e.queue, inv)
}

func (e *e2eIngress) lastHeartbeat() *protocol.HeartbeatRequest {
	e.mu.Lock()
	defer e.mu.Unlock()
	if len(e.heartbeats) == 0 {
		return nil
	}
	hb := e.heartbeats[len(e.heartbeats)-1]
	return &hb
}

func (e *e2eIngress) resultsFor(id string) *protocol.ResultRequest {
	e.mu.Lock()
	defer e.mu.Unlock()
	r, ok := e.results[id]
	if !ok {
		return nil
	}
	return &r
}

func (e *e2eIngress) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if !strings.HasPrefix(r.Header.Get("Authorization"), "Bearer phtr_test_secret") {
		http.Error(w, "bad token", http.StatusUnauthorized)
		return
	}
	switch {
	case r.URL.Path == "/runners/heartbeat":
		var hb protocol.HeartbeatRequest
		_ = json.NewDecoder(r.Body).Decode(&hb)
		e.mu.Lock()
		e.heartbeats = append(e.heartbeats, hb)
		e.mu.Unlock()
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("{}"))
	case r.URL.Path == "/runners/poll":
		e.mu.Lock()
		var inv *protocol.LeasedInvocation
		if len(e.queue) > 0 {
			inv = e.queue[0]
			e.queue = e.queue[1:]
		}
		e.mu.Unlock()
		if inv == nil {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		json.NewEncoder(w).Encode(protocol.PollResponse{Invocation: inv})
	case strings.HasSuffix(r.URL.Path, "/result"):
		id := strings.TrimSuffix(strings.TrimPrefix(r.URL.Path, "/runners/invocations/"), "/result")
		var body protocol.ResultRequest
		_ = json.NewDecoder(r.Body).Decode(&body)
		e.mu.Lock()
		e.results[id] = body
		e.mu.Unlock()
		w.WriteHeader(http.StatusOK)
	case strings.HasSuffix(r.URL.Path, "/extend_lease"):
		newLease := time.Now().Add(60 * time.Second).Format(time.RFC3339Nano)
		json.NewEncoder(w).Encode(protocol.ExtendLeaseResponse{LeaseExpiresAtISO: newLease})
	default:
		http.NotFound(w, r)
	}
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
