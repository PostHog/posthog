package mcp_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/mcp"
	"github.com/posthog/posthog/phrocs/internal/process"
)

func testServer(t *testing.T, names ...string) *mcp.Server {
	t.Helper()
	f := false
	procs := make(map[string]config.ProcConfig, len(names))
	for _, n := range names {
		procs[n] = config.ProcConfig{Shell: "true", Autostart: &f}
	}
	mgr := process.NewManager(&config.Config{
		Procs:      procs,
		Scrollback: 1000,
	})
	return mcp.NewServer(mgr)
}

func post(t *testing.T, srv *mcp.Server, method string, params any) map[string]any {
	t.Helper()
	body := map[string]any{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  method,
	}
	if params != nil {
		body["params"] = params
	}
	b, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	srv.ServeHTTP(rr, req)

	var resp map[string]any
	if err := json.Unmarshal(rr.Body.Bytes(), &resp); err != nil {
		t.Fatalf("unmarshal response: %v (body: %s)", err, rr.Body.String())
	}
	return resp
}

func TestMCP_initialize(t *testing.T) {
	srv := testServer(t)
	resp := post(t, srv, "initialize", nil)
	if resp["error"] != nil {
		t.Fatalf("initialize error: %v", resp["error"])
	}
	result, ok := resp["result"].(map[string]any)
	if !ok {
		t.Fatalf("expected result object, got %T", resp["result"])
	}
	if result["protocolVersion"] == nil {
		t.Error("missing protocolVersion in initialize result")
	}
}

func TestMCP_toolsList(t *testing.T) {
	srv := testServer(t)
	resp := post(t, srv, "tools/list", nil)
	result := resp["result"].(map[string]any)
	tools, ok := result["tools"].([]any)
	if !ok || len(tools) == 0 {
		t.Fatalf("expected non-empty tools list, got %v", result["tools"])
	}
	names := make(map[string]bool)
	for _, tool := range tools {
		m := tool.(map[string]any)
		names[m["name"].(string)] = true
	}
	for _, want := range []string{"get_process_status", "get_process_logs"} {
		if !names[want] {
			t.Errorf("missing tool %q", want)
		}
	}
}

func TestMCP_getProcessStatus_all(t *testing.T) {
	srv := testServer(t, "backend", "frontend")
	resp := post(t, srv, "tools/call", map[string]any{
		"name":      "get_process_status",
		"arguments": map[string]any{},
	})
	if resp["error"] != nil {
		t.Fatalf("tool call error: %v", resp["error"])
	}
	// Result is a text content block; parse the JSON text
	content := extractText(t, resp)
	var status map[string]any
	if err := json.Unmarshal([]byte(content), &status); err != nil {
		t.Fatalf("unmarshal status: %v", err)
	}
	for _, name := range []string{"backend", "frontend"} {
		if status[name] == nil {
			t.Errorf("missing status for %q", name)
		}
	}
}

func TestMCP_getProcessStatus_single(t *testing.T) {
	srv := testServer(t, "backend", "frontend")
	resp := post(t, srv, "tools/call", map[string]any{
		"name":      "get_process_status",
		"arguments": map[string]any{"process": "backend"},
	})
	content := extractText(t, resp)
	var status map[string]any
	json.Unmarshal([]byte(content), &status) //nolint:errcheck
	if status["backend"] == nil {
		t.Errorf("expected 'backend' key in status, got %v", status)
	}
}

func TestMCP_getProcessLogs(t *testing.T) {
	srv := testServer(t, "backend")
	resp := post(t, srv, "tools/call", map[string]any{
		"name":      "get_process_logs",
		"arguments": map[string]any{"process": "backend", "lines": 10},
	})
	if resp["error"] != nil {
		t.Fatalf("unexpected error: %v", resp["error"])
	}
	content := extractText(t, resp)
	var logs map[string]any
	json.Unmarshal([]byte(content), &logs) //nolint:errcheck
	if logs["process"] != "backend" {
		t.Errorf("expected process=backend, got %v", logs["process"])
	}
}

func TestMCP_getProcessStatus_mergesMonitorJSON(t *testing.T) {
	// Write a fake process-monitor JSON file for "backend".
	tmp := t.TempDir()
	// Temporarily redirect the monitor path by writing to /tmp directly.
	// We write to the real /tmp path and clean up after.
	monitorFile := "/tmp/posthog-backend.json"
	payload := map[string]any{
		"process":          "backend",
		"pid":              99999,        // should be overridden by phrocs in-memory value
		"status":           "running",    // should be overridden
		"mem_rss_mb":       123.4,
		"peak_mem_rss_mb":  200.0,
		"cpu_percent":      5.2,
		"startup_duration_s": 1.23,
	}
	_ = tmp // suppress unused warning
	b, _ := json.Marshal(payload)
	if err := os.WriteFile(monitorFile, b, 0o644); err != nil {
		t.Skipf("cannot write %s: %v", monitorFile, err)
	}
	t.Cleanup(func() { os.Remove(monitorFile) })

	srv := testServer(t, "backend")
	resp := post(t, srv, "tools/call", map[string]any{
		"name":      "get_process_status",
		"arguments": map[string]any{"process": "backend"},
	})
	content := extractText(t, resp)
	var outer map[string]any
	json.Unmarshal([]byte(content), &outer) //nolint:errcheck
	fields := outer["backend"].(map[string]any)

	// phrocs in-memory values override monitor file values
	if fields["pid"] == float64(99999) {
		t.Error("pid from monitor file should be overridden by phrocs value")
	}
	if fields["status"] == nil {
		t.Error("status should be present")
	}
	// Metrics from the monitor file should be merged in
	if fields["mem_rss_mb"] != 123.4 {
		t.Errorf("mem_rss_mb: want 123.4, got %v", fields["mem_rss_mb"])
	}
	if fields["startup_duration_s"] != 1.23 {
		t.Errorf("startup_duration_s: want 1.23, got %v", fields["startup_duration_s"])
	}
}

func TestMCP_unknownTool(t *testing.T) {
	srv := testServer(t)
	resp := post(t, srv, "tools/call", map[string]any{
		"name":      "does_not_exist",
		"arguments": map[string]any{},
	})
	if resp["error"] == nil {
		t.Error("expected error for unknown tool")
	}
}

func TestMCP_notification(t *testing.T) {
	srv := testServer(t)
	// Notifications have no id; server should return 202 with no body.
	body := map[string]any{"jsonrpc": "2.0", "method": "notifications/initialized"}
	b, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/mcp", bytes.NewReader(b))
	rr := httptest.NewRecorder()
	srv.ServeHTTP(rr, req)
	if rr.Code != http.StatusAccepted {
		t.Errorf("notification: want 202, got %d", rr.Code)
	}
}

// extractText pulls the text content from an MCP tool-call response.
func extractText(t *testing.T, resp map[string]any) string {
	t.Helper()
	result, ok := resp["result"].(map[string]any)
	if !ok {
		t.Fatalf("no result in response: %v", resp)
	}
	content, ok := result["content"].([]any)
	if !ok || len(content) == 0 {
		t.Fatalf("no content in result: %v", result)
	}
	block := content[0].(map[string]any)
	return block["text"].(string)
}
