package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/x/ansi"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Longer than a stop's grace period, which the stop and restart commands wait out.
const mcpQueryTimeout = 10 * time.Second

const (
	defaultLogLines = 100
	maxLogLines     = 500

	defaultWaitSeconds = 60
	maxWaitSeconds     = 120
	waitPollInterval   = 500 * time.Millisecond

	lastOutputMaxChars = 200
)

type statusInput struct {
	Process string `json:"process,omitempty" jsonschema:"Process name, for example backend or frontend. Leave empty for all processes."`
	Detail  string `json:"detail,omitempty" jsonschema:"summary (default): one line per process. full: also timings and resource metrics."`
}

type logsInput struct {
	Process string `json:"process" jsonschema:"Process name, for example backend, frontend or celery-worker."`
	Lines   int    `json:"lines,omitempty" jsonschema:"Number of recent lines to return. Default 100, max 500."`
	Grep    string `json:"grep,omitempty" jsonschema:"Optional regex. Only matching lines are returned, searched across the whole buffer."`
}

type waitInput struct {
	Process        string `json:"process,omitempty" jsonschema:"Process to wait for. Leave empty to wait for every process."`
	TimeoutSeconds int    `json:"timeout_seconds,omitempty" jsonschema:"How long to wait. Default 60, max 120."`
}

type sendKeysInput struct {
	Process string `json:"process" jsonschema:"Process name."`
	Keys    string `json:"keys" jsonschema:"Text to send. A ctrl+c is the character U+0003."`
	Submit  bool   `json:"submit,omitempty" jsonschema:"Press enter after the text, for example to answer a y/n prompt."`
}

type processInput struct {
	Process string `json:"process" jsonschema:"Process name."`
}

// procSnapshot mirrors the fields of process.Snapshot that the summary reads.
type procSnapshot struct {
	Status        string `json:"status"`
	PID           int    `json:"pid"`
	Ready         bool   `json:"ready"`
	HasReadyCheck bool   `json:"has_ready_check"`
	ExitCode      *int   `json:"exit_code"`
	StartedAt     string `json:"started_at"`
}

type procSummary struct {
	Name       string `json:"-"`
	Status     string `json:"status"`
	Ready      bool   `json:"ready"`
	ReadyCheck bool   `json:"has_ready_check"`
	PID        int    `json:"pid,omitempty"`
	ExitCode   *int   `json:"exit_code,omitempty"`
	UptimeS    int    `json:"uptime_s,omitempty"`
	LastOutput string `json:"last_output,omitempty"`
}

func askPhrocs(cmd map[string]any) (map[string]any, error) {
	return askPhrocsWithin(cmd, mcpQueryTimeout)
}

func askPhrocsWithin(cmd map[string]any, timeout time.Duration) (map[string]any, error) {
	resp, err := queryDetached(cmd, timeout)
	if err != nil {
		if isTimeout(err) {
			return nil, fmt.Errorf("phrocs did not answer within %s", timeout.Round(time.Millisecond))
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

func textResult(text string) *mcp.CallToolResult {
	return &mcp.CallToolResult{Content: []mcp.Content{&mcp.TextContent{Text: text}}}
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

// intField reads a JSON number, which arrives as float64 from the IPC socket.
func intField(v any) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	}
	return 0
}

func stringLines(v any) []string {
	items, _ := v.([]any)
	lines := make([]string, 0, len(items))
	for _, item := range items {
		if s, ok := item.(string); ok {
			lines = append(lines, s)
		}
	}
	return lines
}

// lastOutput returns the last non-empty log line of a process, which for a
// crashed process is usually the error.
func lastOutput(name string) string {
	resp, err := askPhrocs(map[string]any{"cmd": "logs", "process": name, "lines": 20})
	if err != nil {
		return ""
	}
	lines := cleanLogLines(stringLines(resp["lines"]))
	for i := len(lines) - 1; i >= 0; i-- {
		line := strings.TrimSpace(lines[i])
		if line == "" || strings.HasPrefix(line, "[repeated x") {
			continue
		}
		if runes := []rune(line); len(runes) > lastOutputMaxChars {
			line = string(runes[:lastOutputMaxChars]) + "…"
		}
		return line
	}
	return ""
}

func decodeSnapshot(v any) procSnapshot {
	var snap procSnapshot
	raw, _ := json.Marshal(v)
	_ = json.Unmarshal(raw, &snap)
	return snap
}

func summarize(name string, snap procSnapshot, now time.Time) procSummary {
	sum := procSummary{
		Name:       name,
		Status:     snap.Status,
		Ready:      snap.Ready,
		ReadyCheck: snap.HasReadyCheck,
		ExitCode:   snap.ExitCode,
	}
	if snap.Status == "running" || snap.Status == "pending" {
		sum.PID = snap.PID
		if started, err := time.Parse(time.RFC3339Nano, snap.StartedAt); err == nil && !started.IsZero() {
			sum.UptimeS = int(now.Sub(started).Seconds())
		}
	}
	if snap.Status == "crashed" {
		sum.LastOutput = lastOutput(name)
	}
	return sum
}

func (s procSummary) line() string {
	uptime := ""
	if s.UptimeS > 0 {
		uptime = ", up " + (time.Duration(s.UptimeS) * time.Second).String()
	}
	exit := ""
	if s.ExitCode != nil {
		exit = fmt.Sprintf(", exit %d", *s.ExitCode)
	}
	switch s.Status {
	case "running":
		if !s.ReadyCheck {
			return fmt.Sprintf("%s: running, no ready check (pid %d%s)", s.Name, s.PID, uptime)
		}
		return fmt.Sprintf("%s: ready (pid %d%s)", s.Name, s.PID, uptime)
	case "pending":
		return fmt.Sprintf("%s: starting, waiting for its ready line (pid %d%s)", s.Name, s.PID, uptime)
	case "crashed":
		line := fmt.Sprintf("%s: crashed%s", s.Name, exit)
		if s.LastOutput != "" {
			line += ". Last output: " + s.LastOutput
		}
		return line
	case "done":
		return fmt.Sprintf("%s: done%s", s.Name, exit)
	default:
		return fmt.Sprintf("%s: %s", s.Name, s.Status)
	}
}

// statusRank puts the processes an agent has to act on first.
func statusRank(status string) int {
	switch status {
	case "crashed":
		return 0
	case "pending":
		return 1
	case "running":
		return 2
	case "done":
		return 3
	default:
		return 4
	}
}

func summaryText(sums []procSummary) string {
	sort.SliceStable(sums, func(i, j int) bool {
		ri, rj := statusRank(sums[i].Status), statusRank(sums[j].Status)
		if ri != rj {
			return ri < rj
		}
		return sums[i].Name < sums[j].Name
	})
	counts := map[string]int{}
	for _, s := range sums {
		counts[s.Status]++
	}
	var parts []string
	for _, status := range []string{"crashed", "pending", "running", "done", "stopped"} {
		n := counts[status]
		if n == 0 {
			continue
		}
		label := status
		if status == "pending" {
			label = "starting"
		}
		parts = append(parts, fmt.Sprintf("%d %s", n, label))
	}
	noun := "processes"
	if len(sums) == 1 {
		noun = "process"
	}
	lines := []string{fmt.Sprintf("%d %s: %s.", len(sums), noun, strings.Join(parts, ", "))}
	for _, s := range sums {
		lines = append(lines, s.line())
	}
	return strings.Join(lines, "\n")
}

func fetchSnapshots(process string, withMetrics bool, timeout time.Duration) (map[string]any, error) {
	if process != "" {
		resp, err := askPhrocsWithin(map[string]any{"cmd": "status", "process": process, "no_metrics": !withMetrics}, timeout)
		if err != nil {
			return nil, err
		}
		return map[string]any{process: resp}, nil
	}
	resp, err := askPhrocsWithin(map[string]any{"cmd": "status_all", "no_metrics": !withMetrics}, timeout)
	if err != nil {
		return nil, err
	}
	procs, _ := resp["processes"].(map[string]any)
	return procs, nil
}

func summarizeAll(snaps map[string]any) []procSummary {
	now := time.Now()
	sums := make([]procSummary, 0, len(snaps))
	for name, v := range snaps {
		sums = append(sums, summarize(name, decodeSnapshot(v), now))
	}
	return sums
}

func getProcessStatus(_ context.Context, _ *mcp.CallToolRequest, in statusInput) (*mcp.CallToolResult, any, error) {
	if in.Detail != "" && in.Detail != "summary" && in.Detail != "full" {
		return nil, nil, fmt.Errorf("detail must be summary or full, got %q", in.Detail)
	}
	full := in.Detail == "full"
	snaps, err := fetchSnapshots(in.Process, full, mcpQueryTimeout)
	if err != nil {
		return nil, nil, err
	}
	sums := summarizeAll(snaps)
	text := summaryText(sums)
	if full {
		raw, _ := json.Marshal(snaps)
		return textResult(text + "\n\n" + string(raw)), nil, nil
	}
	data := make(map[string]procSummary, len(sums))
	for _, s := range sums {
		data[s.Name] = s
	}
	return textResult(text), data, nil
}

func getProcessLogs(_ context.Context, _ *mcp.CallToolRequest, in logsInput) (*mcp.CallToolResult, any, error) {
	lines := in.Lines
	if lines <= 0 {
		lines = defaultLogLines
	}
	clamped := lines > maxLogLines
	lines = min(lines, maxLogLines)
	resp, err := askPhrocs(map[string]any{"cmd": "logs", "process": in.Process, "lines": lines, "grep": in.Grep})
	if err != nil {
		return nil, nil, err
	}

	raw := stringLines(resp["lines"])
	header := fmt.Sprintf("%s: last %d of %d buffered lines from the current run.", in.Process, len(raw), intField(resp["buffered"]))
	if in.Grep != "" {
		matched := intField(resp["total_matched"])
		noun := "lines match"
		if matched == 1 {
			noun = "line matches"
		}
		header = fmt.Sprintf("%s: %d %s %q, showing the last %d.", in.Process, matched, noun, in.Grep, len(raw))
	}
	if clamped {
		header += fmt.Sprintf(" lines is capped at %d.", maxLogLines)
	}
	if len(raw) == 0 {
		return textResult(header), nil, nil
	}
	cleaned := cleanLogLines(raw)
	if len(cleaned) < len(raw) {
		header += " Repeated lines are folded."
	}
	return textResult(header + "\n\n" + strings.Join(cleaned, "\n")), nil, nil
}

func waitReady(ctx context.Context, _ *mcp.CallToolRequest, in waitInput) (*mcp.CallToolResult, any, error) {
	timeout := in.TimeoutSeconds
	if timeout <= 0 {
		timeout = defaultWaitSeconds
	}
	timeout = min(timeout, maxWaitSeconds)
	start := time.Now()
	deadline := start.Add(time.Duration(timeout) * time.Second)

	for {
		// Bound each request by the wait deadline so a stalled phrocs still
		// yields the timeout verdict on time.
		snaps, err := fetchSnapshots(in.Process, false, max(time.Until(deadline), time.Second))
		if err != nil {
			return nil, nil, err
		}
		if len(snaps) == 0 {
			return textResult("No processes are configured, so there is nothing to wait for."), nil, nil
		}
		if snap := decodeSnapshot(snaps[in.Process]); in.Process != "" && snap.Status == "stopped" {
			return textResult(fmt.Sprintf("%s is stopped. Start it with start_process first.", in.Process)), nil, nil
		}
		verdict, crashed, notReady := classify(snaps)
		elapsed := time.Since(start).Round(time.Second)
		switch {
		case verdict == "ready":
			return textResult(fmt.Sprintf("Ready after %s.\n%s", elapsed, summaryText(summarizeAll(snaps)))), nil, nil
		case verdict == "crashed":
			return textResult(fmt.Sprintf("Crashed: %s.\n%s", strings.Join(crashed, ", "), summaryText(summarizeAll(snaps)))), nil, nil
		case time.Now().After(deadline):
			return textResult(fmt.Sprintf("Timed out after %s. Not ready: %s.\n%s",
				elapsed, strings.Join(notReady, ", "), summaryText(summarizeAll(snaps)))), nil, nil
		}
		select {
		case <-ctx.Done():
			return nil, nil, ctx.Err()
		case <-time.After(waitPollInterval):
		}
	}
}

func sendKeys(_ context.Context, _ *mcp.CallToolRequest, in sendKeysInput) (*mcp.CallToolResult, any, error) {
	keys := in.Keys
	if in.Submit {
		keys += "\r"
	}
	if _, err := askPhrocs(map[string]any{"cmd": "send-keys", "process": in.Process, "keys": keys}); err != nil {
		return nil, nil, err
	}
	return textResult(fmt.Sprintf("Sent %d characters to %s. Read its logs to see the response.", len([]rune(keys)), in.Process)), nil, nil
}

func processAction(cmd, process, doneText, alreadyText string) (*mcp.CallToolResult, any, error) {
	resp, err := askPhrocs(map[string]any{"cmd": cmd, "process": process})
	if err != nil {
		return nil, nil, err
	}
	if resp["already"] == true {
		return textResult(fmt.Sprintf(alreadyText, process)), nil, nil
	}
	return textResult(fmt.Sprintf(doneText, process)), nil, nil
}

func startProcess(_ context.Context, _ *mcp.CallToolRequest, in processInput) (*mcp.CallToolResult, any, error) {
	return processAction("start", in.Process, "Starting %s. Use wait_ready to know when it is up.", "%s is already running.")
}

func stopProcess(_ context.Context, _ *mcp.CallToolRequest, in processInput) (*mcp.CallToolResult, any, error) {
	return processAction("stop", in.Process, "Stopped %s.", "%s was not running.")
}

func restartProcess(_ context.Context, _ *mcp.CallToolRequest, in processInput) (*mcp.CallToolResult, any, error) {
	text := "Restarting %s. Use wait_ready to know when it is up."
	return processAction("restart", in.Process, text, text)
}

func newMCPServer() *mcp.Server {
	server := mcp.NewServer(
		&mcp.Implementation{Name: "phrocs", Version: Version},
		&mcp.ServerOptions{Instructions: "Tools for inspecting and controlling the local PostHog dev environment run by phrocs. " +
			"Start the dev environment with `./bin/start` before using these tools. " +
			"Start with get_process_status; it lists failed processes first with their last output line."},
	)
	closedWorld := false
	readOnly := &mcp.ToolAnnotations{ReadOnlyHint: true, OpenWorldHint: &closedWorld}

	mcp.AddTool(server, &mcp.Tool{
		Name: "get_process_status",
		Description: "Summarize the dev environment processes: one line each, failed and starting ones first, " +
			"with the last output line of a crashed process. detail=full adds pid, timings and resource metrics.",
		Annotations: readOnly,
	}, getProcessStatus)
	mcp.AddTool(server, &mcp.Tool{
		Name: "get_process_logs",
		Description: "Recent output of one process from the current run (a restart clears it), with colors and repeated lines removed. " +
			"Use grep to search the whole buffer instead of asking for many lines.",
		Annotations: readOnly,
	}, getProcessLogs)
	mcp.AddTool(server, &mcp.Tool{
		Name: "wait_ready",
		Description: "Wait until one process, or every process, is ready, has crashed, or the timeout passes. " +
			"Use it after starting or restarting instead of polling get_process_status.",
		Annotations: readOnly,
	}, waitReady)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "start_process",
		Description: "Start a process that is stopped, crashed or done. Does nothing if it is already running.",
		// Some configured processes are one-shot tasks such as a database
		// reset, so starting one is neither safe nor free to repeat.
		Annotations: &mcp.ToolAnnotations{OpenWorldHint: &closedWorld},
	}, startProcess)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "stop_process",
		Description: "Stop a process and wait for it to exit. Also cancels a pending autorestart of a crashed process.",
		Annotations: &mcp.ToolAnnotations{IdempotentHint: true, OpenWorldHint: &closedWorld},
	}, stopProcess)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "restart_process",
		Description: "Restart a process, or start it if it is stopped, crashed or done. The new run starts with empty logs.",
		Annotations: &mcp.ToolAnnotations{OpenWorldHint: &closedWorld},
	}, restartProcess)
	mcp.AddTool(server, &mcp.Tool{
		Name: "send_keys",
		Description: "Type into a running process, for example to answer a prompt. " +
			"Set submit to press enter after the text. Fails if the process is not running.",
		Annotations: &mcp.ToolAnnotations{OpenWorldHint: &closedWorld},
	}, sendKeys)
	return server
}

func runMCP() int {
	if err := newMCPServer().Run(context.Background(), &mcp.StdioTransport{}); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: mcp: %v\n", err)
		return 1
	}
	return 0
}
