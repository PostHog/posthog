package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"reflect"
	"strings"
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
