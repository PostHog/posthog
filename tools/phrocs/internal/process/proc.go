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
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/creack/pty"
	gops "github.com/shirou/gopsutil/v4/process"

	"github.com/posthog/posthog/phrocs/internal/config"
)

const metricsSampleInterval = 5 * time.Second

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
	Name      string
	Line      string
	LineIndex int  // index of this line in the buffer after the append
	Evicted   bool // true when the oldest buffered line was dropped to make room
}

// Metrics holds the most recent sampled resource usage for a process tree.
type Metrics struct {
	MemRSSMB   float64   `json:"mem_rss_mb"`
	PeakMemMB  float64   `json:"peak_mem_rss_mb"`
	CPUPercent float64   `json:"cpu_percent"`
	CPUTimeS   float64   `json:"cpu_time_s"`
	Threads    int32     `json:"thread_count"`
	Children   int       `json:"child_process_count"`
	FDs        int32     `json:"fd_count"`
	SampledAt  time.Time `json:"last_sampled_at"`
}

// Snapshot is a point-in-time view of a process suitable for serialization.
type Snapshot struct {
	Name     string `json:"process"`
	Status   string `json:"status"`
	PID      int    `json:"pid"`
	Ready    bool   `json:"ready"`
	ExitCode *int   `json:"exit_code"`

	StartedAt        time.Time  `json:"started_at"`
	ReadyAt          *time.Time `json:"ready_at,omitempty"`
	StartupDurationS *float64   `json:"startup_duration_s,omitempty"`

	// Nil until the first metrics sample arrives (~5s after start).
	MemRSSMB          *float64   `json:"mem_rss_mb"`
	PeakMemRSSMB      *float64   `json:"peak_mem_rss_mb"`
	CPUPercent        *float64   `json:"cpu_percent"`
	CPUTimeS          *float64   `json:"cpu_time_s"`
	ThreadCount       *int32     `json:"thread_count"`
	ChildProcessCount *int       `json:"child_process_count"`
	FDCount           *int32     `json:"fd_count"`
	LastSampledAt     *time.Time `json:"last_sampled_at"`
}

// Represents a single managed subprocess
type Process struct {
	Name string
	Cfg  config.ProcConfig

	mu            sync.Mutex
	maxLines      int
	status        Status
	lines         []string
	cmd           *exec.Cmd
	ptmx          *os.File // pty master; nil when using pipes
	readyPattern  *regexp.Regexp
	ready         bool // whether we've seen the ready pattern (or no pattern is set)
	stopRequested bool // set by Stop() to catch races with in-flight Start()

	startedAt time.Time
	readyAt   time.Time
	exitCode  *int
	metrics   *Metrics
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

// Directly appends a line to the output buffer, honoring the
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

// Returns a consistent point-in-time view of the process
func (p *Process) Snapshot() Snapshot {
	p.mu.Lock()
	defer p.mu.Unlock()

	snap := Snapshot{
		Name:      p.Name,
		Status:    p.status.String(),
		Ready:     p.ready,
		ExitCode:  p.exitCode,
		StartedAt: p.startedAt,
	}
	if p.cmd != nil && p.cmd.Process != nil {
		snap.PID = p.cmd.Process.Pid
	}
	if !p.readyAt.IsZero() {
		t := p.readyAt
		snap.ReadyAt = &t
		d := p.readyAt.Sub(p.startedAt).Seconds()
		snap.StartupDurationS = &d
	}
	if m := p.metrics; m != nil {
		mem := m.MemRSSMB
		peak := m.PeakMemMB
		cpu := m.CPUPercent
		cpuT := m.CPUTimeS
		thr := m.Threads
		ch := m.Children
		fds := m.FDs
		sa := m.SampledAt
		snap.MemRSSMB = &mem
		snap.PeakMemRSSMB = &peak
		snap.CPUPercent = &cpu
		snap.CPUTimeS = &cpuT
		snap.ThreadCount = &thr
		snap.ChildProcessCount = &ch
		snap.FDCount = &fds
		snap.LastSampledAt = &sa
	}
	return snap
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
	p.metrics = nil
	p.exitCode = nil
	p.startedAt = time.Now()
	p.readyAt = time.Time{}
	p.stopRequested = false
	// Reset ready flag when restarting
	p.ready = p.readyPattern == nil
	p.mu.Unlock()

	env := os.Environ()
	for k, v := range p.Cfg.Env {
		env = append(env, fmt.Sprintf("%s=%s", k, v))
	}

	cmd := exec.Command("bash", "-c", p.Cfg.Shell)
	cmd.Env = env
	// Give child its own process group so Stop() can kill the entire tree,
	// preventing zombie tsx/node/vite processes when phrocs exits.
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	ptmx, err := pty.Start(cmd)
	if err != nil {
		// Use combined stdout/stderr pipe when PTY allocation fails
		return p.startWithPipe(cmd, send)
	}

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = ptmx

	// Stop() was called while pty.Start was in progress — kill immediately
	if p.stopRequested {
		p.killProcessGroup()
		if p.ptmx != nil {
			_ = p.ptmx.Close()
			p.ptmx = nil
		}
		p.status = StatusStopped
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusStopped})
		return nil
	}

	// Only set to running if proc has no ready pattern
	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	currentStatus := p.status
	p.mu.Unlock()
	// Send initial status message
	send(StatusMsg{Name: p.Name, Status: currentStatus})

	go p.startMetricsSampler(cmd.Process.Pid)

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
			code := cmd.ProcessState.ExitCode()
			p.exitCode = &code
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
	// pty.Start may have contaminated SysProcAttr with Setsid/Setctty
	// before failing. For the pipe path we only need Setpgid so Stop() can
	// kill the full process tree via Kill(-pid, SIGTERM).
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

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

	// Stop() was called while cmd.Start was in progress — kill immediately
	if p.stopRequested {
		p.killProcessGroup()
		p.status = StatusStopped
		p.mu.Unlock()
		_ = pr.Close()
		_ = pw.Close()
		send(StatusMsg{Name: p.Name, Status: StatusStopped})
		return nil
	}

	// Only set to running if no ready pattern
	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	currentStatus := p.status
	p.mu.Unlock()
	// Send initial status message
	send(StatusMsg{Name: p.Name, Status: currentStatus})

	go p.startMetricsSampler(cmd.Process.Pid)

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
			code := cmd.ProcessState.ExitCode()
			p.exitCode = &code
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
		evicted := len(p.lines) >= p.maxLines
		if evicted {
			// Discard oldest line to keep the buffer bounded.
			p.lines = p.lines[1:]
		}
		p.lines = append(p.lines, line)
		lineIndex := len(p.lines) - 1

		// Check if this line matches the ready pattern
		shouldNotifyCh := false
		if !p.ready && p.readyPattern != nil && p.readyPattern.MatchString(line) {
			p.ready = true
			p.readyAt = time.Now()
			p.status = StatusRunning
			shouldNotifyCh = true
		}
		p.mu.Unlock()

		send(OutputMsg{Name: p.Name, Line: line, LineIndex: lineIndex, Evicted: evicted})

		// Send status update if we just became ready
		if shouldNotifyCh {
			send(StatusMsg{Name: p.Name, Status: StatusRunning})
		}
	}
}

// Sampling CPU/mem/threads every metricsSampleInterval for the process tree
func (p *Process) startMetricsSampler(pid int) {
	ps, err := gops.NewProcess(int32(pid))
	if err != nil {
		return
	}
	// First CPUPercent call initialises the measurement baseline; always 0
	_, _ = ps.CPUPercent()
	origPID := pid

	ticker := time.NewTicker(metricsSampleInterval)
	defer ticker.Stop()

	for range ticker.C {
		p.mu.Lock()
		st := p.status
		currentPID := 0
		if p.cmd != nil && p.cmd.Process != nil {
			currentPID = p.cmd.Process.Pid
		}

		p.mu.Unlock()
		if st != StatusRunning && st != StatusPending {
			return
		}
		if currentPID != 0 && currentPID != origPID {
			// Process has been restarted with a new PID
			return
		}

		all := collectProcessTree(ps)

		var rssBytes uint64
		var cpuPct, cpuTime float64
		var threads int32
		var fds int32
		for _, proc := range all {
			if mem, err := proc.MemoryInfo(); err == nil {
				rssBytes += mem.RSS
			}
			if c, err := proc.CPUPercent(); err == nil {
				cpuPct += c
			}
			if ct, err := proc.Times(); err == nil {
				cpuTime += ct.User + ct.System
			}
			if t, err := proc.NumThreads(); err == nil {
				threads += t
			}
			if f, err := proc.NumFDs(); err == nil {
				fds += f
			}
		}

		rssMB := float64(rssBytes) / 1024 / 1024

		p.mu.Lock()
		if p.metrics == nil {
			p.metrics = &Metrics{}
		}
		p.metrics.MemRSSMB = rssMB
		if rssMB > p.metrics.PeakMemMB {
			p.metrics.PeakMemMB = rssMB
		}
		p.metrics.CPUPercent = cpuPct
		p.metrics.CPUTimeS = cpuTime
		p.metrics.Threads = threads
		p.metrics.Children = len(all) - 1
		p.metrics.FDs = fds
		p.metrics.SampledAt = time.Now()
		p.mu.Unlock()
	}
}

// collectProcessTree returns ps and all its descendants via a depth-first walk.
func collectProcessTree(ps *gops.Process) []*gops.Process {
	all := []*gops.Process{ps}
	children, err := ps.Children()
	if err != nil {
		return all
	}
	for _, child := range children {
		all = append(all, collectProcessTree(child)...)
	}
	return all
}

// killProcessGroup sends SIGTERM to the process group. Must be called with
// p.mu held. Falls back to signaling the direct child if the group kill fails.
// Also walks the process tree to terminate descendants that escaped the group
// (e.g. pnpm/node processes spawned with a detached process group).
func (p *Process) killProcessGroup() {
	if p.cmd == nil || p.cmd.Process == nil {
		return
	}
	// If the tracked command has already exited, avoid signaling based on a
	// potentially reused PID.
	if p.cmd.ProcessState != nil && p.cmd.ProcessState.Exited() {
		return
	}
	pid := p.cmd.Process.Pid
	if err := syscall.Kill(-pid, syscall.SIGTERM); err != nil {
		_ = p.cmd.Process.Signal(syscall.SIGTERM)
	}
	// Walk the full process tree to catch any descendants that escaped the
	// process group (e.g. pnpm spawns node as a detached child).
	if ps, err := gops.NewProcess(int32(pid)); err == nil {
		for _, proc := range collectProcessTree(ps) {
			_ = proc.SendSignal(syscall.SIGTERM)
		}
	}
}

// Sends SIGTERM to the process group and marks it as stopped.
// Killing the process group (negative PID) ensures all descendants
// (bash → tsx watch → node, etc.) are terminated, not just the shell.
func (p *Process) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.stopRequested = true
	p.killProcessGroup()
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

// PID returns the OS PID of the running process, or 0 if not started.
func (p *Process) PID() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cmd != nil && p.cmd.Process != nil {
		return p.cmd.Process.Pid
	}
	return 0
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
