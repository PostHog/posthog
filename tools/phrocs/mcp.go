package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/charmbracelet/x/ansi"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Longer than a stop's grace period, which toggle-proc waits out.
const mcpQueryTimeout = 10 * time.Second

const (
	defaultLogLines = 100
	maxLogLines     = 500
)

type statusInput struct {
	Process string `json:"process,omitempty" jsonschema:"Process name, for example backend or frontend. Leave empty for all processes."`
}

type logsInput struct {
	Process string `json:"process" jsonschema:"Process name, for example backend, frontend or celery-worker."`
	Lines   int    `json:"lines,omitempty" jsonschema:"Number of recent lines to return. Default 100, max 500."`
	Grep    string `json:"grep,omitempty" jsonschema:"Optional regex. Only matching lines are returned, searched across the whole buffer."`
}

type sendKeysInput struct {
	Process string `json:"process" jsonschema:"Process name."`
	Keys    string `json:"keys" jsonschema:"Text to send. Include a newline for enter. A ctrl+c is the character U+0003."`
}

type processInput struct {
	Process string `json:"process" jsonschema:"Process name."`
}

func askPhrocs(cmd map[string]any) (map[string]any, error) {
	resp, err := queryDetached(cmd, mcpQueryTimeout)
	if err != nil {
		if isTimeout(err) {
			return nil, fmt.Errorf("phrocs did not answer within %s", mcpQueryTimeout)
		}
		return nil, errors.New("phrocs is not running. Start the dev environment with: ./bin/start")
	}
	if resp["ok"] != true {
		if msg, ok := resp["error"].(string); ok && msg != "" {
			return nil, errors.New(msg)
		}
		return nil, errors.New("phrocs returned an error without a message")
	}
	delete(resp, "ok")
	return resp, nil
}

// cleanLogLines drops ANSI escapes, padding and repeats, which cost MCP clients tokens.
func cleanLogLines(lines []string) []string {
	cleaned := make([]string, len(lines))
	for i, line := range lines {
		cleaned[i] = strings.TrimRight(ansi.Strip(line), " \t")
	}
	var out []string
	for i := 0; i < len(cleaned); {
		j := i + 1
		for j < len(cleaned) && cleaned[j] == cleaned[i] {
			j++
		}
		out = append(out, cleaned[i])
		if j-i > 1 {
			out = append(out, fmt.Sprintf("[repeated x%d]", j-i))
		}
		i = j
	}
	return out
}

func processCommand(cmd, process string, extra map[string]any) (*mcp.CallToolResult, any, error) {
	req := map[string]any{"cmd": cmd, "process": process}
	for k, v := range extra {
		req[k] = v
	}
	if _, err := askPhrocs(req); err != nil {
		return nil, nil, err
	}
	return nil, map[string]any{"process": process, "ok": true}, nil
}

func getProcessStatus(_ context.Context, _ *mcp.CallToolRequest, in statusInput) (*mcp.CallToolResult, any, error) {
	if in.Process != "" {
		resp, err := askPhrocs(map[string]any{"cmd": "status", "process": in.Process})
		if err != nil {
			return nil, nil, err
		}
		return nil, map[string]any{in.Process: resp}, nil
	}
	resp, err := askPhrocs(map[string]any{"cmd": "status_all"})
	if err != nil {
		return nil, nil, err
	}
	return nil, resp["processes"], nil
}

func getProcessLogs(_ context.Context, _ *mcp.CallToolRequest, in logsInput) (*mcp.CallToolResult, any, error) {
	lines := in.Lines
	if lines <= 0 {
		lines = defaultLogLines
	}
	lines = min(lines, maxLogLines)
	resp, err := askPhrocs(map[string]any{"cmd": "logs", "process": in.Process, "lines": lines, "grep": in.Grep})
	if err != nil {
		return nil, nil, err
	}

	var raw []string
	if items, ok := resp["lines"].([]any); ok {
		for _, item := range items {
			if s, ok := item.(string); ok {
				raw = append(raw, s)
			}
		}
	}
	out := map[string]any{
		"process":        in.Process,
		"returned_lines": len(raw),
		"logs":           strings.Join(cleanLogLines(raw), "\n"),
		"buffered":       resp["buffered"],
	}
	if in.Grep != "" {
		out["grep"] = in.Grep
		out["total_matched"] = resp["total_matched"]
	}
	return nil, out, nil
}

func sendKeys(_ context.Context, _ *mcp.CallToolRequest, in sendKeysInput) (*mcp.CallToolResult, any, error) {
	return processCommand("send-keys", in.Process, map[string]any{"keys": in.Keys})
}

func toggleProcess(_ context.Context, _ *mcp.CallToolRequest, in processInput) (*mcp.CallToolResult, any, error) {
	return processCommand("toggle-proc", in.Process, nil)
}

func restartProcess(_ context.Context, _ *mcp.CallToolRequest, in processInput) (*mcp.CallToolResult, any, error) {
	return processCommand("restart", in.Process, nil)
}

func newMCPServer() *mcp.Server {
	server := mcp.NewServer(
		&mcp.Implementation{Name: "phrocs", Version: Version},
		&mcp.ServerOptions{Instructions: "Tools for inspecting the local PostHog dev environment. " +
			"Start the dev environment with `./bin/start` before using these tools."},
	)
	mcp.AddTool(server, &mcp.Tool{
		Name: "get_process_status",
		Description: "Get the status of one or all dev environment processes: pid, status, readiness, exit code, " +
			"startup duration, and resource metrics (mem_rss_mb, cpu_percent, thread_count and more).",
	}, getProcessStatus)
	mcp.AddTool(server, &mcp.Tool{
		Name: "get_process_logs",
		Description: "Get recent log output from a dev environment process, read from the phrocs scrollback buffer. " +
			"Prefer a grep pattern over a large line count when looking for something specific.",
	}, getProcessLogs)
	mcp.AddTool(server, &mcp.Tool{
		Name: "send_keys",
		Description: "Send input to a dev environment process, for example to answer an interactive prompt " +
			"or to send ctrl+c.",
	}, sendKeys)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "toggle_process",
		Description: "Stop a process if it is running, start it if it is not.",
	}, toggleProcess)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "restart_process",
		Description: "Restart a process. Also starts a process that is stopped, crashed or done.",
	}, restartProcess)
	return server
}

func runMCP() int {
	if err := newMCPServer().Run(context.Background(), &mcp.StdioTransport{}); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: mcp: %v\n", err)
		return 1
	}
	return 0
}
