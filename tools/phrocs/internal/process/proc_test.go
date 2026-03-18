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
	p := NewProcess("backend", cfg, 5000)
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

func TestNewProcess_readyWithoutPattern(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true"}, 1000)
	if !p.ready {
		t.Error("process with no ready_pattern should start ready")
	}
}

func TestNewProcess_notReadyWithPattern(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "started"}, 1000)
	if p.ready {
		t.Error("process with ready_pattern should not start ready")
	}
	if p.readyPattern == nil {
		t.Error("readyPattern should be compiled")
	}
}

func TestNewProcess_invalidPattern(t *testing.T) {
	// invalid regex should not panic; readyPattern stays nil
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "["}, 1000)
	if p.readyPattern != nil {
		t.Error("invalid regex should result in nil readyPattern")
	}
}

func TestProcess_linesEmpty(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{}, 100)
	if lines := p.Lines(); len(lines) != 0 {
		t.Errorf("expected empty lines, got %v", lines)
	}
}

func TestSnapshot_initialState(t *testing.T) {
	p := NewProcess("backend", config.ProcConfig{Shell: "echo hi"}, 1000)

	snap := p.Snapshot()

	if snap.Name != "backend" {
		t.Errorf("Name: got %q, want %q", snap.Name, "backend")
	}
	if snap.Status != "stopped" {
		t.Errorf("Status: got %q, want %q", snap.Status, "stopped")
	}
	// No ready_pattern means the process is considered ready immediately.
	if !snap.Ready {
		t.Error("Ready: expected true when no ready_pattern is configured")
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
	p := NewProcess("worker", config.ProcConfig{Shell: "echo hi"}, 1000)

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
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "ready"}, 1000)

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
	}, 1000)

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

func TestSnapshot_noReadyAt(t *testing.T) {
	p := NewProcess("svc", config.ProcConfig{Shell: "true", ReadyPattern: "ready"}, 1000)
	// readyAt is left as zero value; startedAt is also zero

	snap := p.Snapshot()

	if snap.ReadyAt != nil {
		t.Errorf("ReadyAt: got %v, want nil", snap.ReadyAt)
	}
	if snap.StartupDurationS != nil {
		t.Errorf("StartupDurationS: got %v, want nil", snap.StartupDurationS)
	}
}
