package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// socketGracePeriod gives the detached phrocs a chance to come up after
// `bin/start --detach` returns — useful when `hogli wait` is run immediately
// after.
const socketGracePeriod = 30 * time.Second

var queryDetached = query

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
		resp, err := queryDetached(map[string]any{"cmd": "status_all"}, 2*time.Second)
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
		// Empty processes is a static state — `mgr.Procs()` returns the
		// configured slice the moment the manager is constructed, so polling
		// won't make procs appear. Surface it as a distinct verdict instead
		// of a "still not ready: " timeout with an empty list.
		if len(procs) == 0 {
			return noProcs(asJSON)
		}
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
//
// "done" counts as ready: a one-shot setup proc (migrations, seed scripts) that
// exits 0 should not block `phrocs wait` forever just because it lacks a
// `ready_pattern`. Only `crashed` is a terminal failure.
func classify(procs map[string]any) (verdict string, crashed []string, notReady []string) {
	if len(procs) == 0 {
		return "pending", nil, nil
	}
	for _, name := range sortedProcessNames(procs) {
		v := procs[name]
		snap, _ := v.(map[string]any)
		status, _ := snap["status"].(string)
		ready, _ := snap["ready"].(bool)
		if status == "crashed" {
			crashed = append(crashed, name)
			continue
		}
		if status == "done" {
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

func sortedProcessNames(procs map[string]any) []string {
	names := make([]string, 0, len(procs))
	for name := range procs {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
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

// noProcs reports a config with zero processes. Treated as "ready" exit-code-
// wise (there's nothing to wait for) but with a distinct verdict so callers
// gating on this state don't silently mask a misconfigured config file.
func noProcs(asJSON bool) int {
	if asJSON {
		printJSON(map[string]any{"verdict": "no_procs"})
	} else {
		fmt.Fprintln(os.Stderr, "phrocs: config has no processes")
	}
	return 0
}

func tailLogs(name string) {
	resp, err := queryDetached(map[string]any{
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
		return stopViaPidfile("", deadline)
	}

	resp, qerr := queryDetached(map[string]any{"cmd": "quit"}, 2*time.Second)
	if qerr == nil && resp["ok"] == true {
		// Wait for the socket to actually disappear.
		for time.Now().Before(deadline) {
			if conn, err := net.DialTimeout("unix", sock, 100*time.Millisecond); err == nil {
				// Probe succeeded — server still up. Close the conn immediately
				// so we don't leak an idle handle goroutine on the server side.
				_ = conn.Close()
			} else {
				// Dial failed — but a fresh detached could race in between
				// the old process releasing the lock and us cleaning up.
				// `cleanIfStale` holds the probe lock during pidfile removal
				// so a racing detached can't have its pidfile clobbered.
				// Lock-check errors are treated as "still held" to avoid
				// false-positive cleanup on transient failures.
				if cleaned, lerr := cleanIfStale(""); lerr == nil && cleaned {
					fmt.Println("phrocs stopped")
					return 0
				}
			}
			time.Sleep(100 * time.Millisecond)
		}
		// Deadline reached with socket still present. Before escalating,
		// check whether the detached phrocs finished its graceful shutdown
		// between our last dial and this check.
		if cleaned, lerr := cleanIfStale(sock); lerr == nil && cleaned {
			fmt.Println("phrocs stopped")
			return 0
		}
		fmt.Fprintln(os.Stderr, "phrocs: detached phrocs did not exit in time; escalating")
	}

	return stopViaPidfile(sock, deadline)
}

// stopViaPidfile uses the pidfile fallback only if the detached lock is still
// held. If the lock can be acquired, the pidfile is stale and its PID may have
// been reused by an unrelated process.
func stopViaPidfile(sock string, deadline time.Time) int {
	cleaned, err := cleanIfStale(sock)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: pidfile lock: %v\n", err)
		return 1
	}
	if cleaned {
		fmt.Println("no detached phrocs running")
		return 0
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

// cleanIfStale tries to acquire the pidfile flock. If it succeeds, the previous
// detached has exited and the pidfile (plus optional socket) are stale; both
// are removed *while the lock is still held* so a racing `phrocs --detach`
// can't squeeze in and have its fresh pidfile clobbered.
//
// Returns (true, nil) when cleanup happened, (false, nil) when a live detached
// owns the lock (nothing was touched). Errors mean "couldn't determine state";
// callers must treat them as "still held" to avoid false-positive cleanup.
func cleanIfStale(sock string) (bool, error) {
	lockFile, err := os.OpenFile(pidLockFilePath(), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			// No lock file means no detached has ever run from this CWD; the
			// pidfile and socket can only be debris. Nothing for us to remove.
			return true, nil
		}
		return false, err
	}
	defer func() { _ = lockFile.Close() }()

	err = syscall.Flock(int(lockFile.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if err == nil {
		// Hold the lock for the full cleanup. fd close releases it.
		_ = os.Remove(pidFilePath())
		if sock != "" {
			_ = os.Remove(sock)
		}
		return true, nil
	}
	if errors.Is(err, syscall.EWOULDBLOCK) || errors.Is(err, syscall.EAGAIN) {
		return false, nil
	}
	return false, err
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
		resp, err := queryDetached(map[string]any{"cmd": "status_all"}, 2*time.Second)
		if err != nil {
			fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
			return 1
		}
		if resp["ok"] != true {
			fmt.Fprintf(os.Stderr, "phrocs: %v\n", resp["error"])
			return 1
		}
		procs, _ := resp["processes"].(map[string]any)
		fmt.Print("\033[H\033[2J") // clear screen
		fmt.Printf("phrocs (detached) — %d procs — Ctrl+C to exit\n\n", len(procs))
		for _, name := range sortedProcessNames(procs) {
			v := procs[name]
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
