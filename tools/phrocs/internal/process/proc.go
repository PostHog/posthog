package process

import (
	"bytes"
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
const flushInterval = 16 * time.Millisecond
const stopGracePeriod = 3 * time.Second

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

type StatusMsg struct {
	Name   string
	Status Status
}

// Batched output notification for incremental viewport updates.
type OutputMsg struct {
	Name    string
	Added   []string
	Evicted int
}

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

	MemRSSMB          *float64   `json:"mem_rss_mb"`
	PeakMemRSSMB      *float64   `json:"peak_mem_rss_mb"`
	CPUPercent        *float64   `json:"cpu_percent"`
	CPUTimeS          *float64   `json:"cpu_time_s"`
	ThreadCount       *int32     `json:"thread_count"`
	ChildProcessCount *int       `json:"child_process_count"`
	FDCount           *int32     `json:"fd_count"`
	LastSampledAt     *time.Time `json:"last_sampled_at"`
}

type Process struct {
	Name         string
	Cfg          config.ProcConfig
	readyPattern *regexp.Regexp
	maxLines     int
	status       Status
	cmd          *exec.Cmd

	mu        sync.Mutex
	lines     []string // scrollback buffer of recent output lines
	ptmx      *os.File // pty master; nil when using pipes
	stdinPipe *os.File // write end of stdin pipe; nil when using PTY
	hasPrompt bool     // true when the last output was a partial line without a trailing \n

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

func (p *Process) CPUPercent() float64 {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.metrics == nil {
		return 0
	}
	return p.metrics.CPUPercent
}

func (p *Process) MemRSSMB() float64 {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.metrics == nil {
		return 0
	}
	return p.metrics.MemRSSMB
}

// HasPrompt returns true when the last output was a partial line (no trailing \n).
func (p *Process) HasPrompt() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.hasPrompt
}

func (p *Process) Lines() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	cp := make([]string, len(p.lines))
	copy(cp, p.lines)
	return cp
}

// AppendLine injects a line into the buffer without a real subprocess (for tests).
func (p *Process) AppendLine(line string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.lines) >= p.maxLines {
		p.lines[0] = ""
		p.lines = p.lines[1:]
	}
	p.lines = append(p.lines, line)
}

func ptr[T any](v T) *T { return &v }

func (p *Process) Snapshot() Snapshot {
	p.mu.Lock()
	defer p.mu.Unlock()

	snap := Snapshot{
		Name:   p.Name,
		Status: p.status.String(),
		Ready:  p.status == StatusRunning,
	}
	if p.cmd != nil && p.cmd.Process != nil {
		snap.ExitCode = p.exitCode
		snap.StartedAt = p.startedAt
		snap.PID = p.cmd.Process.Pid
	}
	if !p.readyAt.IsZero() {
		snap.ReadyAt = ptr(p.readyAt)
		snap.StartupDurationS = ptr(p.readyAt.Sub(p.startedAt).Seconds())
	}
	if m := p.metrics; m != nil {
		snap.MemRSSMB = ptr(m.MemRSSMB)
		snap.PeakMemRSSMB = ptr(m.PeakMemMB)
		snap.CPUPercent = ptr(m.CPUPercent)
		snap.CPUTimeS = ptr(m.CPUTimeS)
		snap.ThreadCount = ptr(m.Threads)
		snap.ChildProcessCount = ptr(m.Children)
		snap.FDCount = ptr(m.FDs)
		snap.LastSampledAt = ptr(m.SampledAt)
	}
	return snap
}

func (p *Process) buildEnv() []string {
	env := os.Environ()
	for k, v := range p.Cfg.Env {
		env = append(env, fmt.Sprintf("%s=%s", k, v))
	}
	return env
}

func (p *Process) buildCmd() *exec.Cmd {
	if len(p.Cfg.Cmd) > 0 {
		return exec.Command(p.Cfg.Cmd[0], p.Cfg.Cmd[1:]...)
	}
	return exec.Command("/bin/bash", "-c", p.Cfg.Shell)
}

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
	p.mu.Unlock()

	cmd := p.buildCmd()
	cmd.Env = p.buildEnv()

	ptmx, err := pty.Start(cmd)
	if err != nil {
		p.mu.Lock()
		p.status = StatusCrashed
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusCrashed})
		return fmt.Errorf("pty.Start %s: %w", p.Name, err)
	}

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = ptmx

	// Stop() was called while pty.Start was in progress
	if p.status == StatusStopped {
		p.killProcessGroup()
		if p.ptmx != nil {
			_ = p.ptmx.Close()
			p.ptmx = nil
		}
		p.mu.Unlock()
		send(StatusMsg{Name: p.Name, Status: StatusStopped})
		return nil
	}

	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	currentStatus := p.status
	p.mu.Unlock()
	send(StatusMsg{Name: p.Name, Status: currentStatus})

	go p.startMetricsSampler(cmd.Process.Pid)

	outChannel := make(chan tea.Msg, 256)

	go func() {
		for msg := range outChannel {
			send(msg)
		}
	}()

	readDone := make(chan struct{})
	go func() {
		p.readLoop(ptmx, outChannel)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()

		// Close the pty master to unblock readLoop
		p.mu.Lock()
		if p.ptmx != nil {
			_ = p.ptmx.Close()
			p.ptmx = nil
		}
		p.mu.Unlock()

		<-readDone
		close(outChannel)
		p.handleExit(cmd, exitErr, send)
	}()

	return nil
}

// handleExit updates process status after cmd.Wait returns and triggers
// autorestart if configured. Shared by PTY and pipe paths.
func (p *Process) handleExit(cmd *exec.Cmd, exitErr error, send func(tea.Msg)) {
	st := StatusDone
	if exitErr != nil {
		st = StatusCrashed
	}
	p.mu.Lock()
	if p.cmd == cmd && p.status != StatusStopped {
		p.status = st
		p.metrics = nil
		code := cmd.ProcessState.ExitCode()
		p.exitCode = &code
	}
	finalStatus := p.status
	shouldRestart := p.cmd == cmd && p.Cfg.Autorestart && st == StatusCrashed && finalStatus != StatusStopped
	p.mu.Unlock()

	send(StatusMsg{Name: p.Name, Status: finalStatus})

	if shouldRestart {
		_ = p.Start(send)
	}
}

// readLoop reads process output, batches lines, and sends OutputMsg to outChannel.
//
// Pipeline: PTY → [reader goroutine] → chunkChannel → [select loop] → outChannel → [drainer] → TUI
//
// The select loop handles three concerns:
//   - data:          split raw bytes into lines, accumulate into batch
//   - flushTicker:   deliver the batch to outChannel every 16ms (non-blocking to avoid backpressure)
//   - partialTimer:  lines without a trailing \n (e.g. "Enter name: ") are flushed after 48ms
//     of silence so interactive prompts appear without waiting for \n
func (p *Process) readLoop(r io.Reader, outChannel chan tea.Msg) {
	// Reader goroutine: drains the PTY independently so the kernel buffer
	// never fills up and blocks the child's writes.
	chunkChannel := make(chan []byte, 64)
	go func() {
		buf := make([]byte, 256*1024)
		for {
			n, err := r.Read(buf)
			if n > 0 {
				data := make([]byte, n)
				copy(data, buf[:n])
				chunkChannel <- data
			}
			if err != nil {
				close(chunkChannel)
				return
			}
		}
	}()

	var partial []byte // leftover bytes after the last \n (incomplete line)
	var batch []string // lines accumulated since last successful send
	var evicted int    // lines evicted from scrollback during this batch

	partialTimer := time.NewTimer(0)
	if !partialTimer.Stop() {
		<-partialTimer.C
	}

	flushTicker := time.NewTicker(flushInterval)
	defer flushTicker.Stop()

	// addLine buffers a line in scrollback and adds it to the current batch.
	// If the line matches the ready pattern, sends StatusRunning to the TUI.
	addLine := func(s string) {
		ev, ready := p.bufferLine(s)
		if ev {
			evicted++
		}
		if ready {
			outChannel <- StatusMsg{Name: p.Name, Status: StatusRunning}
		}
		batch = append(batch, s)
	}

	// trySend delivers the batch to outChannel without blocking. If the TUI event
	// loop is busy (channel full), the batch keeps growing until next tick.
	trySend := func() {
		if len(batch) == 0 {
			return
		}
		select {
		case outChannel <- OutputMsg{Name: p.Name, Added: batch, Evicted: evicted}:
			batch = nil
			evicted = 0
		default:
		}
	}

	for {
		select {
		// New data from the PTY (or EOF when the child exits)
		case data, ok := <-chunkChannel:
			if !ok {
				// EOF — flush remaining partial + batch
				if len(partial) > 0 {
					addLine(string(partial))
				}
				if len(batch) > 0 {
					outChannel <- OutputMsg{Name: p.Name, Added: batch, Evicted: evicted}
				}
				return
			}

			// Prepend any leftover bytes from the previous chunk
			data = append(partial, data...)
			partial = nil

			// Split into complete lines at \n boundaries
			for {
				idx := bytes.IndexByte(data, '\n')
				if idx == -1 {
					break
				}
				line := data[:idx]
				// PTY line discipline adds \r\n (ONLCR); strip the \r
				if len(line) > 0 && line[len(line)-1] == '\r' {
					line = line[:len(line)-1]
				}
				addLine(string(line))
				data = data[idx+1:]
			}

			// Leftover bytes without \n — likely an interactive prompt
			p.mu.Lock()
			p.hasPrompt = len(data) > 0
			p.mu.Unlock()

			if len(data) > 0 {
				partial = data
				// Start/reset the partial timer so the prompt appears
				// after 48ms of silence rather than waiting for \n
				if !partialTimer.Stop() {
					select {
					case <-partialTimer.C:
					default:
					}
				}
				partialTimer.Reset(flushInterval * 3)
			}

		// Periodic flush — deliver accumulated lines to the TUI
		case <-flushTicker.C:
			trySend()

		// Partial line timeout — treat the incomplete line as complete
		case <-partialTimer.C:
			if len(partial) > 0 {
				addLine(string(partial))
				partial = nil
				trySend()
			}
		}
	}
}

func (p *Process) bufferLine(line string) (evicted bool, becameReady bool) {
	p.mu.Lock()
	if len(p.lines) >= p.maxLines {
		p.lines[0] = ""
		p.lines = p.lines[1:]
		evicted = true
	}
	p.lines = append(p.lines, line)

	if p.status != StatusRunning && p.readyPattern != nil && p.readyPattern.MatchString(line) {
		p.readyAt = time.Now()
		p.status = StatusRunning
		becameReady = true
	}
	p.mu.Unlock()

	return evicted, becameReady
}

func (p *Process) startMetricsSampler(pid int) {
	ps, err := gops.NewProcess(int32(pid))
	if err != nil {
		return
	}
	_, _ = ps.CPUPercent() // baseline measurement
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

		if (st != StatusRunning && st != StatusPending) || (currentPID != 0 && currentPID != origPID) {
			return
		}

		all := collectProcessTree(ps)

		var rssBytes uint64
		var cpuPct, cpuTime float64
		var threads, fds int32
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

func (p *Process) stopSignal() syscall.Signal {
	switch p.Cfg.Stop {
	case "SIGINT":
		return syscall.SIGINT
	case "SIGKILL", "hard-kill":
		return syscall.SIGKILL
	default:
		return syscall.SIGTERM
	}
}

// killProcessGroup sends the configured stop signal to the process group
// and walks the tree to catch escaped descendants. Must hold p.mu.
func (p *Process) killProcessGroup() {
	if p.cmd == nil || p.cmd.Process == nil {
		return
	}
	if p.cmd.ProcessState != nil && p.cmd.ProcessState.Exited() {
		return
	}

	sig := p.stopSignal()
	pid := p.cmd.Process.Pid
	if err := syscall.Kill(-pid, sig); err != nil {
		_ = p.cmd.Process.Signal(sig)
	}
	if ps, err := gops.NewProcess(int32(pid)); err == nil {
		for _, proc := range collectProcessTree(ps) {
			_ = proc.SendSignal(sig)
		}
	}
}

// Stop sends SIGTERM, waits for exit, and escalates to SIGKILL.
func (p *Process) Stop() {
	p.mu.Lock()
	p.killProcessGroup()
	if p.ptmx != nil {
		_ = p.ptmx.Close()
		p.ptmx = nil
	}
	if p.stdinPipe != nil {
		_ = p.stdinPipe.Close()
		p.stdinPipe = nil
	}
	p.status = StatusStopped
	cmd := p.cmd
	p.mu.Unlock()

	if cmd == nil || cmd.Process == nil {
		return
	}

	// Wait for graceful exit, then escalate to SIGKILL
	deadline := time.Now().Add(stopGracePeriod)
	for time.Now().Before(deadline) {
		if cmd.ProcessState != nil {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}

	p.mu.Lock()
	if cmd.ProcessState == nil {
		_ = syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	p.mu.Unlock()
	time.Sleep(200 * time.Millisecond)
}

func (p *Process) Restart(send func(tea.Msg)) {
	p.Stop()
	send(StatusMsg{Name: p.Name, Status: StatusStopped})
	_ = p.Start(send)
}

func (p *Process) PID() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cmd != nil && p.cmd.Process != nil {
		return p.cmd.Process.Pid
	}
	return 0
}

func (p *Process) WriteInput(data []byte) error {
	p.mu.Lock()
	ptmx := p.ptmx
	stdinPipe := p.stdinPipe
	p.mu.Unlock()
	if ptmx != nil {
		_, err := ptmx.Write(data)
		return err
	}
	if stdinPipe != nil {
		// No terminal line discipline in pipe mode: translate \r to \n
		translated := bytes.ReplaceAll(data, []byte("\r"), []byte("\n"))
		_, err := stdinPipe.Write(translated)
		return err
	}
	return fmt.Errorf("process %s has no PTY or stdin pipe", p.Name)
}

func (p *Process) Resize(cols, rows uint16) {
	p.mu.Lock()
	ptmx := p.ptmx
	p.mu.Unlock()
	if ptmx != nil {
		_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
	}
}
