package process

import (
	"testing"

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
