package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

func invokeCmd(args []string) {
	var (
		server  string
		tool    string
		argsStr string
		timeout int
	)
	parseFlags("invoke", args, func(fs *flag.FlagSet) {
		fs.StringVar(&server, "server", "http://localhost:18080", "fake-posthog serve URL")
		fs.StringVar(&tool, "tool", "", "qualified tool name (e.g. echo.hello)")
		fs.StringVar(&argsStr, "args", "{}", "JSON object passed as tool args")
		fs.IntVar(&timeout, "timeout", 30, "Server-side wait timeout (seconds)")
	})
	if tool == "" {
		fmt.Fprintln(os.Stderr, "invoke: --tool is required")
		os.Exit(2)
	}

	// Validate args is parseable JSON object before sending.
	var argsCheck any
	if err := json.Unmarshal([]byte(argsStr), &argsCheck); err != nil {
		fmt.Fprintf(os.Stderr, "invoke: --args is not valid JSON: %v\n", err)
		os.Exit(2)
	}

	reqBody, _ := json.Marshal(map[string]any{
		"tool_name":       tool,
		"args":            json.RawMessage(argsStr),
		"timeout_seconds": timeout,
	})
	httpClient := &http.Client{Timeout: time.Duration(timeout+5) * time.Second}
	resp, err := httpClient.Post(
		strings.TrimRight(server, "/")+"/admin/invoke",
		"application/json",
		bytes.NewReader(reqBody),
	)
	if err != nil {
		fmt.Fprintf(os.Stderr, "invoke: POST /admin/invoke: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 400 {
		fmt.Fprintf(os.Stderr, "invoke: server returned %d:\n%s\n", resp.StatusCode, string(body))
		os.Exit(1)
	}

	// Pretty-print whatever the server returned. Keep it raw-ish so the
	// caller can pipe it through jq if they want.
	var pretty bytes.Buffer
	if err := json.Indent(&pretty, body, "", "  "); err != nil {
		// Body wasn't JSON for some reason — print as-is.
		os.Stdout.Write(body)
		return
	}
	pretty.WriteByte('\n')
	_, _ = os.Stdout.Write(pretty.Bytes())

	// Non-zero exit if the runner reported failure or the wait timed
	// out — useful for scripting.
	var parsed struct {
		Status string `json:"status"`
	}
	if json.Unmarshal(body, &parsed) == nil && parsed.Status != "done" {
		os.Exit(1)
	}
}

func stateCmd(args []string) {
	var server string
	parseFlags("state", args, func(fs *flag.FlagSet) {
		fs.StringVar(&server, "server", "http://localhost:18080", "fake-posthog serve URL")
	})
	httpClient := &http.Client{Timeout: 5 * time.Second}
	resp, err := httpClient.Get(strings.TrimRight(server, "/") + "/admin/state")
	if err != nil {
		fmt.Fprintf(os.Stderr, "state: GET /admin/state: %v\n", err)
		os.Exit(1)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		fmt.Fprintf(os.Stderr, "state: server returned %d:\n%s\n", resp.StatusCode, string(body))
		os.Exit(1)
	}
	var pretty bytes.Buffer
	if err := json.Indent(&pretty, body, "", "  "); err != nil {
		os.Stdout.Write(body)
		return
	}
	pretty.WriteByte('\n')
	_, _ = os.Stdout.Write(pretty.Bytes())
}
