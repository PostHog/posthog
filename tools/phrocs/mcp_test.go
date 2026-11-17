package main

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

func callMCPTool(t *testing.T, name string, args map[string]any) string {
	t.Helper()
	ctx := context.Background()
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := newMCPServer().Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatalf("server connect: %v", err)
	}
	t.Cleanup(func() { _ = serverSession.Close() })
	session, err := mcp.NewClient(&mcp.Implementation{Name: "test"}, nil).Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatalf("client connect: %v", err)
	}
	t.Cleanup(func() { _ = session.Close() })

	result, err := session.CallTool(ctx, &mcp.CallToolParams{Name: name, Arguments: args})
	if err != nil {
		t.Fatalf("call tool: %v", err)
	}
	if result.IsError || len(result.Content) != 1 {
		t.Fatalf("tool %s: error=%v content=%v", name, result.IsError, result.Content)
	}
	return result.Content[0].(*mcp.TextContent).Text
}

func TestMCPGetProcessLogs_cleansLinesFromPhrocs(t *testing.T) {
	var gotCmd map[string]any
	stubQuery(t, func(cmd map[string]any, _ time.Duration) (map[string]any, error) {
		gotCmd = cmd
		return map[string]any{
			"ok":       true,
			"lines":    []any{"\x1b[32mINFO\x1b[0m ready   ", "tick", "tick", "tick"},
			"buffered": 4,
		}, nil
	})

	text := callMCPTool(t, "get_process_logs", map[string]any{"process": "backend", "lines": 900})

	if gotCmd["cmd"] != "logs" || gotCmd["process"] != "backend" || gotCmd["lines"] != maxLogLines {
		t.Errorf("IPC request: got %v", gotCmd)
	}
	want := "backend: last 4 of 4 buffered lines from the current run. lines is capped at 500. Repeated lines are folded.\n\nINFO ready\ntick\n[repeated x3]"
	if text != want {
		t.Errorf("logs:\n got %q\nwant %q", text, want)
	}
}

func TestMCPGetProcessStatus_summarizesFailuresFirst(t *testing.T) {
	stubQuery(t, func(cmd map[string]any, _ time.Duration) (map[string]any, error) {
		if cmd["cmd"] == "logs" {
			return map[string]any{"ok": true, "lines": []any{"Traceback", "ValueError: bad config", ""}}, nil
		}
		return map[string]any{"ok": true, "processes": map[string]any{
			"web":    map[string]any{"status": "running", "ready": true, "has_ready_check": true, "pid": 10},
			"repl":   map[string]any{"status": "running", "ready": true, "has_ready_check": false, "pid": 11},
			"worker": map[string]any{"status": "crashed", "exit_code": 1},
			"setup":  map[string]any{"status": "done", "exit_code": 0},
		}}, nil
	})

	text := callMCPTool(t, "get_process_status", map[string]any{})

	want := strings.Join([]string{
		"4 processes: 1 crashed, 2 running, 1 done.",
		"worker: crashed, exit 1. Last output: ValueError: bad config",
		"repl: running, no ready check (pid 11)",
		"web: ready (pid 10)",
		"setup: done, exit 0",
	}, "\n")
	if text != want {
		t.Errorf("status:\n got %q\nwant %q", text, want)
	}
}

func TestMCPWaitReady_pollsUntilReady(t *testing.T) {
	calls := 0
	stubQuery(t, func(map[string]any, time.Duration) (map[string]any, error) {
		calls++
		ready := calls > 1
		status := "pending"
		if ready {
			status = "running"
		}
		return map[string]any{"ok": true, "status": status, "ready": ready, "has_ready_check": true, "pid": 10}, nil
	})

	text := callMCPTool(t, "wait_ready", map[string]any{"process": "web", "timeout_seconds": 5})

	if !strings.HasPrefix(text, "Ready after") || !strings.Contains(text, "web: ready (pid 10)") || calls != 2 {
		t.Errorf("wait_ready after %d polls: %q", calls, text)
	}
}

func TestMCPWaitReady_noProcessesReturnsAtOnce(t *testing.T) {
	stubQuery(t, func(map[string]any, time.Duration) (map[string]any, error) {
		return map[string]any{"ok": true, "processes": map[string]any{}}, nil
	})

	text := callMCPTool(t, "wait_ready", map[string]any{"timeout_seconds": 60})

	if text != "No processes are configured, so there is nothing to wait for." {
		t.Errorf("wait_ready with no processes: %q", text)
	}
}
