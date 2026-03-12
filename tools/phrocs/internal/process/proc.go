package process

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"syscall"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/ansi"
	"github.com/charmbracelet/x/vt"
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

// Represents a single managed subprocess. Output is processed through a
// virtual terminal emulator (charmbracelet/x/vt) so ANSI escape sequences
// like cursor movement, line erasure, and progress bar animations render
// correctly instead of corrupting the line buffer.
type Process struct {
	Name string
	Cfg  config.ProcConfig

	mu           sync.Mutex
	maxLines     int
	status       Status
	vterm        *vt.Emulator
	vtermW       int // last known width
	vtermH       int // last known height
	cmd          *exec.Cmd
	ptmx         *os.File // pty master; nil when using pipes
	readyPattern *regexp.Regexp
	ready        bool // whether we've seen the ready pattern (or no pattern is set)
}

func NewProcess(name string, cfg config.ProcConfig, scrollback int) *Process {
	em := vt.NewEmulator(80, 24)
	em.SetScrollbackSize(scrollback)

	p := &Process{
		Name:     name,
		Cfg:      cfg,
		maxLines: scrollback,
		status:   StatusStopped,
		vterm:    em,
		vtermW:   80,
		vtermH:   24,
		ready:    cfg.ReadyPattern == "",
	}
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

// Returns output lines extracted from the virtual terminal emulator.
// Scrollback lines (historical content) are plain text; current screen
// lines preserve ANSI styling for colors and formatting.
func (p *Process) Lines() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.vterm == nil {
		return nil
	}

	var lines []string

	// Historical content that scrolled off the top of the screen
	sb := p.vterm.Scrollback()
	if sb != nil {
		for i := range sb.Len() {
			sbLine := sb.Line(i)
			var buf strings.Builder
			for _, cell := range sbLine {
				if cell.Content != "" {
					buf.WriteString(cell.Content)
				}
			}
			lines = append(lines, buf.String())
		}
	}

	// Current screen content with ANSI styling preserved
	render := p.vterm.Render()
	screenLines := strings.Split(render, "\n")
	for len(screenLines) > 0 {
		last := screenLines[len(screenLines)-1]
		if strings.TrimSpace(ansi.Strip(last)) == "" {
			screenLines = screenLines[:len(screenLines)-1]
		} else {
			break
		}
	}
	lines = append(lines, screenLines...)

	return lines
}

// AppendLine writes a line to the virtual terminal emulator. Intended for
// tests that inject output without running a real subprocess.
func (p *Process) AppendLine(line string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.vterm != nil {
		if _, err := p.vterm.WriteString(line + "\n"); err != nil {
			fmt.Fprintf(os.Stderr, "error writing to vterm: %v\n", err)
		}
	}
}

// It's safe to call Start concurrently as running process is a no-op
func (p *Process) Start(send func(tea.Msg)) error {
	p.mu.Lock()
	if p.status == StatusRunning {
		p.mu.Unlock()
		return nil
	}
	p.status = StatusPending
	// Reset vterm for fresh output
	if p.vterm != nil {
		_ = p.vterm.Close()
	}
	p.vterm = vt.NewEmulator(p.vtermW, p.vtermH)
	p.vterm.SetScrollbackSize(p.maxLines)
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
		return err
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

// Reads raw bytes from the process output and feeds them into the virtual
// terminal emulator, which correctly handles ANSI escape sequences like
// cursor movement, line erasure, and progress bar animations.
func (p *Process) readLoop(r io.Reader, send func(tea.Msg)) {
	buf := make([]byte, 32*1024)
	// Keep a bounded trailing window so readyPattern can match across read()
	// chunk boundaries (e.g. "server sta" + "rted").
	const readyMatchWindow = 4 * 1024
	var tail []byte
	for {
		n, err := r.Read(buf)
		if n > 0 {
			chunk := buf[:n]

			p.mu.Lock()
			if p.vterm != nil {
				_, _ = p.vterm.Write(chunk)
			}

			shouldNotify := false
			if !p.ready && p.readyPattern != nil {
				matched := p.readyPattern.Match(chunk)
				if !matched && len(tail) > 0 {
					combined := append(append(make([]byte, 0, len(tail)+len(chunk)), tail...), chunk...)
					matched = p.readyPattern.Match(combined)
				}
				if matched {
					p.ready = true
					p.status = StatusRunning
					shouldNotify = true
					tail = nil
				} else {
					tail = append(tail, chunk...)
					if len(tail) > readyMatchWindow {
						tail = append([]byte(nil), tail[len(tail)-readyMatchWindow:]...)
					}
				}
			}
			p.mu.Unlock()

			send(OutputMsg{Name: p.Name})

			if shouldNotify {
				send(StatusMsg{Name: p.Name, Status: StatusRunning})
			}
		}
		if err != nil {
			break
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

// Updates the pty window size and vterm dimensions to keep output correctly
// reflowed and ensure the virtual terminal matches the display area.
func (p *Process) Resize(cols, rows uint16) {
	p.mu.Lock()
	ptmx := p.ptmx
	p.vtermW = int(cols)
	p.vtermH = int(rows)
	if p.vterm != nil {
		p.vterm.Resize(int(cols), int(rows))
	}
	p.mu.Unlock()
	if ptmx != nil {
		_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
	}
}
