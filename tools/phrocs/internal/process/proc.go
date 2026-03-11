package process

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"sync"
	"syscall"

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

	env := os.Environ()
	for k, v := range p.Cfg.Env {
		env = append(env, fmt.Sprintf("%s=%s", k, v))
	}

	cmd := exec.Command("bash", "-c", p.Cfg.Shell)
	cmd.Env = env

	ptmx, err := pty.Start(cmd)
	if err != nil {
		// Use combined stdout/stderr pipe when PTY allocation fails
		return p.startWithPipe(cmd, send)
	}

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = ptmx
	// Only set to running if proc has no ready pattern
	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	currentStatus := p.status
	p.mu.Unlock()
	// Send initial status message
	send(StatusMsg{Name: p.Name, Status: currentStatus})

	readDone := make(chan struct{})
	go func() {
		p.readLoop(ptmx, send)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()

		// Close the pty master to unblock readLoop if still reading
		p.mu.Lock()
		if p.ptmx != nil {
			_ = p.ptmx.Close()
			p.ptmx = nil
		}
		p.mu.Unlock()

		// Wait for readLoop to drain all buffered output before updating status
		<-readDone

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
