package process

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
)

func TestStatusString(t *testing.T) {
	tests := []struct {
		status Status
		want   string
	}{
		{StatusPending, "pending"},
		{StatusRunning, "running"},
		{StatusStopped, "stopped"},
		{StatusDone, "done"},
		{StatusCrashed, "crashed"},
		{Status(99), "unknown"},
	}
	for _, tt := range tests {
		t.Run(tt.want, func(t *testing.T) {
			if got := tt.status.String(); got != tt.want {
				t.Errorf("got %q, want %q", got, tt.want)
			}
		})
	}
}

func TestNewProcess_fields(t *testing.T) {
	cfg := config.ProcConfig{Shell: "echo hi"}
	p := NewProcess("backend", cfg, 5000, "")
	if p.Name != "backend" {
		t.Errorf("Name: got %q, want %q", p.Name, "backend")
	}
	if p.maxLines != 5000 {
		t.Errorf("maxLines: got %d, want 5000", p.maxLines)
	}
	if p.Status() != StatusStopped {
		t.Errorf("initial status: got %s, want stopped", p.Status())
	}
}

func TestNewProcess_notReadyWithPattern(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "started"}, 1000, "")
	if p.Status() == StatusRunning {
		t.Error("process with ready_pattern should not start ready")
	}
	if p.readyPattern == nil {
		t.Error("readyPattern should be compiled")
	}
}

func TestNewProcess_compilesReadyPattern(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "started"}, 1000, "")
	if p.readyPattern == nil {
		t.Error("readyPattern should be compiled")
	}
}

func TestNewProcess_invalidPattern(t *testing.T) {
	// invalid regex should not panic; readyPattern stays nil
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "["}, 1000, "")
	if p.readyPattern != nil {
		t.Error("invalid regex should result in nil readyPattern")
	}
}

func TestProcess_linesEmpty(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{}, 100, "")
	if lines := p.Lines(); len(lines) != 0 {
		t.Errorf("expected empty lines, got %v", lines)
	}
}

func TestSnapshot_initialState(t *testing.T) {
	p := NewProcess("backend", config.ProcConfig{Shell: "echo hi"}, 1000, "")

	snap := p.Snapshot()

	if snap.Name != "backend" {
		t.Errorf("Name: got %q, want %q", snap.Name, "backend")
	}
	if snap.Status != "stopped" {
		t.Errorf("Status: got %q, want %q", snap.Status, "stopped")
	}
	if snap.Ready {
		t.Error("Ready: expected false when process is stopped")
	}
	if snap.PID != 0 {
		t.Errorf("PID: got %d, want 0", snap.PID)
	}
	if snap.ExitCode != nil {
		t.Errorf("ExitCode: got %v, want nil", snap.ExitCode)
	}
	if !snap.StartedAt.IsZero() {
		t.Errorf("StartedAt: got %v, want zero time", snap.StartedAt)
	}
	if snap.MemRSSMB != nil {
		t.Errorf("MemRSSMB: got %v, want nil", snap.MemRSSMB)
	}
	if snap.PeakMemRSSMB != nil {
		t.Errorf("PeakMemRSSMB: got %v, want nil", snap.PeakMemRSSMB)
	}
	if snap.CPUPercent != nil {
		t.Errorf("CPUPercent: got %v, want nil", snap.CPUPercent)
	}
	if snap.CPUTimeS != nil {
		t.Errorf("CPUTimeS: got %v, want nil", snap.CPUTimeS)
	}
	if snap.ThreadCount != nil {
		t.Errorf("ThreadCount: got %v, want nil", snap.ThreadCount)
	}
	if snap.ChildProcessCount != nil {
		t.Errorf("ChildProcessCount: got %v, want nil", snap.ChildProcessCount)
	}
	if snap.FDCount != nil {
		t.Errorf("FDCount: got %v, want nil", snap.FDCount)
	}
	if snap.LastSampledAt != nil {
		t.Errorf("LastSampledAt: got %v, want nil", snap.LastSampledAt)
	}
}

func TestSnapshot_withMetrics(t *testing.T) {
	p := NewProcess("worker", config.ProcConfig{Shell: "echo hi"}, 1000, "")

	someTime := time.Date(2024, 1, 15, 10, 0, 0, 0, time.UTC)
	p.startedAt = someTime
	p.metrics = &Metrics{
		MemRSSMB:   42.5,
		PeakMemMB:  55.0,
		CPUPercent: 1.5,
		CPUTimeS:   3.2,
		Threads:    4,
		Children:   2,
		FDs:        10,
		SampledAt:  someTime,
	}

	snap := p.Snapshot()

	if snap.MemRSSMB == nil || *snap.MemRSSMB != 42.5 {
		t.Errorf("MemRSSMB: got %v, want 42.5", snap.MemRSSMB)
	}
	if snap.PeakMemRSSMB == nil || *snap.PeakMemRSSMB != 55.0 {
		t.Errorf("PeakMemRSSMB: got %v, want 55.0", snap.PeakMemRSSMB)
	}
	if snap.CPUPercent == nil || *snap.CPUPercent != 1.5 {
		t.Errorf("CPUPercent: got %v, want 1.5", snap.CPUPercent)
	}
	if snap.CPUTimeS == nil || *snap.CPUTimeS != 3.2 {
		t.Errorf("CPUTimeS: got %v, want 3.2", snap.CPUTimeS)
	}
	if snap.ThreadCount == nil || *snap.ThreadCount != 4 {
		t.Errorf("ThreadCount: got %v, want 4", snap.ThreadCount)
	}
	if snap.ChildProcessCount == nil || *snap.ChildProcessCount != 2 {
		t.Errorf("ChildProcessCount: got %v, want 2", snap.ChildProcessCount)
	}
	if snap.FDCount == nil || *snap.FDCount != 10 {
		t.Errorf("FDCount: got %v, want 10", snap.FDCount)
	}
	if snap.LastSampledAt == nil || !snap.LastSampledAt.Equal(someTime) {
		t.Errorf("LastSampledAt: got %v, want %v", snap.LastSampledAt, someTime)
	}
}

func TestSnapshot_withReadyAt(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "ready"}, 1000, "")

	t0 := time.Date(2024, 6, 1, 12, 0, 0, 0, time.UTC)
	p.startedAt = t0
	p.readyAt = t0.Add(3 * time.Second)

	snap := p.Snapshot()

	if snap.ReadyAt == nil {
		t.Fatal("ReadyAt: got nil, want non-nil")
	}
	if !snap.ReadyAt.Equal(t0.Add(3 * time.Second)) {
		t.Errorf("ReadyAt: got %v, want %v", *snap.ReadyAt, t0.Add(3*time.Second))
	}
	if snap.StartupDurationS == nil {
		t.Fatal("StartupDurationS: got nil, want non-nil")
	}
	const want = 3.0
	const tolerance = 1e-9
	got := *snap.StartupDurationS
	if got < want-tolerance || got > want+tolerance {
		t.Errorf("StartupDurationS: got %f, want %f", got, want)
	}
}

// collectMsgs returns a thread-safe send function that collects all messages.
func collectMsgs() (func(tea.Msg), *[]tea.Msg, *sync.Mutex) {
	var mu sync.Mutex
	var msgs []tea.Msg
	return func(msg tea.Msg) {
		mu.Lock()
		msgs = append(msgs, msg)
		mu.Unlock()
	}, &msgs, &mu
}

// pidAlive checks whether a PID is still running.
func pidAlive(pid int) bool {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	return proc.Signal(syscall.Signal(0)) == nil
}

func TestStop_kills_entire_process_group(t *testing.T) {
	// Spawn a shell that writes its grandchild's PID to stdout, then waits.
	// "sleep 999 &" creates a grandchild; "echo $!" prints its PID.
	p := NewProcess("test-pgkill", config.ProcConfig{
		Shell: `sleep 999 & echo "GRANDCHILD_PID=$!"; wait`,
	}, 1000, "")

	send, _, _ := collectMsgs()
	if err := p.Start(send); err != nil {
		// PTY/fork may be unavailable in sandboxed environments
		t.Skipf("skipping: cannot spawn subprocess: %v", err)
	}

	// Wait for the grandchild PID to appear in output
	var grandchildPID int
	deadline := time.After(5 * time.Second)
	for grandchildPID == 0 {
		select {
		case <-deadline:
			t.Fatal("timed out waiting for grandchild PID in output")
		default:
		}
		for _, line := range p.Lines() {
			if strings.HasPrefix(line, "GRANDCHILD_PID=") {
				_, _ = fmt.Sscanf(line, "GRANDCHILD_PID=%d", &grandchildPID)
			}
		}
		if grandchildPID == 0 {
			time.Sleep(50 * time.Millisecond)
		}
	}

	parentPID := p.PID()
	if parentPID == 0 {
		t.Fatal("parent PID is 0 after Start")
	}

	// Both should be alive before Stop
	if !pidAlive(parentPID) {
		t.Fatalf("parent PID %d not alive before Stop", parentPID)
	}
	if !pidAlive(grandchildPID) {
		t.Fatalf("grandchild PID %d not alive before Stop", grandchildPID)
	}

	p.Stop()

	// Give the OS a moment to reap
	time.Sleep(200 * time.Millisecond)

	if pidAlive(parentPID) {
		t.Errorf("parent PID %d still alive after Stop", parentPID)
	}
	if pidAlive(grandchildPID) {
		t.Errorf("grandchild PID %d still alive after Stop — process group kill didn't work", grandchildPID)
	}
	if p.Status() != StatusStopped {
		t.Errorf("status: got %s, want stopped", p.Status())
	}
}

func TestReadLoop_batchesOutput(t *testing.T) {
	const totalLines = 500
	// Spawn a process that writes 500 lines as fast as possible
	p := NewProcess("batch-test", config.ProcConfig{
		Shell: fmt.Sprintf(`for i in $(seq 1 %d); do echo "line $i"; done`, totalLines),
	}, totalLines+100, "")

	send, msgs, mu := collectMsgs()
	if err := p.Start(send); err != nil {
		t.Skipf("skipping: cannot spawn subprocess: %v", err)
	}

	// Wait for the process to finish
	deadline := time.After(10 * time.Second)
	for {
		select {
		case <-deadline:
			t.Fatal("timed out waiting for process to finish")
		default:
		}
		st := p.Status()
		if st == StatusDone || st == StatusCrashed {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	// Most lines should be buffered. The exact count may vary slightly due
	// to VT screen row trimming and PTY buffering, but should be close.
	lines := p.Lines()
	if len(lines) < totalLines/2 {
		t.Fatalf("expected at least %d buffered lines, got %d", totalLines/2, len(lines))
	}

	// Count OutputMsg notifications — should be far fewer than totalLines
	mu.Lock()
	var outputMsgCount int
	for _, msg := range *msgs {
		if _, ok := msg.(OutputMsg); ok {
			outputMsgCount++
		}
	}
	mu.Unlock()

	t.Logf("lines=%d, OutputMsg count=%d (%.1fx reduction)",
		totalLines, outputMsgCount, float64(totalLines)/float64(outputMsgCount))

	if outputMsgCount >= totalLines {
		t.Errorf("expected batching to reduce OutputMsg count below %d, got %d", totalLines, outputMsgCount)
	}
	// With 16ms flush interval and 500 lines written instantly, we expect
	// significant coalescing (typically <20 messages)
	if outputMsgCount > totalLines/5 {
		t.Errorf("batching not effective enough: %d OutputMsgs for %d lines", outputMsgCount, totalLines)
	}
}

// runReadLoop drives readLoop against an in-memory reader and waits for it to
// return. Bypassing the PTY avoids a known Linux kernel race (commit
// 1a48632ffed6) where data written and immediately followed by close() on the
// child's PTY end can be dropped before the parent's read is scheduled.
func runReadLoop(t *testing.T, p *Process, input string) {
	t.Helper()
	outChannel := make(chan tea.Msg, 64)
	done := make(chan struct{})
	go func() {
		p.readLoop(strings.NewReader(input), outChannel)
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("readLoop did not return")
	}
}

func TestHasPrompt_partialLine(t *testing.T) {
	p := NewProcess("prompt-test", config.ProcConfig{}, 100, "")
	runReadLoop(t, p, "Enter name: ")

	if !p.HasPrompt() {
		t.Error("HasPrompt should be true for a partial line")
	}
	lines := p.Lines()
	if len(lines) == 0 {
		t.Fatal("expected at least one buffered line")
	}
	if !strings.Contains(lines[len(lines)-1], "Enter name:") {
		t.Errorf("expected partial line containing 'Enter name:', got %q", lines[len(lines)-1])
	}
}

func TestHasPrompt_completeLine(t *testing.T) {
	p := NewProcess("no-prompt", config.ProcConfig{}, 100, "")
	runReadLoop(t, p, "hello\n")

	if p.HasPrompt() {
		t.Error("HasPrompt should be false after a complete line")
	}
}

func TestWriteInput(t *testing.T) {
	p := NewProcess("pty-input", config.ProcConfig{
		Shell: `head -1`,
	}, 100, "")

	send, _, _ := collectMsgs()
	if err := p.Start(send); err != nil {
		t.Skipf("skipping: cannot spawn subprocess: %v", err)
	}

	time.Sleep(100 * time.Millisecond)

	// PTY line discipline translates \r to \n, so head -1 sees a full line
	if err := p.WriteInput([]byte("hello\r")); err != nil {
		t.Fatalf("WriteInput failed: %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case <-deadline:
			t.Fatal("timed out waiting for process to finish")
		default:
		}
		st := p.Status()
		if st == StatusDone || st == StatusCrashed {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	lines := p.Lines()
	found := false
	for _, l := range lines {
		if strings.Contains(l, "hello") {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("expected 'hello' in output, got lines: %v", lines)
	}
}

// Simulates the production backpressure scenario: many processes flood output
// simultaneously while sends are serialized through a slow bottleneck (like
// Bubble Tea's unbuffered Program.msgs channel). Without the per-process
// outCh buffer, readLoops block on send → stop draining chunkCh → PTY buffer
// fills → child write() blocks → processes hang. With the fix, readLoops
// send non-blocking to outCh so the PTY is always drained.
func TestBackpressure_concurrentFloodDoesNotStall(t *testing.T) {
	const procCount = 10
	const linesPerProc = 5000

	// Serialize all sends through a mutex with a 2ms delay to simulate the
	// Bubble Tea unbuffered channel where Program.Send blocks until the
	// event loop processes the previous message.
	var bottleneck sync.Mutex
	slowSend := func(msg tea.Msg) {
		bottleneck.Lock()
		time.Sleep(2 * time.Millisecond)
		bottleneck.Unlock()
	}

	procs := make([]*Process, procCount)
	for i := range procs {
		procs[i] = NewProcess(
			fmt.Sprintf("flood-%d", i),
			config.ProcConfig{
				Shell: fmt.Sprintf(
					`for i in $(seq 1 %d); do echo "proc-%d line $i xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"; done`,
					linesPerProc, i),
			},
			linesPerProc+100, "",
		)
	}

	for _, p := range procs {
		if err := p.Start(slowSend); err != nil {
			t.Skipf("skipping: cannot spawn subprocess: %v", err)
		}
	}

	// All processes should complete well within 10s. Without the outCh
	// buffer the serialized sends cause PTY backpressure that hangs the
	// child processes, triggering this timeout.
	deadline := time.After(10 * time.Second)
	for {
		select {
		case <-deadline:
			var stalled []string
			for _, p := range procs {
				st := p.Status()
				if st != StatusDone && st != StatusCrashed {
					stalled = append(stalled, fmt.Sprintf(
						"%s (status=%s, lines=%d)", p.Name, st, len(p.Lines())))
				}
			}
			if len(stalled) > 0 {
				t.Fatalf("timed out — %d/%d processes stalled: %v",
					len(stalled), procCount, stalled)
			}
			return
		default:
		}

		allDone := true
		for _, p := range procs {
			st := p.Status()
			if st != StatusDone && st != StatusCrashed {
				allDone = false
				break
			}
		}
		if allDone {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}

	// Verify most output was captured — the PTY teardown race can lose a few
	// lines at the tail, so we allow up to 5% loss. The important assertion
	// is that processes completed (above), not exact line counts.
	for _, p := range procs {
		lines := p.Lines()
		if len(lines) < linesPerProc*95/100 {
			t.Errorf("%s: expected at least %d lines (95%%), got %d", p.Name, linesPerProc*95/100, len(lines))
		}
	}
}

func TestSnapshot_noReadyAt(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "ready"}, 1000, "")
	// readyAt is left as zero value; startedAt is also zero

	snap := p.Snapshot()

	if snap.ReadyAt != nil {
		t.Errorf("ReadyAt: got %v, want nil", snap.ReadyAt)
	}
	if snap.StartupDurationS != nil {
		t.Errorf("StartupDurationS: got %v, want nil", snap.StartupDurationS)
	}
}

func TestNewProcess_globalShell(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "echo hi"}, 100, "/bin/zsh")
	if p.shellBin != "/bin/zsh" {
		t.Errorf("shellBin: got %q, want %q", p.shellBin, "/bin/zsh")
	}
}

func TestNewProcess_defaultShell(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "echo hi"}, 100, "")
	if p.shellBin != defaultShell {
		t.Errorf("shellBin: got %q, want %q", p.shellBin, defaultShell)
	}
}

func TestIsRunning(t *testing.T) {
	tests := []struct {
		status Status
		want   bool
	}{
		{StatusPending, true},
		{StatusRunning, true},
		{StatusStopped, false},
		{StatusDone, false},
		{StatusCrashed, false},
	}
	for _, tt := range tests {
		t.Run(tt.status.String(), func(t *testing.T) {
			if got := tt.status.IsRunning(); got != tt.want {
				t.Errorf("got %v, want %v", got, tt.want)
			}
		})
	}
}

func TestProcess_IsRunning(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true"}, 100, "")
	if p.IsRunning() {
		t.Error("new process should not be running")
	}
}

func TestBuildCmd_cwd(t *testing.T) {
	dir := t.TempDir()
	p := NewProcess("svc", config.ProcConfig{Shell: "echo hi", Cwd: dir}, 100, "")
	cmd := p.buildCmd()
	if cmd.Dir != dir {
		t.Errorf("Dir: got %q, want %q", cmd.Dir, dir)
	}
}

func TestBuildCmd_globalShell(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "echo hi"}, 100, "/bin/zsh")
	cmd := p.buildCmd()
	if cmd.Path == "" {
		t.Fatal("cmd.Path is empty")
	}
	if cmd.Args[0] != "/bin/zsh" {
		t.Errorf("Args[0]: got %q, want %q", cmd.Args[0], "/bin/zsh")
	}
	if cmd.Args[1] != "-c" {
		t.Errorf("Args[1]: got %q, want %q", cmd.Args[1], "-c")
	}
}

// ── VT emulator integration ────────────────────────────────────────────────────

func TestVT_cursorMovementOverwrites(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	// Write two lines, then cursor-up + overwrite the first
	_, _ = p.emulator.Write([]byte("old line\r\n"))
	_, _ = p.emulator.Write([]byte("second\r\n"))
	// Move cursor up 2, write replacement
	_, _ = p.emulator.Write([]byte("\x1b[2Anew line\r\n"))

	lines := p.Lines()
	if len(lines) < 2 {
		t.Fatalf("expected at least 2 lines, got %d", len(lines))
	}
	if !strings.Contains(lines[0], "new line") {
		t.Errorf("cursor-up overwrite: want 'new line', got %q", lines[0])
	}
	if strings.Contains(lines[0], "old line") {
		t.Errorf("old content should be overwritten, got %q", lines[0])
	}
}

func TestVT_eraseLineSequence(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	_, _ = p.emulator.Write([]byte("to be erased\r\n"))
	_, _ = p.emulator.Write([]byte("keep this\r\n"))
	// Cursor up 2 + erase entire line (CSI 2K)
	_, _ = p.emulator.Write([]byte("\x1b[2A\x1b[2K\r\n"))

	lines := p.Lines()
	if len(lines) < 1 {
		t.Fatalf("expected at least 1 line, got %d", len(lines))
	}
	// First line should be blank after erase
	if strings.TrimSpace(lines[0]) != "" {
		t.Errorf("erased line should be blank, got %q", lines[0])
	}
	if !strings.Contains(lines[1], "keep this") {
		t.Errorf("second line should be preserved, got %q", lines[1])
	}
}

func TestVT_scrollbackAndScreen(t *testing.T) {
	// Small screen (5 rows) with scrollback of 10
	p := NewProcess("vt", config.ProcConfig{}, 10, "")
	p.emulator.Resize(40, 5)

	// Write 8 lines — 3 go to scrollback, 5 remain on screen
	for i := range 8 {
		_, _ = fmt.Fprintf(p.emulator, "line %d\r\n", i)
	}

	lines := p.Lines()
	if len(lines) < 8 {
		t.Fatalf("expected at least 8 lines (scrollback + screen), got %d", len(lines))
	}
	// First line should be from scrollback
	if !strings.Contains(lines[0], "line 0") {
		t.Errorf("first scrollback line: want 'line 0', got %q", lines[0])
	}
	// Last content line
	if !strings.Contains(lines[7], "line 7") {
		t.Errorf("last line: want 'line 7', got %q", lines[7])
	}
}

func TestVT_scrollbackEviction(t *testing.T) {
	// Scrollback of 3, screen of 2 rows — eviction after 5 lines
	p := NewProcess("vt", config.ProcConfig{}, 3, "")
	p.emulator.Resize(40, 2)

	for i := range 8 {
		_, _ = fmt.Fprintf(p.emulator, "line %d\r\n", i)
	}

	lines := p.Lines()
	// Oldest lines should have been evicted from scrollback
	for _, l := range lines {
		if strings.Contains(l, "line 0") || strings.Contains(l, "line 1") || strings.Contains(l, "line 2") {
			t.Errorf("evicted line should not appear, got %q", l)
		}
	}
	// Recent lines should be present
	found7 := false
	for _, l := range lines {
		if strings.Contains(l, "line 7") {
			found7 = true
		}
	}
	if !found7 {
		t.Errorf("recent line 'line 7' should be present, lines: %v", lines)
	}
}

func TestVT_centeringPreservesLeadingSpaces(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	p.emulator.Resize(80, 24)
	// Simulate centered text: 20 spaces + content
	_, _ = p.emulator.Write([]byte("                    centered text\r\n"))

	lines := p.Lines()
	if len(lines) == 0 {
		t.Fatal("expected at least 1 line")
	}
	if !strings.HasPrefix(lines[0], "                    centered") {
		t.Errorf("leading spaces should be preserved, got %q", lines[0])
	}
}

func TestVT_cursorForwardPreservesIndent(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	p.emulator.Resize(80, 24)
	// CSI 20C = cursor forward 20 columns, then write text
	_, _ = p.emulator.Write([]byte("\x1b[20Cindented via escape\r\n"))

	lines := p.Lines()
	if len(lines) == 0 {
		t.Fatal("expected at least 1 line")
	}
	// The first 20 columns should be spaces, then the text
	if len(lines[0]) < 20 {
		t.Fatalf("line too short: %q", lines[0])
	}
	prefix := lines[0][:20]
	if strings.TrimSpace(prefix) != "" {
		t.Errorf("first 20 chars should be spaces, got %q", prefix)
	}
	if !strings.Contains(lines[0], "indented via escape") {
		t.Errorf("text should follow indent, got %q", lines[0])
	}
}

func TestVT_resizeUpdatesEmulator(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	if w := p.emulator.Width(); w != 80 {
		t.Fatalf("initial width: got %d, want 80", w)
	}
	p.Resize(120, 40)
	if w := p.emulator.Width(); w != 120 {
		t.Errorf("after Resize: width got %d, want 120", w)
	}
	if h := p.emulator.Height(); h != 40 {
		t.Errorf("after Resize: height got %d, want 40", h)
	}
}

func TestVT_emptyScreenReturnsNoLines(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	lines := p.Lines()
	if len(lines) != 0 {
		t.Errorf("empty emulator: want 0 lines, got %d", len(lines))
	}
}

func TestVT_clearLinesResetsScrollback(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	p.emulator.Resize(40, 3)
	// Write enough to fill scrollback
	for i := range 10 {
		_, _ = fmt.Fprintf(p.emulator, "line %d\r\n", i)
	}
	before := p.Lines()
	if len(before) == 0 {
		t.Fatal("expected lines before clear")
	}

	p.ClearLines()

	after := p.Lines()
	// Scrollback should be empty; only visible screen lines remain
	sb := p.emulator.Scrollback()
	if sb.Len() != 0 {
		t.Errorf("scrollback should be empty after ClearLines, got %d", sb.Len())
	}
	if len(after) >= len(before) {
		t.Errorf("after ClearLines: expected fewer lines (%d before), got %d", len(before), len(after))
	}
}

func TestVT_appendLineWritesToEmulator(t *testing.T) {
	p := NewProcess("vt", config.ProcConfig{}, 100, "")
	p.AppendLine("hello from test")
	lines := p.Lines()
	found := false
	for _, l := range lines {
		if strings.Contains(l, "hello from test") {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("AppendLine content not found in Lines(), got: %v", lines)
	}
}

func TestBuildCmd_cmdBypassesShell(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Cmd: []string{"echo", "hi"}}, 100, "/bin/zsh")
	cmd := p.buildCmd()
	if cmd.Args[0] != "echo" {
		t.Errorf("Cmd mode should bypass shell, got Args[0]=%q", cmd.Args[0])
	}
}

func TestProcess_logFileTee(t *testing.T) {
	dir := t.TempDir()
	p := NewProcess("svc", config.ProcConfig{Shell: `echo hello-log-tee; sleep 0.1`}, 100, "")
	p.SetLogDir(dir)

	send, _, _ := collectMsgs()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}

	// Wait for the process to exit so the log file flush is complete.
	deadline := time.After(5 * time.Second)
	for p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("process did not exit in time")
		case <-time.After(25 * time.Millisecond):
		}
	}

	data, err := os.ReadFile(dir + "/svc.log")
	if err != nil {
		t.Fatalf("read log file: %v", err)
	}
	if !strings.Contains(string(data), "hello-log-tee") {
		t.Errorf("expected log file to contain 'hello-log-tee', got %q", string(data))
	}
}

func TestProcess_logFileTruncatesOnRestart(t *testing.T) {
	dir := t.TempDir()
	p := NewProcess("svc", config.ProcConfig{Shell: `echo first-run; sleep 0.05`}, 100, "")
	p.SetLogDir(dir)

	send, _, _ := collectMsgs()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	// Wait for first run to finish.
	deadline := time.After(5 * time.Second)
	for p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("first run did not finish")
		case <-time.After(25 * time.Millisecond):
		}
	}

	// Replace shell and restart to verify truncation.
	p.Cfg.Shell = `echo second-run; sleep 0.05`
	if err := p.Start(send); err != nil {
		t.Fatalf("restart: %v", err)
	}
	deadline = time.After(5 * time.Second)
	for p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("second run did not finish")
		case <-time.After(25 * time.Millisecond):
		}
	}

	data, err := os.ReadFile(dir + "/svc.log")
	if err != nil {
		t.Fatalf("read log file: %v", err)
	}
	if strings.Contains(string(data), "first-run") {
		t.Errorf("expected first-run to be truncated, got %q", string(data))
	}
	if !strings.Contains(string(data), "second-run") {
		t.Errorf("expected second-run in log, got %q", string(data))
	}
}

func TestProcess_logFileDisabledByDefault(t *testing.T) {
	dir := t.TempDir()
	p := NewProcess("svc", config.ProcConfig{Shell: `echo no-log; sleep 0.05`}, 100, "")
	// Note: no SetLogDir call.

	send, _, _ := collectMsgs()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	deadline := time.After(5 * time.Second)
	for p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("did not finish")
		case <-time.After(25 * time.Millisecond):
		}
	}
	if _, err := os.Stat(dir + "/svc.log"); !os.IsNotExist(err) {
		t.Errorf("expected no log file when logDir unset; got err=%v", err)
	}
}
