package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// socketGracePeriod gives the detached phrocs a chance to come up after
// `bin/start --detach` returns — useful when `hogli wait` is run immediately
// after.
const socketGracePeriod = 30 * time.Second

// runWait polls status_all on an interval until every process is ready
// (exit 0), any process has crashed (exit 1, prints tail logs), or the
// deadline expires (exit 2, prints what's not ready).
func runWait(timeoutSec int, asJSON bool) int {
	start := time.Now()
	deadline := start.Add(time.Duration(timeoutSec) * time.Second)
	var lastNotReady []string
	notReachableUntil := start.Add(socketGracePeriod)
	sawResponse := false

	for {
		resp, err := query(map[string]any{"cmd": "status_all"}, 2*time.Second)
		if err != nil {
			// The detached process may not have bound yet — allow a grace
			// period before failing.
			if time.Now().After(notReachableUntil) {
				return notReachable(asJSON, err.Error())
			}
			// Short --timeout (< socketGracePeriod) means the deadline can fire
			// before we ever reach the detached process. Treat that as
			// not_reachable, not timeout — the former is semantically correct
			// and keeps --json callers from seeing an empty notReady list.
			if time.Now().After(deadline) {
				if !sawResponse {
					return notReachable(asJSON, "deadline exceeded before detached phrocs bound")
				}
				return waitTimeout(asJSON, lastNotReady)
			}
			time.Sleep(500 * time.Millisecond)
			continue
		}
		sawResponse = true
		if resp["ok"] != true {
			return notReachable(asJSON, fmt.Sprintf("%v", resp["error"]))
		}
		procs, _ := resp["processes"].(map[string]any)
		verdict, crashed, notReady := classify(procs)
		lastNotReady = notReady

		switch verdict {
		case "ready":
			elapsed := time.Since(start).Round(time.Millisecond)
			if asJSON {
				printJSON(map[string]any{
					"verdict":   "ready",
					"elapsed_s": elapsed.Seconds(),
					"count":     len(procs),
				})
			} else {
				fmt.Printf("ok: %d procs ready in %s\n", len(procs), elapsed)
			}
			return 0
		case "crashed":
			if asJSON {
				printJSON(map[string]any{"verdict": "crashed", "procs": crashed})
			} else {
				for _, name := range crashed {
					tailLogs(name)
				}
				fmt.Fprintf(os.Stderr, "crashed: %s\n", strings.Join(crashed, ", "))
			}
			return 1
		}

		if time.Now().After(deadline) {
			return waitTimeout(asJSON, notReady)
		}
		time.Sleep(500 * time.Millisecond)
	}
}

// classify turns a status_all response into one of three verdicts.
func classify(procs map[string]any) (verdict string, crashed []string, notReady []string) {
	if len(procs) == 0 {
		return "pending", nil, nil
	}
	for name, v := range procs {
		snap, _ := v.(map[string]any)
		status, _ := snap["status"].(string)
		ready, _ := snap["ready"].(bool)
		if status == "crashed" {
			crashed = append(crashed, name)
			continue
		}
		if !ready {
			notReady = append(notReady, name+" ("+status+")")
		}
	}
	if len(crashed) > 0 {
		return "crashed", crashed, notReady
	}
	if len(notReady) > 0 {
		return "pending", nil, notReady
	}
	return "ready", nil, nil
}

func waitTimeout(asJSON bool, notReady []string) int {
	if asJSON {
		printJSON(map[string]any{"verdict": "timeout", "not_ready": notReady})
	} else {
		fmt.Fprintf(os.Stderr, "timeout: still not ready: %s\n", strings.Join(notReady, ", "))
	}
	return 2
}

func notReachable(asJSON bool, reason string) int {
	if asJSON {
		printJSON(map[string]any{"verdict": "not_reachable", "error": reason})
	} else {
		fmt.Fprintf(os.Stderr, "phrocs: detached phrocs not reachable: %s\n", reason)
	}
	return 3
}

func tailLogs(name string) {
	resp, err := query(map[string]any{
		"cmd":     "logs",
		"process": name,
		"lines":   30,
	}, 2*time.Second)
	if err != nil || resp["ok"] != true {
		return
	}
	lines, _ := resp["lines"].([]any)
	fmt.Fprintf(os.Stderr, "--- %s (last %d) ---\n", name, len(lines))
	for _, l := range lines {
		if s, ok := l.(string); ok {
			fmt.Fprintf(os.Stderr, "  %s\n", s)
		}
	}
}

func printJSON(v any) {
	_ = json.NewEncoder(os.Stdout).Encode(v)
}

// runStop sends a quit command to the detached phrocs, waits for the socket
// to disappear, and falls back to SIGTERM → SIGKILL via the pidfile if needed.
func runStop(timeoutSec int) int {
	sock, err := detachedSocketPath()
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}
	deadline := time.Now().Add(time.Duration(timeoutSec) * time.Second)

	// Fast path: if the socket isn't even there, check pidfile.
	if _, err := os.Stat(sock); errors.Is(err, os.ErrNotExist) {
		return cleanupIfStalePidfile()
	}

	resp, qerr := query(map[string]any{"cmd": "quit"}, 2*time.Second)
	if qerr == nil && resp["ok"] == true {
		// Wait for the socket to actually disappear.
		for time.Now().Before(deadline) {
			if _, err := net.DialTimeout("unix", sock, 100*time.Millisecond); err != nil {
				// No longer reachable — detached phrocs has torn down.
				_ = os.Remove(pidFilePath())
				fmt.Println("phrocs stopped")
				return 0
			}
			time.Sleep(100 * time.Millisecond)
		}
		// Deadline reached with socket still present. Before escalating,
		// check whether the detached phrocs finished its graceful shutdown
		// between our last dial and this check — its defer removes the
		// pidfile on a clean exit, so ENOENT here means "done, just slow".
		if _, err := os.Stat(pidFilePath()); errors.Is(err, os.ErrNotExist) {
			_ = os.Remove(sock)
			fmt.Println("phrocs stopped")
			return 0
		}
		fmt.Fprintln(os.Stderr, "phrocs: detached phrocs did not exit in time; escalating")
	}

	// Fallback: SIGTERM via pidfile.
	pid, err := readPidfile()
	if errors.Is(err, os.ErrNotExist) {
		// Pidfile vanished after we committed to escalating — detached
		// phrocs has already exited cleanly. Clean up any leftover socket
		// and report success rather than a confusing "file not found".
		_ = os.Remove(sock)
		fmt.Println("phrocs stopped")
		return 0
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}
	if pid <= 0 {
		return 0
	}
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil && !errors.Is(err, syscall.ESRCH) {
		fmt.Fprintf(os.Stderr, "phrocs: SIGTERM %d: %v\n", pid, err)
		return 1
	}
	for time.Now().Before(deadline) {
		if !pidAlive(pid) {
			_ = os.Remove(pidFilePath())
			_ = os.Remove(sock)
			fmt.Println("phrocs stopped (SIGTERM)")
			return 0
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Last resort.
	_ = syscall.Kill(pid, syscall.SIGKILL)
	time.Sleep(200 * time.Millisecond)
	_ = os.Remove(pidFilePath())
	_ = os.Remove(sock)
	fmt.Fprintln(os.Stderr, "phrocs killed (SIGKILL)")
	return 0
}

// cleanupIfStalePidfile handles the case where the socket is gone: either no
// detached phrocs is running (exit 0), or there's a stale pidfile we should
// remove.
func cleanupIfStalePidfile() int {
	pid, err := readPidfile()
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		fmt.Fprintf(os.Stderr, "phrocs: pidfile: %v\n", err)
		return 1
	}
	if pid > 0 && pidAlive(pid) {
		// Socket gone but PID alive — unusual, try SIGTERM.
		_ = syscall.Kill(pid, syscall.SIGTERM)
	}
	_ = os.Remove(pidFilePath())
	fmt.Println("no detached phrocs running")
	return 0
}

func readPidfile() (int, error) {
	data, err := os.ReadFile(pidFilePath())
	if err != nil {
		return 0, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 0, fmt.Errorf("parse pidfile: %w", err)
	}
	return pid, nil
}

func pidAlive(pid int) bool {
	// Signal 0 tests whether we can signal the process without delivering one.
	err := syscall.Kill(pid, 0)
	return err == nil || errors.Is(err, syscall.EPERM)
}

// runAttach is a minimal polling client: it prints each process's status
// every 500ms and exits on Ctrl+C. Full push-based TUI attach is a follow-up.
func runAttach() int {
	for {
		resp, err := query(map[string]any{"cmd": "status_all"}, 2*time.Second)
		if err != nil {
			fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
			return 1
		}
		procs, _ := resp["processes"].(map[string]any)
		fmt.Print("\033[H\033[2J") // clear screen
		fmt.Printf("phrocs (detached) — %d procs — Ctrl+C to exit\n\n", len(procs))
		for name, v := range procs {
			snap, _ := v.(map[string]any)
			status, _ := snap["status"].(string)
			ready, _ := snap["ready"].(bool)
			readiness := "…"
			if ready {
				readiness = "✓"
			}
			if status == "crashed" {
				readiness = "✗"
			}
			fmt.Printf("  %s  %-20s  %s\n", readiness, name, status)
		}
		time.Sleep(500 * time.Millisecond)
	}
}
