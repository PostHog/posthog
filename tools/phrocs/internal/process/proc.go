package process

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"syscall"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/creack/pty"
	"github.com/posthog/posthog/phrocs/internal/config"
)

type Status int

const (
	StatusPending Status = iota
	StatusRunning
	StatusStopped
	StatusDone
	StatusCrashed
)

func (s Status) String() string {
	switch s {
	case StatusPending:
		return "pending"
	case StatusRunning:
		return "running"
	case StatusStopped:
		return "stopped"
	case StatusDone:
		return "done"
	case StatusCrashed:
		return "crashed"
	default:
		return "unknown"
	}
}

// Process state change
type StatusMsg struct {
	Name   string
	Status Status
}

// New output line from process
type OutputMsg struct {
	Name string
	Line string
}

// Represents a single managed subprocess
type Process struct {
	Name string
	Cfg  config.ProcConfig

	mu           sync.Mutex
	maxLines     int
	status       Status
	lines        []string
	cmd          *exec.Cmd
	ptmx         *os.File // pty master; nil when using pipes
	readyPattern *regexp.Regexp
	ready        bool // whether we've seen the ready pattern (or no pattern is set)
}

func NewProcess(name string, cfg config.ProcConfig, scrollback int) *Process {
	p := &Process{
		Name:     name,
		Cfg:      cfg,
		maxLines: scrollback,
		status:   StatusStopped,
		ready:    cfg.ReadyPattern == "", // ready if no pattern, otherwise wait for pattern
	}
	// Compile ready pattern if one exists
	if cfg.ReadyPattern != "" {
		if re, err := regexp.Compile(cfg.ReadyPattern); err == nil {
			p.readyPattern = re
		}
	}
	return p
}

func (p *Process) Status() Status {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.status
}

// Returns a copy of the output lines
func (p *Process) Lines() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	cp := make([]string, len(p.lines))
	copy(cp, p.lines)
	return cp
}

// AppendLine directly appends a line to the output buffer, honoring the
// scrollback limit. Mirrors the append step in readLoop; intended for tests
// that inject output without running a real subprocess.
func (p *Process) AppendLine(line string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.lines) >= p.maxLines {
		p.lines = p.lines[1:]
	}
	p.lines = append(p.lines, line)
}

// It's safe to call Start concurrently as running process is a no-op
func (p *Process) Start(send func(tea.Msg)) error {
	p.mu.Lock()
	if p.status == StatusRunning {
		p.mu.Unlock()
		return nil
	}
	p.status = StatusPending
	p.lines = nil
	// Reset ready flag when restarting
	p.ready = p.readyPattern == nil
	p.mu.Unlock()

	// If tmux is installed, use tmux instead of PTY for better interactivity
	if _, err := exec.LookPath("tmux"); err == nil {
		return p.startTmux(send)
	}

	// Fall back to PTY if tmux is not available

	// env := os.Environ()
	// for k, v := range p.Cfg.Env {
	// 	env = append(env, fmt.Sprintf("%s=%s", k, v))
	// }

	// cmd := exec.Command("bash", "-c", p.Cfg.Shell)
	// cmd.Env = env

	// ptmx, err := pty.Start(cmd)
	// if err != nil {
	// 	// Use combined stdout/stderr pipe when PTY allocation fails
	// 	return p.startWithPipe(cmd, send)
	// }

	// p.mu.Lock()
	// p.cmd = cmd
	// p.ptmx = ptmx
	// // Only set to running if proc has no ready pattern
	// if p.readyPattern == nil {
	// 	p.status = StatusRunning
	// }
	// currentStatus := p.status
	// p.mu.Unlock()
	// // Send initial status message
	// send(StatusMsg{Name: p.Name, Status: currentStatus})

	// readDone := make(chan struct{})
	// go func() {
	// 	p.readLoop(ptmx, send)
	// 	close(readDone)
	// }()

	// go func() {
	// 	exitErr := cmd.Wait()

	// 	// Close the pty master to unblock readLoop if still reading
	// 	p.mu.Lock()
	// 	if p.ptmx != nil {
	// 		_ = p.ptmx.Close()
	// 		p.ptmx = nil
	// 	}
	// 	p.mu.Unlock()

	// 	// Wait for readLoop to drain all buffered output before updating status
	// 	<-readDone

	// 	st := StatusDone
	// 	if exitErr != nil {
	// 		st = StatusCrashed
	// 	}
	// 	p.mu.Lock()
	// 	// Don't update status if this cmd is no longer the active one
	// 	// (process was restarted) or if an explicit Stop() was called
	// 	if p.cmd == cmd && p.status != StatusStopped {
	// 		p.status = st
	// 	}
	// 	finalStatus := p.status
	// 	shouldRestart := p.cmd == cmd && p.Cfg.Autorestart && st == StatusCrashed
	// 	p.mu.Unlock()

	// 	send(StatusMsg{Name: p.Name, Status: finalStatus})

	// 	if shouldRestart {
	// 		_ = p.Start(send)
	// 	}
	// }()

	return nil
}

// Launches the process in a tmux session instead of a direct PTY
func (p *Process) startTmux(send func(tea.Msg)) error {
	// Use a global "phrocs" session for all processes, with windows named after processes
	sessionName := "phrocs"
	windowName := p.Name

	// Ensure tmux is installed
	if _, err := exec.LookPath("tmux"); err != nil {
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return fmt.Errorf("tmux not installed: %w", err)
	}

	// Create or reuse tmux session (idempotent)
	createSessionCmd := exec.Command("tmux", "new-session", "-d", "-s", sessionName)
	_ = createSessionCmd.Run() // Ignore error if session already exists

	// Create window in the session
	createWindowCmd := exec.Command("tmux", "new-window", "-t", fmt.Sprintf("%s:", sessionName), "-n", windowName)
	if err := createWindowCmd.Run(); err != nil {
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return fmt.Errorf("failed to create tmux window: %w", err)
	}

	// Prepare environment as semicolon-separated export statements
	var envPrefix strings.Builder
	for k, v := range p.Cfg.Env {
		envPrefix.WriteString(fmt.Sprintf("export %s=%s; ", k, v))
	}

	// Send the command to the window
	targetWindow := fmt.Sprintf("%s:%s", sessionName, windowName)
	shellCmd := envPrefix.String() + p.Cfg.Shell
	sendKeysCmd := exec.Command("tmux", "send-keys", "-t", targetWindow, shellCmd, "Enter")
	if err := sendKeysCmd.Run(); err != nil {
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return fmt.Errorf("failed to send command to tmux window: %w", err)
	}

	p.mu.Lock()
	p.status = StatusRunning
	p.mu.Unlock()
	send(StatusMsg{Name: p.Name, Status: StatusRunning})

	// Start polling for output
	go p.readTmuxOutput(sessionName, windowName, send)

	// Start polling for status (window exists)
	go p.statusTmuxPoller(sessionName, windowName, send)

	return nil
}

// Polls tmux for output updates every 100ms
func (p *Process) readTmuxOutput(sessionName, windowName string, send func(tea.Msg)) {
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	var lastOutput string

	for range ticker.C {
		targetWindow := fmt.Sprintf("%s:%s", sessionName, windowName)
		captureCmd := exec.Command("tmux", "capture-pane", "-p", "-t", targetWindow, "-S", "-1000")
		out, err := captureCmd.Output()
		if err != nil {
			// Window might be gone or other error; stop polling
			return
		}

		currentOutput := string(out)

		// Diff against last capture to find new lines
		if currentOutput != lastOutput {
			// Split into lines
			currentLines := strings.Split(strings.TrimRight(currentOutput, "\n"), "\n")

			p.mu.Lock()
			// Keep only new lines that aren't already in our buffer
			startIdx := len(p.lines)
			for _, line := range currentLines {
				if len(p.lines) >= p.maxLines {
					p.lines = p.lines[1:]
				}
				p.lines = append(p.lines, line)
			}
			p.mu.Unlock()

			// Send OutputMsg for each new line
			for i := startIdx; i < len(currentLines); i++ {
				send(OutputMsg{Name: p.Name, Line: currentLines[i]})
			}

			lastOutput = currentOutput
		}
	}
}

// Periodically checks if the tmux window still exists
func (p *Process) statusTmuxPoller(sessionName, windowName string, send func(tea.Msg)) {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for range ticker.C {
		listCmd := exec.Command("tmux", "list-windows", "-t", sessionName, "-F", "#{window_name}")
		out, err := listCmd.Output()

		windowExists := err == nil && strings.Contains(string(out), windowName)

		p.mu.Lock()
		currentStatus := p.status

		if !windowExists && (currentStatus == StatusRunning || currentStatus == StatusPending) {
			p.status = StatusCrashed
			currentStatus = StatusCrashed
		}
		p.mu.Unlock()

		if !windowExists && (currentStatus == StatusRunning || currentStatus == StatusPending) {
			send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		}
	}
}

// Falls back to stdout/stderr pipes when PTY allocation fails
func (p *Process) startWithPipe(cmd *exec.Cmd, send func(tea.Msg)) error {
	pr, pw, err := os.Pipe()
	if err != nil {
		return err
	}
	cmd.Stdout = pw
	cmd.Stderr = pw

	if err := cmd.Start(); err != nil {
		_ = pr.Close()
		_ = pw.Close()
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return err
	}

	p.mu.Lock()
	p.cmd = cmd
	// Only set to running if no ready pattern
	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	p.mu.Unlock()

	p.mu.Lock()
	currentStatus := p.status
	p.mu.Unlock()
	// Send initial status message
	send(StatusMsg{Name: p.Name, Status: currentStatus})

	readDone := make(chan struct{})
	go func() {
		p.readLoop(pr, send)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()
		// Close the write end so readLoop sees EOF
		_ = pw.Close()

		<-readDone
		_ = pr.Close()

		st := StatusDone
		if exitErr != nil {
			st = StatusCrashed
		}
		p.mu.Lock()
		// Don't update status if this cmd is no longer the active one
		// (process was restarted) or if an explicit Stop() was called
		if p.cmd == cmd && p.status != StatusStopped {
			p.status = st
		}
		finalStatus := p.status
		shouldRestart := p.cmd == cmd && p.Cfg.Autorestart && st == StatusCrashed
		p.mu.Unlock()

		send(StatusMsg{Name: p.Name, Status: finalStatus})

		if shouldRestart {
			_ = p.Start(send)
		}
	}()

	return nil
}

// Scans line by line, appending to the output buffer and sending OutputMsgs
func (p *Process) readLoop(r io.Reader, send func(tea.Msg)) {
	// Larger buffer to handle long lines (like minified JS error traces)
	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 256*1024), 256*1024)

	for scanner.Scan() {
		line := scanner.Text()
		p.mu.Lock()
		if len(p.lines) >= p.maxLines {
			// Discard oldest line to keep the buffer bounded.
			p.lines = p.lines[1:]
		}
		p.lines = append(p.lines, line)

		// Check if this line matches the ready pattern
		shouldNotifyCh := false
		if !p.ready && p.readyPattern != nil && p.readyPattern.MatchString(line) {
			p.ready = true
			p.status = StatusRunning
			shouldNotifyCh = true
		}
		p.mu.Unlock()

		send(OutputMsg{Name: p.Name, Line: line})

		// Send status update if we just became ready
		if shouldNotifyCh {
			send(StatusMsg{Name: p.Name, Status: StatusRunning})
		}
	}
}

// Sends SIGTERM to the process and marks it as stopped
func (p *Process) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()

	// For tmux processes, send Ctrl-C to the window (if tmux is available)
	if _, err := exec.LookPath("tmux"); err == nil {
		sessionName := "phrocs"
		windowName := p.Name
		targetWindow := fmt.Sprintf("%s:%s", sessionName, windowName)
		// Send Ctrl-C to gracefully stop the process
		_ = exec.Command("tmux", "send-keys", "-t", targetWindow, "C-c").Run()
	}

	// For PTY-based processes, use the normal exit flow
	if p.cmd != nil && p.cmd.Process != nil {
		_ = p.cmd.Process.Signal(syscall.SIGTERM)
	}
	if p.ptmx != nil {
		_ = p.ptmx.Close()
		p.ptmx = nil
	}
	p.status = StatusStopped
}

// Stops the process, clears its output buffer, and starts it again
func (p *Process) Restart(send func(tea.Msg)) {
	p.Stop()
	send(StatusMsg{Name: p.Name, Status: StatusStopped})
	_ = p.Start(send)
}

// Updates the pty window size to keep output correctly reflowed
func (p *Process) Resize(cols, rows uint16) {
	p.mu.Lock()
	ptmx := p.ptmx
	p.mu.Unlock()
	if ptmx != nil {
		_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
	}
}
