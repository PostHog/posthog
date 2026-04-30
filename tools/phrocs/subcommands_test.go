package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"syscall"
	"testing"
	"time"
)

func stubQuery(t *testing.T, fn func(map[string]any, time.Duration) (map[string]any, error)) {
	t.Helper()
	previous := queryDetached
	queryDetached = fn
	t.Cleanup(func() {
		queryDetached = previous
	})
}

func captureStdout(t *testing.T, fn func() int) (int, string) {
	t.Helper()
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}

	previous := os.Stdout
	os.Stdout = writer
	code := fn()
	_ = writer.Close()
	os.Stdout = previous

	var output bytes.Buffer
	if _, err := io.Copy(&output, reader); err != nil {
		t.Fatalf("read stdout: %v", err)
	}
	return code, output.String()
}

func TestClassify_sortsProcessNames(t *testing.T) {
	procs := map[string]any{
		"worker": map[string]any{"status": "running", "ready": false},
		"plugin": map[string]any{"status": "crashed", "ready": false},
		"web":    map[string]any{"status": "pending", "ready": false},
	}

	verdict, crashed, notReady := classify(procs)

	if verdict != "crashed" {
		t.Fatalf("verdict: got %q, want %q", verdict, "crashed")
	}
	if !reflect.DeepEqual(crashed, []string{"plugin"}) {
		t.Fatalf("crashed: got %v, want %v", crashed, []string{"plugin"})
	}
	if !reflect.DeepEqual(notReady, []string{"web (pending)", "worker (running)"}) {
		t.Fatalf("notReady: got %v, want %v", notReady, []string{"web (pending)", "worker (running)"})
	}
}

func TestRunWait_jsonDaemonError(t *testing.T) {
	stubQuery(t, func(map[string]any, time.Duration) (map[string]any, error) {
		return map[string]any{"ok": false, "error": "boom"}, nil
	})

	code, output := captureStdout(t, func() int {
		return runWait(1, true)
	})

	if code != 3 {
		t.Fatalf("exit code: got %d, want 3", code)
	}
	if !strings.Contains(output, `"verdict":"not_reachable"`) {
		t.Fatalf("output missing not_reachable verdict: %q", output)
	}
	if !strings.Contains(output, `"error":"boom"`) {
		t.Fatalf("output missing daemon error: %q", output)
	}
}

func TestRunWait_shortTimeoutBeforeBindIsNotReachable(t *testing.T) {
	stubQuery(t, func(map[string]any, time.Duration) (map[string]any, error) {
		return nil, errors.New("dial unix: no such file")
	})

	code, output := captureStdout(t, func() int {
		return runWait(0, true)
	})

	if code != 3 {
		t.Fatalf("exit code: got %d, want 3", code)
	}
	if !strings.Contains(output, `"verdict":"not_reachable"`) {
		t.Fatalf("output missing not_reachable verdict: %q", output)
	}
}

func TestRunStop_quitPathRemovesPidfile(t *testing.T) {
	t.Chdir(t.TempDir())
	if err := os.MkdirAll(generatedDir(), 0o755); err != nil {
		t.Fatalf("mkdir generated dir: %v", err)
	}

	lockFile, err := os.OpenFile(pidLockFilePath(), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		t.Fatalf("open lock: %v", err)
	}
	defer func() { _ = lockFile.Close() }()
	if err := syscall.Flock(int(lockFile.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		t.Fatalf("flock: %v", err)
	}

	cmd := exec.Command("sleep", "30")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start sleep: %v", err)
	}
	t.Cleanup(func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	})

	if err := os.WriteFile(pidFilePath(), []byte(fmt.Sprintf("%d\n", cmd.Process.Pid)), 0o644); err != nil {
		t.Fatalf("write pidfile: %v", err)
	}

	sock, err := detachedSocketPath()
	if err != nil {
		t.Fatalf("detached socket path: %v", err)
	}
	ln, err := net.Listen("unix", sock)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() {
		_ = ln.Close()
		_ = os.Remove(sock)
	})

	done := make(chan struct{})
	go func() {
		defer close(done)
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()

		line, err := bufio.NewReader(conn).ReadString('\n')
		if err != nil {
			return
		}
		if !strings.Contains(line, `"cmd":"quit"`) {
			return
		}
		_, _ = conn.Write([]byte(`{"ok":true}` + "\n"))
		_ = ln.Close()
		_ = os.Remove(sock)
		_ = syscall.Flock(int(lockFile.Fd()), syscall.LOCK_UN)
	}()

	code, _ := captureStdout(t, func() int {
		return runStop(1)
	})

	if code != 0 {
		t.Fatalf("exit code: got %d, want 0", code)
	}
	if _, err := os.Stat(pidFilePath()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("pidfile should be removed, stat err=%v", err)
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("quit server did not finish")
	}
}

func TestStopViaPidfile_doesNotSignalUnlockedPidfile(t *testing.T) {
	t.Chdir(t.TempDir())
	if err := os.MkdirAll(generatedDir(), 0o755); err != nil {
		t.Fatalf("mkdir generated dir: %v", err)
	}

	cmd := exec.Command("sleep", "30")
	if err := cmd.Start(); err != nil {
		t.Fatalf("start sleep: %v", err)
	}
	t.Cleanup(func() {
		_ = cmd.Process.Kill()
		_ = cmd.Wait()
	})

	if err := os.WriteFile(pidFilePath(), []byte(fmt.Sprintf("%d\n", cmd.Process.Pid)), 0o644); err != nil {
		t.Fatalf("write pidfile: %v", err)
	}

	code, output := captureStdout(t, func() int {
		return stopViaPidfile("", time.Now().Add(time.Second))
	})

	if code != 0 {
		t.Fatalf("exit code: got %d, want 0", code)
	}
	if !strings.Contains(output, "no detached phrocs running") {
		t.Fatalf("output: got %q, want no detached message", output)
	}
	if !pidAlive(cmd.Process.Pid) {
		t.Fatalf("stale pidfile process %d was signaled", cmd.Process.Pid)
	}
	if _, err := os.Stat(pidFilePath()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("pidfile should be removed, stat err=%v", err)
	}
}

func TestStopViaPidfile_missingGeneratedDirIsIdempotent(t *testing.T) {
	t.Chdir(t.TempDir())

	code, output := captureStdout(t, func() int {
		return stopViaPidfile("", time.Now().Add(time.Second))
	})

	if code != 0 {
		t.Fatalf("exit code: got %d, want 0", code)
	}
	if !strings.Contains(output, "no detached phrocs running") {
		t.Fatalf("output: got %q, want no detached message", output)
	}
}

// Regression: a one-shot proc that exits cleanly (status="done") must not
// block `phrocs wait` forever. Pre-fix `classify` only treated "crashed" as
// terminal, so a config with any one-shot setup proc would always time out.
func TestClassify_doneCountsAsReady(t *testing.T) {
	procs := map[string]any{
		"migrate": map[string]any{"status": "done", "ready": false},
		"web":     map[string]any{"status": "running", "ready": true},
	}

	verdict, crashed, notReady := classify(procs)

	if verdict != "ready" {
		t.Fatalf("verdict: got %q, want %q", verdict, "ready")
	}
	if len(crashed) != 0 {
		t.Fatalf("crashed: got %v, want empty", crashed)
	}
	if len(notReady) != 0 {
		t.Fatalf("notReady: got %v, want empty", notReady)
	}
}

// runWait must surface an empty-config response as a distinct "no_procs"
// verdict (exit 0) rather than spinning until the deadline and printing
// "still not ready: " with an empty list.
func TestRunWait_emptyConfigReportsNoProcs(t *testing.T) {
	stubQuery(t, func(map[string]any, time.Duration) (map[string]any, error) {
		return map[string]any{"ok": true, "processes": map[string]any{}}, nil
	})

	code, _ := captureStdout(t, func() int {
		return runWait(1, true)
	})

	if code != 0 {
		t.Fatalf("exit code: got %d, want 0", code)
	}
}

// cleanIfStale must hold the pidfile flock during pidfile removal so a fresh
// `phrocs --detach` racing in between detection and cleanup can't have its
// pidfile clobbered. We exercise the contract: when the lock is already held
// elsewhere, cleanIfStale returns (false, nil) and leaves the pidfile alone.
func TestCleanIfStale_doesNotTouchLiveDetached(t *testing.T) {
	t.Chdir(t.TempDir())
	if err := os.MkdirAll(generatedDir(), 0o755); err != nil {
		t.Fatalf("mkdir generated dir: %v", err)
	}

	holder, err := os.OpenFile(pidLockFilePath(), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		t.Fatalf("open lock: %v", err)
	}
	defer func() { _ = holder.Close() }()
	if err := syscall.Flock(int(holder.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		t.Fatalf("flock: %v", err)
	}

	if err := os.WriteFile(pidFilePath(), []byte("12345\n"), 0o644); err != nil {
		t.Fatalf("write pidfile: %v", err)
	}

	cleaned, err := cleanIfStale("")
	if err != nil {
		t.Fatalf("cleanIfStale: %v", err)
	}
	if cleaned {
		t.Fatalf("cleaned: got true while lock is held; pidfile would have been clobbered")
	}
	if _, err := os.Stat(pidFilePath()); err != nil {
		t.Fatalf("pidfile should still exist, stat err=%v", err)
	}
}

func TestCleanIfStale_removesStalePidfile(t *testing.T) {
	t.Chdir(t.TempDir())
	if err := os.MkdirAll(generatedDir(), 0o755); err != nil {
		t.Fatalf("mkdir generated dir: %v", err)
	}
	// Create lock file but don't hold flock — simulates a previous detached
	// that has exited (kernel released the lock on exit).
	lf, err := os.OpenFile(pidLockFilePath(), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		t.Fatalf("create lock: %v", err)
	}
	_ = lf.Close()
	if err := os.WriteFile(pidFilePath(), []byte("99999\n"), 0o644); err != nil {
		t.Fatalf("write pidfile: %v", err)
	}

	cleaned, err := cleanIfStale("")
	if err != nil {
		t.Fatalf("cleanIfStale: %v", err)
	}
	if !cleaned {
		t.Fatalf("cleaned: got false, want true (lock was free)")
	}
	if _, err := os.Stat(pidFilePath()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("pidfile should be removed, stat err=%v", err)
	}
}
