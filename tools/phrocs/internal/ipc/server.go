// Package ipc exposes phrocs process data over a Unix domain socket so
// external tools (e.g. the dev-env MCP server) can query logs and status
// without any file-based intermediary.
//
// Protocol: newline-delimited JSON over a stream socket at SocketPath.
//
// Requests (one JSON object per line):
//
//	{"cmd":"list"}
//	{"cmd":"status","process":"web"}
//	{"cmd":"status_all"}
//	{"cmd":"logs","process":"web","lines":100,"grep":"error"}
//
// Responses (one JSON object per line):
//
//	{"ok":true,"processes":["web","worker"]}
//	{"ok":true,"process":"web","status":"running","pid":1234,...}
//	{"ok":true,"processes":{"web":{...},"worker":{...}}}
//	{"ok":true,"lines":["..."],"buffered":4832}
//	{"ok":false,"error":"process not found: web"}
package ipc

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"syscall"

	"github.com/posthog/posthog/phrocs/internal/process"
)

// SocketPathFor returns the Unix socket path for the given workspace directory.
// The path is stable (hash of the real absolute dir) so multiple phrocs
// instances — one per workspace — can coexist without collision.
func SocketPathFor(dir string) string {
	real, err := filepath.EvalSymlinks(dir)
	if err != nil {
		real = dir
	}
	abs, err := filepath.Abs(real)
	if err != nil {
		abs = real
	}
	sum := sha256.Sum256([]byte(abs))
	return "/tmp/phrocs-" + hex.EncodeToString(sum[:4]) + ".sock"
}

type request struct {
	Cmd     string `json:"cmd"`
	Process string `json:"process,omitempty"`
	Lines   int    `json:"lines,omitempty"`
	Grep    string `json:"grep,omitempty"`
}

// Binds a Unix domain socket at path and returns the listener.
// It removes any stale socket owned by the current user before binding.
// The caller is responsible for closing the listener and removing the socket file.
func Listen(path string) (net.Listener, error) {
	// Only remove an existing socket file if it is a Unix socket owned by the
	// current user. This avoids clobbering arbitrary files in /tmp.
	if fi, err := os.Lstat(path); err == nil {
		if fi.Mode()&os.ModeSocket == 0 {
			return nil, fmt.Errorf("ipc: existing path is not a socket: %s", path)
		}
		if stat, ok := fi.Sys().(*syscall.Stat_t); ok {
			if stat.Uid != uint32(os.Getuid()) {
				return nil, fmt.Errorf("ipc: existing socket not owned by current user: %s", path)
			}
		}
		if err := os.Remove(path); err != nil {
			return nil, err
		}
	}

	ln, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	// Restrict socket permissions so only the owner can connect, independent of umask
	if err := os.Chmod(path, 0o600); err != nil {
		_ = ln.Close()
		return nil, err
	}
	return ln, nil
}

// Accepts connections on ln and handles requests using mgr.
// Blocks until the listener is closed; intended to be run in a goroutine.
func Serve(ln net.Listener, mgr *process.Manager) error {
	for {
		conn, err := ln.Accept()
		if err != nil {
			return err
		}
		go handle(conn, mgr)
	}
}

func handle(conn net.Conn, mgr *process.Manager) {
	defer func() { _ = conn.Close() }()
	scanner := bufio.NewScanner(conn)
	for scanner.Scan() {
		var req request
		if err := json.Unmarshal(scanner.Bytes(), &req); err != nil {
			writeJSON(conn, map[string]any{"ok": false, "error": "invalid JSON"})
			continue
		}
		writeJSON(conn, dispatch(req, mgr))
	}
}

func dispatch(req request, mgr *process.Manager) any {
	switch req.Cmd {
	case "list":
		procs := mgr.Procs()
		names := make([]string, 0, len(procs))
		for _, p := range procs {
			names = append(names, p.Name)
		}
		return map[string]any{"ok": true, "processes": names}

	case "status":
		p, ok := mgr.Get(req.Process)
		if !ok {
			return map[string]any{"ok": false, "error": "process not found: " + req.Process}
		}
		return okSnapshot{OK: true, Snapshot: p.Snapshot()}

	case "status_all":
		procs := mgr.Procs()
		result := make(map[string]any, len(procs))
		for _, p := range procs {
			result[p.Name] = p.Snapshot()
		}
		return map[string]any{"ok": true, "processes": result}

	case "logs":
		p, ok := mgr.Get(req.Process)
		if !ok {
			return map[string]any{"ok": false, "error": "process not found: " + req.Process}
		}
		n := req.Lines
		if n <= 0 {
			n = 100
		}
		if n > 500 {
			n = 500
		}
		all := p.Lines()
		if req.Grep != "" {
			re, err := regexp.Compile(req.Grep)
			if err != nil {
				return map[string]any{"ok": false, "error": "invalid grep pattern: " + err.Error()}
			}
			matched := make([]string, 0)
			for _, l := range all {
				if re.MatchString(l) {
					matched = append(matched, l)
				}
			}
			tail := matched
			if len(tail) > n {
				tail = tail[len(tail)-n:]
			}
			return map[string]any{
				"ok":            true,
				"lines":         tail,
				"total_matched": len(matched),
				"buffered":      len(all),
			}
		}
		tail := all
		if len(tail) > n {
			tail = tail[len(tail)-n:]
		}
		return map[string]any{
			"ok":       true,
			"lines":    tail,
			"buffered": len(all),
		}

	default:
		return map[string]any{"ok": false, "error": "unknown command: " + req.Cmd}
	}
}

// Wraps a Snapshot with an "ok" field for the wire protocol.
type okSnapshot struct {
	OK bool `json:"ok"`
	process.Snapshot
}

func writeJSON(conn net.Conn, v any) {
	data, _ := json.Marshal(v)
	data = append(data, '\n')
	_, _ = conn.Write(data)
}
