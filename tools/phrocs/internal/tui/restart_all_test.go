package tui

import (
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// noopSend is a sender that drops every message. Tests don't drive the Bubble
// Tea event loop, so we just need a non-nil function for Manager.send.
func noopSend(tea.Msg) {}

// wireSend installs a no-op sender on the manager — required because
// process.Start panics on a nil send func, and Manager.send is otherwise only
// populated by the real Program at app startup.
func wireSend(m *Model) {
	m.mgr.SetSend(noopSend)
}

// startAndWait starts a quick-exit proc and blocks until it has terminated, so
// that IsRestartable() returns true on the next call. Skips the test if the
// sandbox can't fork PTYs.
func startAndWait(t *testing.T, p *process.Process, send func(tea.Msg)) {
	t.Helper()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	deadline := time.After(5 * time.Second)
	for p.IsRunning() {
		select {
		case <-deadline:
			t.Fatalf("proc %s did not exit", p.Name)
		case <-time.After(20 * time.Millisecond):
		}
	}
	t.Cleanup(func() { p.Stop() })
}

// findProc returns the proc with the given name from the model's services.
func findProc(t *testing.T, m Model, name string) *process.Process {
	t.Helper()
	for _, p := range m.services {
		if p.Name == name {
			return p
		}
	}
	t.Fatalf("proc %q not found in services", name)
	return nil
}

// ── hasRestartableProc ──────────────────────────────────────────────────────────

func TestHasRestartableProc_falseOnFreshModel(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	if m.hasRestartableProc() {
		t.Error("fresh model with never-started procs should have nothing restartable")
	}
}

func TestHasRestartableProc_trueAfterProcExits(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	wireSend(&m)
	startAndWait(t, findProc(t, m, "backend"), m.mgr.Send())
	if !m.hasRestartableProc() {
		t.Error("after a proc has been started and exited, hasRestartableProc should be true")
	}
}

func TestHasRestartableProc_falseWhileRunning(t *testing.T) {
	// A long-running proc is not restartable — running ≠ stopped/crashed/done.
	cfg := testConfig()
	cfg.Procs = map[string]config.ProcConfig{
		"sleeper": {Shell: "sleep 30"},
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	model := next.(Model)
	wireSend(&model)

	p := findProc(t, model, "sleeper")
	if err := p.Start(model.mgr.Send()); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	t.Cleanup(func() { p.Stop() })

	// Wait until it's actually running (not just spawning).
	deadline := time.After(2 * time.Second)
	for !p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("sleeper never reached running state")
		case <-time.After(20 * time.Millisecond):
		}
	}

	if model.hasRestartableProc() {
		t.Error("running procs should not be restartable")
	}
}

// ── restartAll ──────────────────────────────────────────────────────────────────

func TestRestartAll_returnsZeroOnFreshModel(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	if n := m.restartAll(); n != 0 {
		t.Errorf("restartAll on fresh model: got %d, want 0", n)
	}
}

func TestRestartAll_skipsNeverStartedAndCountsOnlyRestartable(t *testing.T) {
	m := readyModel(t, "backend", "frontend", "capture")
	wireSend(&m)

	// Start two procs and let them exit — they should be the only ones counted.
	startAndWait(t, findProc(t, m, "backend"), m.mgr.Send())
	startAndWait(t, findProc(t, m, "frontend"), m.mgr.Send())
	// "capture" is left untouched (autostart=false, never started).

	if n := m.restartAll(); n != 2 {
		t.Errorf("restartAll: got %d, want 2 (capture must be skipped)", n)
	}

	// Belt and braces: capture should still report not-restartable, since
	// restartAll must not have touched it.
	if findProc(t, m, "capture").IsRestartable() {
		t.Error("capture was never started; restartAll must not flip its state")
	}
}

// ── updateProcKeys: RestartAll binding gating ────────────────────────────────────

func TestUpdateProcKeys_RestartAllDisabledWhenNothingRestartable(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.updateProcKeys()
	if m.keys.RestartAll.Enabled() {
		t.Error("RestartAll should be disabled when no proc has ever been started")
	}
}

func TestUpdateProcKeys_RestartAllEnabledOnceOneIsRestartable(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	wireSend(&m)
	startAndWait(t, findProc(t, m, "backend"), m.mgr.Send())

	m.updateProcKeys()
	if !m.keys.RestartAll.Enabled() {
		t.Error("RestartAll should be enabled when at least one proc is restartable")
	}
}
