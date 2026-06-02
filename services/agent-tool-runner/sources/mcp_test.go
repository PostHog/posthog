package sources

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

func TestMCPSource_ConnectListsAndPrefixesTools(t *testing.T) {
	srv, addr := startTestMCPServer(t, func(s *server.MCPServer) {
		s.AddTool(
			mcp.NewTool("echo",
				mcp.WithDescription("echoes its input"),
				mcp.WithString("text", mcp.Required()),
			),
			func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				text := req.GetString("text", "")
				return mcp.NewToolResultText(text), nil
			},
		)
	})
	defer srv.Close()

	src, err := NewMCPSource("upstream", addr)
	if err != nil {
		t.Fatalf("NewMCPSource: %v", err)
	}
	defer src.Close()

	if err := src.Connect(context.Background()); err != nil {
		t.Fatalf("Connect: %v", err)
	}

	tools := src.Tools()
	if len(tools) != 1 {
		t.Fatalf("expected 1 tool, got %d (%+v)", len(tools), tools)
	}
	if tools[0].Name != "upstream.echo" {
		t.Errorf("tool name = %q; want upstream.echo (source-prefixed)", tools[0].Name)
	}
	if tools[0].Description != "echoes its input" {
		t.Errorf("description not forwarded: %q", tools[0].Description)
	}
	if len(tools[0].InputSchema) == 0 {
		t.Errorf("input schema empty")
	}
}

func TestMCPSource_CallForwardsToUpstream(t *testing.T) {
	srv, addr := startTestMCPServer(t, func(s *server.MCPServer) {
		s.AddTool(
			mcp.NewTool("greet",
				mcp.WithString("name", mcp.Required()),
			),
			func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				name := req.GetString("name", "world")
				return mcp.NewToolResultText("hello " + name), nil
			},
		)
	})
	defer srv.Close()

	src, err := NewMCPSource("upstream", addr)
	if err != nil {
		t.Fatalf("NewMCPSource: %v", err)
	}
	defer src.Close()
	if err := src.Connect(context.Background()); err != nil {
		t.Fatalf("Connect: %v", err)
	}

	out, err := src.Call(context.Background(), "upstream.greet", json.RawMessage(`{"name":"ben"}`))
	if err != nil {
		t.Fatalf("Call: %v", err)
	}
	// The MCP CallToolResult is passed through as JSON. We don't assert
	// the precise shape (it belongs to the library), but the response
	// must contain the upstream's "hello ben" text somewhere.
	if !strings.Contains(string(out), "hello ben") {
		t.Errorf("response should contain upstream text; got %s", out)
	}
}

func TestMCPSource_CallRejectsWrongPrefix(t *testing.T) {
	srv, addr := startTestMCPServer(t, func(s *server.MCPServer) {
		s.AddTool(
			mcp.NewTool("ok"),
			func(ctx context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
				return mcp.NewToolResultText("ok"), nil
			},
		)
	})
	defer srv.Close()

	src, _ := NewMCPSource("upstream", addr)
	defer src.Close()
	src.Connect(context.Background())

	_, err := src.Call(context.Background(), "wrong.ok", nil)
	if err == nil || !strings.Contains(err.Error(), "not prefixed with source") {
		t.Errorf("expected prefix-mismatch error, got %v", err)
	}
}

func TestMCPSource_CallWithoutConnect(t *testing.T) {
	src, _ := NewMCPSource("upstream", "http://example/")
	_, err := src.Call(context.Background(), "upstream.x", nil)
	if err == nil || !strings.Contains(err.Error(), "not connected") {
		t.Errorf("expected not-connected error, got %v", err)
	}
}

func TestMCPSource_ConnectFailsToBadURL(t *testing.T) {
	src, err := NewMCPSource("upstream", "http://127.0.0.1:1") // closed port
	if err != nil {
		t.Fatalf("NewMCPSource: %v", err)
	}
	if err := src.Connect(context.Background()); err == nil {
		t.Errorf("expected Connect to fail against a closed port")
	}
}

func TestMCPSource_Tools_BeforeConnect(t *testing.T) {
	src, _ := NewMCPSource("upstream", "http://example/")
	if got := src.Tools(); len(got) != 0 {
		t.Errorf("Tools() before Connect should be empty; got %+v", got)
	}
}

// startTestMCPServer spins up an MCP server on an httptest.Server and
// returns the bound URL (with the MCP endpoint path appended). The
// caller calls Close() to tear it down.
func startTestMCPServer(t *testing.T, configure func(*server.MCPServer)) (*httptest.Server, string) {
	t.Helper()
	mcpServer := server.NewMCPServer("test-runner-fixture", "1")
	configure(mcpServer)
	streamable := server.NewStreamableHTTPServer(mcpServer)
	httpSrv := httptest.NewServer(streamable)
	return httpSrv, httpSrv.URL + "/mcp"
}
