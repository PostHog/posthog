package main

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/ipc"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// generatedDir returns the repository-local path for generated artifacts
// (pidfile, per-process logs, detached stdio log). Relative to CWD, which for
// bin/start is always the repo root.
func generatedDir() string {
	return filepath.Join(".posthog", ".generated")
}

func logDir() string          { return filepath.Join(generatedDir(), "logs") }
func pidFilePath() string     { return filepath.Join(generatedDir(), "phrocs.pid") }
func pidLockFilePath() string { return pidFilePath() + ".lock" }

// runDetached either forks into a detached child (when run from the user's shell)
// or becomes the detached main loop (when re-exec'd with PHROCS_DETACHED_CHILD=1).
//
// Fork protocol:
//   - Parent: spawn self with Setsid, PHROCS_DETACHED_CHILD=1, stdio redirected
//     to <logDir>/phrocs.log. Wait up to 5s for child to bind the IPC socket.
//   - Child: write pidfile, bind IPC socket, start all procs, block on
//     SIGTERM/SIGHUP or {"cmd":"quit"}, clean up.
func runDetached(configPath string) int {
	if os.Getenv(detachedChildEnv) != "1" {
		return spawnDetached(configPath)
	}
	return detachedMain(configPath)
}

// spawnDetached re-execs the current binary with Setsid + env marker so the
// child detaches from our session. The parent returns as soon as the child's
// IPC socket is reachable (or 5s elapses with a failure).
func spawnDetached(configPath string) int {
	wd, err := os.Getwd()
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: getwd: %v\n", err)
		return 1
	}

	// Quick liveness check: if a detached phrocs is already bound at our socket
	// path, refuse to start a second one so we don't leave orphans.
	socketPath := ipc.SocketPathFor(wd)
	if conn, err := net.DialTimeout("unix", socketPath, 200*time.Millisecond); err == nil {
		_ = conn.Close()
		fmt.Fprintf(os.Stderr, "phrocs: detached phrocs already running (socket %s is live)\n", socketPath)
		return 1
	}

	if err := os.MkdirAll(logDir(), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: mkdir logs: %v\n", err)
		return 1
	}
	logPath := filepath.Join(logDir(), "phrocs.log")
	logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: open detached log: %v\n", err)
		return 1
	}

	exe, err := os.Executable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: resolve executable: %v\n", err)
		_ = logFile.Close()
		return 1
	}

	childArgs := []string{"--detach"}
	if configPath != "" {
		childArgs = append(childArgs, "--config", configPath)
	}

	cmd := exec.Command(exe, childArgs...)
	cmd.Env = append(os.Environ(), detachedChildEnv+"=1")
	cmd.Stdin = nil
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := cmd.Start(); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: spawn detached: %v\n", err)
		_ = logFile.Close()
		return 1
	}
	// Parent doesn't need the log fd.
	_ = logFile.Close()
	// Don't Wait — we're leaving the child detached. Release it from the
	// process table with a go cmd.Wait() so it doesn't linger as a zombie
	// until the parent exits (this process is about to exit anyway, but
	// this keeps ps output clean if the exit is delayed).
	go func() { _ = cmd.Wait() }()

	// Poll the socket so we only return success when the child is reachable.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if conn, err := net.DialTimeout("unix", socketPath, 100*time.Millisecond); err == nil {
			_ = conn.Close()
			fmt.Printf("phrocs detached (pid %d, socket %s, log %s)\n",
				cmd.Process.Pid, socketPath, logPath)
			return 0
		}
		time.Sleep(50 * time.Millisecond)
	}
	fmt.Fprintf(os.Stderr, "phrocs: detached child did not bind socket within 5s; check %s\n", logPath)
	return 1
}

// detachedMain is what the re-exec'd child runs: pidfile, IPC, processes, signals.
// Returns exit code.
func detachedMain(configPath string) int {
	resolved, err := config.ResolveConfigPath(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}
	cfg, err := config.Load(resolved)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: load config: %v\n", err)
		return 1
	}

	if err := os.MkdirAll(generatedDir(), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: mkdir generated: %v\n", err)
		return 1
	}
	pidPath := pidFilePath()

	// Take an exclusive flock on the pidfile before binding the socket so two
	// racing `phrocs --detach` invocations can't both succeed. The kernel
	// releases the lock on process exit, so a SIGKILLed child doesn't leave
	// the lock stranded. The fd stays open for the child's lifetime.
	lockFile, err := os.OpenFile(pidLockFilePath(), os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: open lock: %v\n", err)
		return 1
	}
	if err := syscall.Flock(int(lockFile.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: another detached phrocs is already running\n")
		_ = lockFile.Close()
		return 1
	}
	defer func() { _ = lockFile.Close() }()

	if err := os.WriteFile(pidPath, []byte(fmt.Sprintf("%d\n", os.Getpid())), 0o644); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: write pidfile: %v\n", err)
		return 1
	}
	defer func() { _ = os.Remove(pidPath) }()

	wd, err := os.Getwd()
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: getwd: %v\n", err)
		return 1
	}
	socketPath := ipc.SocketPathFor(wd)
	ln, err := ipc.Listen(socketPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: ipc listen: %v\n", err)
		return 1
	}
	ownerInode := ipc.SocketInode(socketPath)
	defer func() {
		_ = ln.Close()
		ipc.RemoveOwnedSocket(socketPath, ownerInode)
	}()

	mgr := process.NewManager(cfg)
	// Enable per-proc log files so crash diagnostics survive without a TUI.
	absLogDir, err := filepath.Abs(logDir())
	if err == nil {
		for _, p := range mgr.Procs() {
			p.SetLogDir(absLogDir)
		}
	}
	// No-op send: no TUI to notify. StatusMsg / OutputMsg / MetricsMsg are
	// discarded. Status is still queryable via IPC.
	mgr.SetSend(func(tea.Msg) {})

	go func() { _ = ipc.Serve(ln, mgr) }()
	go mgr.StartAll()

	sigCh := make(chan os.Signal, 1)
	// SIGINT normally won't reach a Setsid-detached process, but handle it so
	// that explicit `kill -INT <pid>` still runs StopAll and doesn't orphan
	// child processes.
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGHUP, syscall.SIGINT)

	select {
	case <-sigCh:
	case <-mgr.QuitCh():
	}
	mgr.StopAll()
	return 0
}
