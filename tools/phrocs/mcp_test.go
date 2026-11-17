package main

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

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

	ctx := context.Background()
	server := newMCPServer()
	serverTransport, clientTransport := mcp.NewInMemoryTransports()
	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatalf("server connect: %v", err)
	}
	t.Cleanup(func() { _ = serverSession.Close() })
	client := mcp.NewClient(&mcp.Implementation{Name: "test"}, nil)
	session, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatalf("client connect: %v", err)
	}
	t.Cleanup(func() { _ = session.Close() })

	result, err := session.CallTool(ctx, &mcp.CallToolParams{
		Name:      "get_process_logs",
		Arguments: map[string]any{"process": "backend"},
	})
	if err != nil {
		t.Fatalf("call tool: %v", err)
	}
	if result.IsError {
		t.Fatalf("tool error: %v", result.Content)
	}

	if gotCmd["cmd"] != "logs" || gotCmd["process"] != "backend" || gotCmd["lines"] != defaultLogLines {
		t.Errorf("IPC request: got %v", gotCmd)
	}
	raw, _ := json.Marshal(result.StructuredContent)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	if want := "INFO ready\ntick\n[repeated x3]"; out["logs"] != want {
		t.Errorf("logs: got %q, want %q", out["logs"], want)
	}
}
