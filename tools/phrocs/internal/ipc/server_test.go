package ipc

import (
	"bufio"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"testing"

	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// testManager builds a process.Manager from the given process names without
// starting any subprocesses.
func testManager(t *testing.T, names ...string) *process.Manager {
	t.Helper()
	procs := make(map[string]config.ProcConfig, len(names))
	for _, name := range names {
		procs[name] = config.ProcConfig{Shell: "echo " + name}
	}
	cfg := &config.Config{
		Procs:      procs,
		Scrollback: 1000,
	}
	return process.NewManager(cfg)
}

// startServe launches Listen+Serve in a background goroutine. The listener is
// cleaned up via t.Cleanup. Returns the socket path.
func startServe(t *testing.T, mgr *process.Manager) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.sock")
	ln, err := Listen(path)
	if err != nil {
		t.Fatalf("Listen: %v", err)
	}
	t.Cleanup(func() {
		_ = ln.Close()
		_ = os.Remove(path)
	})
	go func() {
		_ = Serve(ln, mgr)
	}()
	return path
}

// send connects to the socket, writes req as newline-delimited JSON, and
// reads one response line back as a map.
func send(t *testing.T, path string, req map[string]any) map[string]any {
	t.Helper()
	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}
	return sendRaw(t, path, string(data))
}

// sendRaw sends a raw string (followed by a newline) to the socket and reads
// one response line. Useful for injecting malformed JSON.
func sendRaw(t *testing.T, path string, raw string) map[string]any {
	t.Helper()
	conn, err := net.Dial("unix", path)
	if err != nil {
		t.Fatalf("dial %s: %v", path, err)
	}
	defer func() { _ = conn.Close() }()

	if _, err := conn.Write([]byte(raw + "\n")); err != nil {
		t.Fatalf("write request: %v", err)
	}

	reader := bufio.NewReader(conn)
	line, err := reader.ReadString('\n')
	if err != nil {
		t.Fatalf("read response: %v", err)
	}

	var resp map[string]any
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		t.Fatalf("unmarshal response %q: %v", line, err)
	}
	return resp
}

func TestServe_list(t *testing.T) {
	mgr := testManager(t, "web", "worker")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "list"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	procs, ok := resp["processes"].([]any)
	if !ok {
		t.Fatalf("processes: expected []any, got %T", resp["processes"])
	}
	if len(procs) != 2 {
		t.Errorf("processes length: got %d, want 2", len(procs))
	}
}

func TestServe_statusUnknown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "status", "process": "doesnotexist"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	if errMsg == "" {
		t.Fatal("error: expected non-empty error message")
	}
	const wantSubstr = "process not found"
	if !containsSubstr(errMsg, wantSubstr) {
		t.Errorf("error %q does not contain %q", errMsg, wantSubstr)
	}
}

func TestServe_statusKnown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "status", "process": "web"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	if resp["process"] != "web" {
		t.Errorf("process: got %v, want %q", resp["process"], "web")
	}
	if _, hasStatus := resp["status"]; !hasStatus {
		t.Error("response missing 'status' field")
	}
}

func TestServe_statusAll(t *testing.T) {
	mgr := testManager(t, "web", "worker")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "status_all"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	procs, ok := resp["processes"].(map[string]any)
	if !ok {
		t.Fatalf("processes: expected map[string]any, got %T", resp["processes"])
	}
	if _, hasWeb := procs["web"]; !hasWeb {
		t.Error("processes map missing 'web' key")
	}
	if _, hasWorker := procs["worker"]; !hasWorker {
		t.Error("processes map missing 'worker' key")
	}
}

func TestServe_logsEmpty(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "logs", "process": "web"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	lines, ok := resp["lines"].([]any)
	if !ok {
		t.Fatalf("lines: expected []any, got %T", resp["lines"])
	}
	if len(lines) != 0 {
		t.Errorf("lines length: got %d, want 0", len(lines))
	}
	buffered, _ := resp["buffered"].(float64)
	if buffered != 0 {
		t.Errorf("buffered: got %v, want 0", buffered)
	}
}

func TestServe_logsWithContent(t *testing.T) {
	mgr := testManager(t, "web")
	p, _ := mgr.Get("web")
	p.AppendLine("line one")
	p.AppendLine("line two")
	p.AppendLine("line three")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "logs", "process": "web", "lines": 10})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	lines, ok := resp["lines"].([]any)
	if !ok {
		t.Fatalf("lines: expected []any, got %T", resp["lines"])
	}
	if len(lines) != 3 {
		t.Errorf("lines length: got %d, want 3", len(lines))
	}
	buffered, _ := resp["buffered"].(float64)
	if buffered != 3 {
		t.Errorf("buffered: got %v, want 3", buffered)
	}
}

func TestServe_logsLineCap(t *testing.T) {
	mgr := testManager(t, "web")
	p, _ := mgr.Get("web")
	p.AppendLine("alpha")
	p.AppendLine("beta")
	p.AppendLine("gamma")
	path := startServe(t, mgr)

	// Request more lines than the 500 cap — server clamps to 500, but since
	// only 3 lines are buffered we still get 3 back (not 600).
	resp := send(t, path, map[string]any{"cmd": "logs", "process": "web", "lines": 600})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	lines, ok := resp["lines"].([]any)
	if !ok {
		t.Fatalf("lines: expected []any, got %T", resp["lines"])
	}
	if len(lines) != 3 {
		t.Errorf("lines length: got %d, want 3 (clamped to 500, buffer only has 3)", len(lines))
	}
}

func TestServe_logsGrep(t *testing.T) {
	mgr := testManager(t, "web")
	p, _ := mgr.Get("web")
	p.AppendLine("error: foo")
	p.AppendLine("info: bar")
	p.AppendLine("error: baz")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "logs", "process": "web", "lines": 100, "grep": "error"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}
	lines, ok := resp["lines"].([]any)
	if !ok {
		t.Fatalf("lines: expected []any, got %T", resp["lines"])
	}
	if len(lines) != 2 {
		t.Errorf("lines length: got %d, want 2", len(lines))
	}
	totalMatched, _ := resp["total_matched"].(float64)
	if totalMatched != 2 {
		t.Errorf("total_matched: got %v, want 2", totalMatched)
	}
}

func TestServe_unknownCommand(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "bogus"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	const wantSubstr = "unknown command"
	if !containsSubstr(errMsg, wantSubstr) {
		t.Errorf("error %q does not contain %q", errMsg, wantSubstr)
	}
}

func TestServe_invalidJSON(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := sendRaw(t, path, "not json")

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	const wantSubstr = "invalid JSON"
	if !containsSubstr(errMsg, wantSubstr) {
		t.Errorf("error %q does not contain %q", errMsg, wantSubstr)
	}
}

// containsSubstr reports whether s contains substr.
func containsSubstr(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && indexSubstr(s, substr) >= 0)
}

func indexSubstr(s, substr string) int {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return i
		}
	}
	return -1
}
