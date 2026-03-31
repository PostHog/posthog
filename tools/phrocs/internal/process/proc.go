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

	// Nil until the first metrics sample arrives (~5s after start).
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

// Represents a single managed subprocess
type Process struct {
	Name         string
	Cfg          config.ProcConfig
	readyPattern *regexp.Regexp
	maxLines     int
	status       Status
	cmd          *exec.Cmd

	mu        sync.Mutex
	lines     []string      // scrollback buffer of recent output lines
	ptmx      *os.File      // pty master; nil when using pipes
	stdinPipe *os.File      // write end of stdin pipe; nil when using PTY
	hasPrompt bool          // true when the last output was a partial line without a trailing \n
	waitDone  chan struct{} // closed by the goroutine that calls cmd.Wait()

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

// CPUPercent returns the most recently sampled CPU usage, or 0 if not yet sampled.
func (p *Process) CPUPercent() float64 {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.metrics == nil {
		return 0
	}
	return p.metrics.CPUPercent
}

// MemRSSMB returns the most recently sampled RSS in MB, or 0 if not yet sampled.
func (p *Process) MemRSSMB() float64 {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.metrics == nil {
		return 0
	}
	return p.metrics.MemRSSMB
}

// HasPrompt returns true when the last output was a partial line (no trailing \n),
// indicating the process is likely waiting for input.
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
		p.lines[0] = "" // allow GC of evicted string data
		p.lines = p.lines[1:]
	}
	p.lines = append(p.lines, line)
}

func ptr[T any](v T) *T { return &v }

// Returns a consistent point-in-time view of the process
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

// buildEnv constructs the environment for the child process.
func (p *Process) buildEnv() []string {
	env := os.Environ()
	for k, v := range p.Cfg.Env {
		env = append(env, fmt.Sprintf("%s=%s", k, v))
	}
	return env
}

// buildCmd creates the exec.Cmd from either the shell or cmd config.
func (p *Process) buildCmd() *exec.Cmd {
	if len(p.Cfg.Cmd) > 0 {
		return exec.Command(p.Cfg.Cmd[0], p.Cfg.Cmd[1:]...)
	}
	return exec.Command("/bin/bash", "-c", p.Cfg.Shell)
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
	if p.stdinPipe != nil {
		_ = p.stdinPipe.Close()
		p.stdinPipe = nil
	}
	p.mu.Unlock()

	cmd := p.buildCmd()
	cmd.Env = p.buildEnv()

	ptmx, err := pty.Start(cmd)
	if err != nil {
		// Use combined stdout/stderr pipe when PTY allocation fails
		return p.startWithPipe(cmd, send)
	}

	waitDone := make(chan struct{})

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = ptmx
	p.waitDone = waitDone

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

	// Only set to running if proc has no ready pattern
	if p.readyPattern == nil {
		p.status = StatusRunning
	}
	currentStatus := p.status
	p.mu.Unlock()
	// Send initial status message
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
		close(waitDone)

		// Close the pty master to unblock readLoop
		p.mu.Lock()
		if p.ptmx != nil {
			_ = p.ptmx.Close()
			p.ptmx = nil
		}
		p.mu.Unlock()

		// Wait for readLoop to drain all buffered output before updating status
		<-readDone
		close(outChannel)
		p.handleExit(cmd, exitErr, send)
	}()

	return nil
}

// startWithPipe is the fallback when PTY allocation fails. It uses a combined
// stdout/stderr pipe instead.
func (p *Process) startWithPipe(cmd *exec.Cmd, send func(tea.Msg)) error {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	stdinR, stdinW, err := os.Pipe()
	if err != nil {
		return fmt.Errorf("stdin pipe: %w", err)
	}
	cmd.Stdin = stdinR

	stdoutR, stdoutW, err := os.Pipe()
	if err != nil {
		_ = stdinR.Close()
		_ = stdinW.Close()
		return fmt.Errorf("stdout pipe: %w", err)
	}
	cmd.Stdout = stdoutW
	cmd.Stderr = stdoutW

	if err := cmd.Start(); err != nil {
		_ = stdinR.Close()
		_ = stdinW.Close()
		_ = stdoutR.Close()
		_ = stdoutW.Close()
		return fmt.Errorf("start: %w", err)
	}

	// Close write ends in the parent so reads get EOF when the child exits.
	_ = stdinR.Close()
	_ = stdoutW.Close()

	waitDone := make(chan struct{})

	p.mu.Lock()
	p.cmd = cmd
	p.ptmx = nil
	p.stdinPipe = stdinW
	p.waitDone = waitDone

	if p.status == StatusStopped {
		p.killProcessGroup()
		_ = stdinW.Close()
		p.stdinPipe = nil
		p.mu.Unlock()
		_ = stdoutR.Close()
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
		p.readLoop(stdoutR, outChannel)
		close(readDone)
	}()

	go func() {
		exitErr := cmd.Wait()
		close(waitDone)

		_ = stdoutR.Close()

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

	becameReady := false

	// addLine buffers a line in scrollback and adds it to the current batch.
	addLine := func(s string) {
		ev, ready := p.bufferLine(s)
		if ev {
			evicted++
		}
		if ready {
			becameReady = true
		}
		batch = append(batch, s)
	}

	// trySend delivers the batch to outChannel without blocking. If the TUI event
	// loop is busy (channel full), the batch keeps growing until next tick.
	// A pending "became ready" status is sent first (also non-blocking).
	trySend := func() {
		if becameReady {
			select {
			case outChannel <- StatusMsg{Name: p.Name, Status: StatusRunning}:
				becameReady = false
			default:
			}
		}
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
				// EOF — flush remaining partial + batch (non-blocking to avoid deadlock)
				if len(partial) > 0 {
					addLine(string(partial))
				}
				trySend()
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

// bufferLine adds a line to the scrollback buffer, evicting old lines if needed.
func (p *Process) bufferLine(line string) (evicted bool, becameReady bool) {
	p.mu.Lock()
	if len(p.lines) >= p.maxLines {
		p.lines[0] = "" // allow GC of evicted string data
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

// Sampling CPU/mem/threads every metricsSampleInterval for the process tree
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
			// Process has been restarted with a new PID
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

// stopSignal returns the syscall signal to use when stopping the process,
// based on the stop config. Defaults to SIGTERM.
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
	// If the tracked command has already exited, avoid signaling based on a potentially reused PID.
	if p.waitDone != nil {
		select {
		case <-p.waitDone:
			return
		default:
		}
	}

	sig := p.stopSignal()
	pid := p.cmd.Process.Pid
	if err := syscall.Kill(-pid, sig); err != nil {
		_ = p.cmd.Process.Signal(sig)
	}
	// Walk the full process tree to catch any descendants that escaped the
	// process group (e.g. pnpm spawns node as a detached child).
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
	waitDone := p.waitDone
	p.mu.Unlock()

	if cmd == nil || cmd.Process == nil {
		return
	}

	// Wait for graceful exit, then escalate to SIGKILL
	if waitDone != nil {
		select {
		case <-waitDone:
			return
		case <-time.After(stopGracePeriod):
		}

		pid := cmd.Process.Pid
		if err := syscall.Kill(-pid, syscall.SIGKILL); err != nil && err != syscall.ESRCH {
			_ = cmd.Process.Kill()
		}

		// Give the kernel a moment to reap after SIGKILL
		select {
		case <-waitDone:
		case <-time.After(200 * time.Millisecond):
		}
	}
}

// Stops the process, clears its output buffer, and starts it again
func (p *Process) Restart(send func(tea.Msg)) {
	p.Stop()
	send(StatusMsg{Name: p.Name, Status: StatusPending})
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

// WriteInput writes data to the process's stdin via the PTY.
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

// Updates the pty window size to keep output correctly reflowed
func (p *Process) Resize(cols, rows uint16) {
	p.mu.Lock()
	ptmx := p.ptmx
	p.mu.Unlock()
	if ptmx != nil {
		_ = pty.Setsize(ptmx, &pty.Winsize{Rows: rows, Cols: cols})
	}
}
