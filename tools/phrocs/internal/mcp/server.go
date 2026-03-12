// Package mcp implements a minimal MCP server over the Streamable HTTP
// transport (spec 2024-11-05). It exposes two tools that give AI coding
// agents read access to the live process data held by process.Manager:
//
//   - get_process_status – status + PID for one or all processes
//   - get_process_logs   – recent output lines with optional grep filter
//
// The server is embedded inside phrocs and started as a goroutine alongside
// the Bubble Tea TUI. Because the TUI takes over the TTY in alt-screen mode,
// the MCP server binds a regular TCP socket (default :5835) rather than using
// stdio transport.
//
// When hogli dev:setup --log is active, bin/process-monitor writes rich
// performance metrics (CPU%, RSS, thread count, startup duration, etc.) to
// /tmp/posthog-{name}.json. get_process_status merges those metrics into its
// response when the files are present; the in-memory phrocs data is always
// authoritative for status and PID.
package mcp

import (
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"regexp"
	"strings"

	"github.com/charmbracelet/x/ansi"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// ── JSON-RPC 2.0 wire types ──────────────────────────────────────────────────

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"` // nil for notifications
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type rpcResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  any             `json:"result,omitempty"`
	Error   *rpcError       `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// ── Server ───────────────────────────────────────────────────────────────────

// Server is an MCP HTTP server backed by a live process.Manager.
type Server struct {
	mgr *process.Manager
}

// NewServer creates a Server. Call ListenAndServe to start accepting requests.
func NewServer(mgr *process.Manager) *Server {
	return &Server{mgr: mgr}
}

// ListenAndServe binds addr and serves until the process exits.
func (s *Server) ListenAndServe(addr string) (net.Addr, error) {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}
	go http.Serve(ln, s) //nolint:errcheck
	return ln.Addr(), nil
}

// ServeHTTP implements http.Handler, routing /mcp to the MCP endpoint.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/mcp" {
		s.handleMCP(w, r)
		return
	}
	http.NotFound(w, r)
}

// handleMCP handles POST /mcp (Streamable HTTP transport).
func (s *Server) handleMCP(w http.ResponseWriter, r *http.Request) {
	// Permissive CORS for local tooling
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Headers", "content-type")
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req rpcRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, rpcResponse{JSONRPC: "2.0", Error: &rpcError{Code: -32700, Message: "parse error"}})
		return
	}

	// Notifications have no id and expect no response
	if req.ID == nil {
		w.WriteHeader(http.StatusAccepted)
		return
	}

	result, rpcErr := s.dispatch(req.Method, req.Params)
	resp := rpcResponse{JSONRPC: "2.0", ID: req.ID}
	if rpcErr != nil {
		resp.Error = rpcErr
	} else {
		resp.Result = result
	}
	writeJSON(w, resp)
}

func (s *Server) dispatch(method string, params json.RawMessage) (any, *rpcError) {
	switch method {
	case "initialize":
		return map[string]any{
			"protocolVersion": "2024-11-05",
			"capabilities":    map[string]any{"tools": map[string]any{}},
			"serverInfo":      map[string]any{"name": "phrocs", "version": "1.0"},
		}, nil

	case "tools/list":
		return map[string]any{"tools": toolDefinitions()}, nil

	case "tools/call":
		return s.callTool(params)

	default:
		return nil, &rpcError{Code: -32601, Message: "method not found: " + method}
	}
}

// ── Tool definitions ─────────────────────────────────────────────────────────

func toolDefinitions() []map[string]any {
	return []map[string]any{
		{
			"name":        "get_process_status",
			"description": "Get the status of one or all dev environment processes managed by phrocs. Returns the running state, PID, and line count for each process.",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"process": map[string]any{
						"type":        "string",
						"description": "Process name (e.g. 'backend', 'frontend'). Leave empty to get all processes.",
					},
				},
			},
		},
		{
			"name":        "get_process_logs",
			"description": "Get recent log output from a dev environment process managed by phrocs. ANSI escape codes are stripped.",
			"inputSchema": map[string]any{
				"type":     "object",
				"required": []string{"process"},
				"properties": map[string]any{
					"process": map[string]any{
						"type":        "string",
						"description": "Process name (e.g. 'backend', 'frontend', 'celery-worker').",
					},
					"lines": map[string]any{
						"type":        "integer",
						"description": "Number of recent lines to return (default 100, max 500).",
						"default":     100,
					},
					"grep": map[string]any{
						"type":        "string",
						"description": "Optional regex pattern to filter lines (e.g. 'ERROR', 'warning').",
					},
				},
			},
		},
	}
}

// ── Tool dispatch ─────────────────────────────────────────────────────────────

func (s *Server) callTool(params json.RawMessage) (any, *rpcError) {
	var p struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		return nil, &rpcError{Code: -32602, Message: "invalid params"}
	}

	var (
		result any
		err    error
	)
	switch p.Name {
	case "get_process_status":
		result, err = s.toolGetStatus(p.Arguments)
	case "get_process_logs":
		result, err = s.toolGetLogs(p.Arguments)
	default:
		return nil, &rpcError{Code: -32602, Message: "unknown tool: " + p.Name}
	}
	if err != nil {
		return nil, &rpcError{Code: -32603, Message: err.Error()}
	}
	return textResult(result), nil
}

func (s *Server) toolGetStatus(args json.RawMessage) (any, error) {
	var a struct {
		Process string `json:"process"`
	}
	json.Unmarshal(args, &a) //nolint:errcheck — empty args is fine

	procs := s.mgr.Procs()
	if a.Process != "" {
		for _, p := range procs {
			if p.Name == a.Process {
				return map[string]any{p.Name: procStatusFields(p)}, nil
			}
		}
		return map[string]any{a.Process: map[string]any{"error": "process not found"}}, nil
	}

	result := make(map[string]any, len(procs))
	for _, p := range procs {
		result[p.Name] = procStatusFields(p)
	}
	return result, nil
}

// procStatusFields builds the status map for a single process.
// It starts with the authoritative in-memory phrocs data, then merges any
// performance metrics written by bin/process-monitor into the result.
// Keys from the JSON file are only included when the file exists and is
// readable; missing or malformed files are silently ignored.
func procStatusFields(p *process.Process) map[string]any {
	result := map[string]any{
		"status":     p.Status().String(),
		"pid":        p.PID(),
		"line_count": len(p.Lines()),
	}

	// Merge richer metrics from bin/process-monitor when log mode is active.
	// phrocs status/pid take precedence over anything in the file.
	if extra := readMonitorJSON(p.Name); extra != nil {
		for k, v := range extra {
			switch k {
			case "status", "pid", "process":
				// Keep the authoritative in-memory values.
			default:
				result[k] = v
			}
		}
	}

	return result
}

// readMonitorJSON reads /tmp/posthog-{name}.json written by bin/process-monitor.
// Returns nil if the file does not exist or cannot be parsed.
func readMonitorJSON(name string) map[string]any {
	data, err := os.ReadFile("/tmp/posthog-" + name + ".json")
	if err != nil {
		return nil
	}
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		return nil
	}
	return m
}

func (s *Server) toolGetLogs(args json.RawMessage) (any, error) {
	var a struct {
		Process string `json:"process"`
		Lines   int    `json:"lines"`
		Grep    string `json:"grep"`
	}
	a.Lines = 100
	json.Unmarshal(args, &a) //nolint:errcheck

	a.Lines = clamp(a.Lines, 1, 500)

	var target *process.Process
	for _, p := range s.mgr.Procs() {
		if p.Name == a.Process {
			target = p
			break
		}
	}
	if target == nil {
		return map[string]any{"process": a.Process, "error": "process not found"}, nil
	}

	raw := target.Lines()
	// Strip ANSI so agents receive clean text
	lines := make([]string, len(raw))
	for i, l := range raw {
		lines[i] = ansi.Strip(l)
	}

	if a.Grep != "" {
		re, err := regexp.Compile(a.Grep)
		if err != nil {
			return nil, fmt.Errorf("invalid grep pattern: %w", err)
		}
		var matched []string
		for _, l := range lines {
			if re.MatchString(l) {
				matched = append(matched, l)
			}
		}
		tail := tailLines(matched, a.Lines)
		return map[string]any{
			"process":        a.Process,
			"grep":           a.Grep,
			"total_matched":  len(matched),
			"returned_lines": len(tail),
			"logs":           tail,
		}, nil
	}

	tail := tailLines(lines, a.Lines)
	return map[string]any{
		"process":        a.Process,
		"total_lines":    len(lines),
		"returned_lines": len(tail),
		"logs":           tail,
	}, nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

// textResult wraps a value in the MCP tool-result content envelope.
// The value is JSON-marshalled and returned as a single text content block.
func textResult(v any) map[string]any {
	b, _ := json.Marshal(v)
	return map[string]any{
		"content": []map[string]any{
			{"type": "text", "text": string(b)},
		},
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	b, _ := json.Marshal(v)
	w.Write(b) //nolint:errcheck
}

func tailLines(lines []string, n int) []string {
	if len(lines) <= n {
		return lines
	}
	return lines[len(lines)-n:]
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// DefaultAddr is the default MCP server address.
const DefaultAddr = "127.0.0.1:5835"

// AddrFlag returns a human-readable description for the --mcp-addr flag.
func AddrFlag() string {
	return strings.Join([]string{
		"Address for the embedded MCP HTTP server (host:port).",
		`Set to "" to disable. Default: ` + DefaultAddr,
	}, " ")
}
