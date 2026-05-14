package ipc

import (
	"bufio"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
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
	// Use /tmp directly to keep socket paths under macOS's 104-byte limit
	dir, err := os.MkdirTemp("/tmp", "phrocs-test-*")
	if err != nil {
		t.Fatalf("MkdirTemp: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "t.sock")
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

func TestRemoveOwnedSocket_guardAgainstReplacedFile(t *testing.T) {
	dir, err := os.MkdirTemp("/tmp", "phrocs-test-*")
	if err != nil {
		t.Fatalf("MkdirTemp: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "s.sock")

	ln, err := Listen(path)
	if err != nil {
		t.Fatalf("Listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })

	actualInode := SocketInode(path)
	if actualInode == 0 {
		t.Fatal("SocketInode returned 0 for bound socket")
	}

	// Simulate a crashed detached phrocs's stale defer calling RemoveOwnedSocket
	// with an inode that doesn't match the file currently at `path` (a replacement
	// bound by a later detached phrocs). The guard must refuse to remove the file.
	// We pass actualInode+1 directly rather than rebind-at-same-path, because
	// on Linux tmpfs the freed inode often gets reused, which would defeat
	// the simulation (the "replacement" would have the same inode).
	RemoveOwnedSocket(path, actualInode+1)

	if _, err := os.Lstat(path); err != nil {
		t.Fatalf("expected socket to survive RemoveOwnedSocket with mismatched inode, got error %v", err)
	}
}

func TestRemoveOwnedSocket_removesOwnSocket(t *testing.T) {
	dir, err := os.MkdirTemp("/tmp", "phrocs-test-*")
	if err != nil {
		t.Fatalf("MkdirTemp: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	path := filepath.Join(dir, "s.sock")

	ln, err := Listen(path)
	if err != nil {
		t.Fatalf("Listen: %v", err)
	}
	inode := SocketInode(path)
	_ = ln.Close()

	RemoveOwnedSocket(path, inode)
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatalf("expected socket removed; Lstat err=%v", err)
	}
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
	if !strings.Contains(errMsg, wantSubstr) {
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
	if !strings.Contains(errMsg, wantSubstr) {
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
	if !strings.Contains(errMsg, wantSubstr) {
		t.Errorf("error %q does not contain %q", errMsg, wantSubstr)
	}
}

func TestServe_sendKeys_unknownProcess(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "send-keys", "process": "nope", "keys": "y\n"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	if !strings.Contains(errMsg, "process not found") {
		t.Errorf("error %q does not contain 'process not found'", errMsg)
	}
}

func TestServe_sendKeys_missingKeys(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "send-keys", "process": "web"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	if !strings.Contains(errMsg, "missing keys") {
		t.Errorf("error %q does not contain 'missing keys'", errMsg)
	}
}

func TestServe_addProc(t *testing.T) {
	mgr := testManager(t, "web")
	// Set a no-op send so add-proc can notify the TUI
	mgr.SetSend(func(tea.Msg) {})
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "add-proc", "process": "worker", "shell": "echo worker"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true; error: %v", resp["ok"], resp["error"])
	}
	// Verify the process was added
	_, ok := mgr.Get("worker")
	if !ok {
		t.Error("process 'worker' should exist after add-proc")
	}
}

func TestServe_addProc_duplicate(t *testing.T) {
	mgr := testManager(t, "web")
	mgr.SetSend(func(tea.Msg) {})
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "add-proc", "process": "web", "shell": "echo web"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	if !strings.Contains(errMsg, "already exists") {
		t.Errorf("error %q does not contain 'already exists'", errMsg)
	}
}

func TestServe_addProc_missingFields(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "add-proc"})
	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false for missing name", resp["ok"])
	}

	resp = send(t, path, map[string]any{"cmd": "add-proc", "process": "worker"})
	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false for missing shell", resp["ok"])
	}
}

func TestServe_removeProc(t *testing.T) {
	mgr := testManager(t, "web", "worker")
	mgr.SetSend(func(tea.Msg) {})
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "remove-proc", "process": "worker"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true; error: %v", resp["ok"], resp["error"])
	}
	_, ok := mgr.Get("worker")
	if ok {
		t.Error("process 'worker' should be removed after remove-proc")
	}
}

func TestServe_removeProc_unknown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "remove-proc", "process": "nope"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
	errMsg, _ := resp["error"].(string)
	if !strings.Contains(errMsg, "process not found") {
		t.Errorf("error %q does not contain 'process not found'", errMsg)
	}
}

func TestServe_focus(t *testing.T) {
	mgr := testManager(t, "web", "worker")
	var focused string
	mgr.SetSend(func(msg tea.Msg) {
		if fm, ok := msg.(process.FocusMsg); ok {
			focused = fm.Name
		}
	})
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "focus", "process": "worker"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true; error: %v", resp["ok"], resp["error"])
	}
	if focused != "worker" {
		t.Errorf("FocusMsg name: got %q, want %q", focused, "worker")
	}
}

func TestServe_focus_unknown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "focus", "process": "nope"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
}

func TestServe_toggleProc_unknown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "toggle-proc", "process": "nope"})

	if resp["ok"] != false {
		t.Fatalf("ok: got %v, want false", resp["ok"])
	}
}

func TestServe_toggleProc_stoppedProcess(t *testing.T) {
	mgr := testManager(t, "web")
	mgr.SetSend(func(tea.Msg) {})
	path := startServe(t, mgr)

	// Process starts as stopped; toggle should succeed (attempts to start it)
	resp := send(t, path, map[string]any{"cmd": "toggle-proc", "process": "web"})

	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true; error: %v", resp["ok"], resp["error"])
	}
}

func TestServe_quit(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	resp := send(t, path, map[string]any{"cmd": "quit"})
	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}

	select {
	case <-mgr.QuitCh():
	case <-time.After(time.Second):
		t.Fatal("QuitCh not closed after quit command")
	}
}

func TestServe_quit_idempotent(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	for i := 0; i < 3; i++ {
		resp := send(t, path, map[string]any{"cmd": "quit"})
		if resp["ok"] != true {
			t.Fatalf("quit #%d ok: got %v, want true", i, resp["ok"])
		}
	}
	select {
	case <-mgr.QuitCh():
	case <-time.After(time.Second):
		t.Fatal("QuitCh not closed")
	}
}

// TestServe_quit_replyBeforeShutdown guards against the detached main loop
// closing QuitCh before the quit reply is flushed. The race was real:
// `dispatch` used to call `mgr.Quit()` inline, so the detached main loop
// could tear down before `writeJSON` returned. Regression test: read the
// quit reply and assert it arrived before QuitCh was observed closed.
func TestServe_quit_replyBeforeShutdown(t *testing.T) {
	mgr := testManager(t, "web")
	path := startServe(t, mgr)

	conn, err := net.Dial("unix", path)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer func() { _ = conn.Close() }()

	if _, err := conn.Write([]byte(`{"cmd":"quit"}` + "\n")); err != nil {
		t.Fatalf("write: %v", err)
	}

	// At this point either the reply or the QuitCh close may be observable
	// first. Read the reply line — it must succeed with ok:true, proving
	// the server wrote it before signaling shutdown.
	_ = conn.SetReadDeadline(time.Now().Add(time.Second))
	line, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		t.Fatalf("read reply (race regressed?): %v", err)
	}
	var resp map[string]any
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		t.Fatalf("unmarshal %q: %v", line, err)
	}
	if resp["ok"] != true {
		t.Fatalf("ok: got %v, want true", resp["ok"])
	}

	// And confirm QuitCh eventually closes — the dispatch side effect.
	select {
	case <-mgr.QuitCh():
	case <-time.After(time.Second):
		t.Fatal("QuitCh not closed after quit reply")
	}
}
