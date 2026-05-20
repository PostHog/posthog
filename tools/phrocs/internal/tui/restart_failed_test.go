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

// runUntilStatus starts the proc and blocks until it reaches the target
// status. Useful for driving a proc to a known terminal state via a real
// shell exit code (`true` → Done, `false` → Crashed). Skips on PTY failure.
func runUntilStatus(t *testing.T, p *process.Process, send func(tea.Msg), target process.Status) {
	t.Helper()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	deadline := time.After(5 * time.Second)
	for p.Status() != target {
		select {
		case <-deadline:
			t.Fatalf("proc %s never reached %s (last status: %s)", p.Name, target, p.Status())
		case <-time.After(20 * time.Millisecond):
		}
	}
	t.Cleanup(func() { p.Stop() })
}

// modelWithProcs builds a ready model where each proc has a custom shell
// command. Useful for setting up mixed-state scenarios (some `false`, some
// `true`, some `sleep`) in a single test.
func modelWithProcs(t *testing.T, shells map[string]string) Model {
	t.Helper()
	f := false
	procs := make(map[string]config.ProcConfig, len(shells))
	for name, shell := range shells {
		procs[name] = config.ProcConfig{Shell: shell, Autostart: &f}
	}
	cfg := &config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	model := next.(Model)
	wireSend(&model)
	return model
}

// ── hasFailedProc ───────────────────────────────────────────────────────────────

func TestHasFailedProc_falseOnFreshModel(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	if m.hasFailedProc() {
		t.Error("fresh model with never-started procs should have no failed procs")
	}
}

func TestHasFailedProc_falseAfterCleanExit(t *testing.T) {
	// `true` shell exits 0 → StatusDone, NOT failed. This is the key
	// difference from "all stopped/crashed": a clean one-shot exit must
	// not be auto-restarted.
	m := modelWithProcs(t, map[string]string{"oneshot": "true"})
	runUntilStatus(t, findProc(t, m, "oneshot"), m.mgr.Send(), process.StatusDone)
	if m.hasFailedProc() {
		t.Error("clean exit (StatusDone) should not be considered failed")
	}
}

func TestHasFailedProc_trueAfterCrash(t *testing.T) {
	m := modelWithProcs(t, map[string]string{"flaky": "exit 1"})
	runUntilStatus(t, findProc(t, m, "flaky"), m.mgr.Send(), process.StatusCrashed)
	if !m.hasFailedProc() {
		t.Error("non-zero exit (StatusCrashed) should be considered failed")
	}
}

func TestHasFailedProc_falseAfterManualStop(t *testing.T) {
	// Manually-stopped procs sit at StatusStopped — user said stop, leave
	// them stopped. `R` must not undo a manual stop.
	m := modelWithProcs(t, map[string]string{"sleeper": "sleep 30"})
	p := findProc(t, m, "sleeper")
	if err := p.Start(m.mgr.Send()); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	deadline := time.After(2 * time.Second)
	for !p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("sleeper never started")
		case <-time.After(20 * time.Millisecond):
		}
	}
	p.Stop()

	if m.hasFailedProc() {
		t.Error("manually stopped proc (StatusStopped) should not be considered failed")
	}
}

func TestHasFailedProc_falseWhileRunning(t *testing.T) {
	m := modelWithProcs(t, map[string]string{"sleeper": "sleep 30"})
	p := findProc(t, m, "sleeper")
	if err := p.Start(m.mgr.Send()); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	t.Cleanup(func() { p.Stop() })

	deadline := time.After(2 * time.Second)
	for !p.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("sleeper never reached running state")
		case <-time.After(20 * time.Millisecond):
		}
	}

	if m.hasFailedProc() {
		t.Error("running procs should not be considered failed")
	}
}

// ── restartAllFailed ────────────────────────────────────────────────────────────

func TestRestartAllFailed_returnsZeroOnFreshModel(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	if n := m.restartAllFailed(); n != 0 {
		t.Errorf("restartAllFailed on fresh model: got %d, want 0", n)
	}
}

func TestRestartAllFailed_picksOnlyCrashed(t *testing.T) {
	m := modelWithProcs(t, map[string]string{
		"crash-a":   "exit 1",
		"crash-b":   "exit 2",
		"clean":     "true",
		"sleeper":   "sleep 30",
		"untouched": "exit 1",
	})
	send := m.mgr.Send()

	// Drive each proc to its terminal state, except "untouched" which we
	// leave as-is so it stays at the never-started StatusStopped.
	runUntilStatus(t, findProc(t, m, "crash-a"), send, process.StatusCrashed)
	runUntilStatus(t, findProc(t, m, "crash-b"), send, process.StatusCrashed)
	runUntilStatus(t, findProc(t, m, "clean"), send, process.StatusDone)

	sleeper := findProc(t, m, "sleeper")
	if err := sleeper.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	t.Cleanup(func() { sleeper.Stop() })
	deadline := time.After(2 * time.Second)
	for !sleeper.IsRunning() {
		select {
		case <-deadline:
			t.Fatal("sleeper never started")
		case <-time.After(20 * time.Millisecond):
		}
	}

	if n := m.restartAllFailed(); n != 2 {
		t.Errorf("restartAllFailed: got %d, want 2 (only crash-a and crash-b should count)", n)
	}

	// Belt and braces: the non-crashed procs must not have been touched.
	if findProc(t, m, "clean").Status() != process.StatusDone {
		t.Error("clean proc was touched")
	}
	if findProc(t, m, "untouched").Status() != process.StatusStopped {
		t.Error("never-started proc was touched")
	}
	if !sleeper.IsRunning() {
		t.Error("running sleeper was disturbed")
	}
}

// ── updateProcKeys: RestartAllFailed binding gating ──────────────────────────────

func TestUpdateProcKeys_RestartAllFailedDisabledWhenNothingFailed(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.updateProcKeys()
	if m.keys.RestartAllFailed.Enabled() {
		t.Error("RestartAllFailed should be disabled when no proc has crashed")
	}
}

func TestUpdateProcKeys_RestartAllFailedEnabledOnceOneCrashes(t *testing.T) {
	m := modelWithProcs(t, map[string]string{"flaky": "exit 1"})
	runUntilStatus(t, findProc(t, m, "flaky"), m.mgr.Send(), process.StatusCrashed)

	m.updateProcKeys()
	if !m.keys.RestartAllFailed.Enabled() {
		t.Error("RestartAllFailed should be enabled when at least one proc has crashed")
	}
}

// ── updateProcKeys: Restart binding gating ──────────────────────────────────────

// waitRunning blocks until the proc reaches IsRunning, registering a cleanup
// before the spin loop so a t.Fatal inside the loop doesn't leak the subprocess.
// Skips on PTY allocation failure.
func waitRunning(t *testing.T, p *process.Process, send func(tea.Msg)) {
	t.Helper()
	if err := p.Start(send); err != nil {
		t.Skipf("cannot spawn subprocess: %v", err)
	}
	t.Cleanup(func() { p.Stop() })
	deadline := time.After(2 * time.Second)
	for !p.IsRunning() {
		select {
		case <-deadline:
			t.Fatalf("proc %s never reached running state", p.Name)
		case <-time.After(20 * time.Millisecond):
		}
	}
}

// TestUpdateProcKeys_RestartBindingGating verifies the `r` (Restart) binding
// is enabled in exactly the states where it has meaningful work: a running
// proc (existing behavior) or a crashed proc (new behavior). Never-started,
// cleanly-exited, and manually-stopped procs are all the user's chosen end-
// state and must leave `r` disabled.
func TestUpdateProcKeys_RestartBindingGating(t *testing.T) {
	cases := []struct {
		name        string
		setup       func(t *testing.T) Model
		wantEnabled bool
	}{
		{
			name: "fresh proc (never started)",
			setup: func(t *testing.T) Model {
				return readyModel(t, "backend")
			},
			wantEnabled: false,
		},
		{
			name: "running proc",
			setup: func(t *testing.T) Model {
				m := modelWithProcs(t, map[string]string{"sleeper": "sleep 30"})
				waitRunning(t, findProc(t, m, "sleeper"), m.mgr.Send())
				return m
			},
			wantEnabled: true,
		},
		{
			name: "crashed proc",
			setup: func(t *testing.T) Model {
				m := modelWithProcs(t, map[string]string{"flaky": "exit 1"})
				runUntilStatus(t, findProc(t, m, "flaky"), m.mgr.Send(), process.StatusCrashed)
				return m
			},
			wantEnabled: true,
		},
		{
			name: "clean exit",
			setup: func(t *testing.T) Model {
				m := modelWithProcs(t, map[string]string{"oneshot": "true"})
				runUntilStatus(t, findProc(t, m, "oneshot"), m.mgr.Send(), process.StatusDone)
				return m
			},
			wantEnabled: false,
		},
		{
			name: "manually stopped",
			setup: func(t *testing.T) Model {
				m := modelWithProcs(t, map[string]string{"sleeper": "sleep 30"})
				p := findProc(t, m, "sleeper")
				waitRunning(t, p, m.mgr.Send())
				p.Stop()
				return m
			},
			wantEnabled: false,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := tc.setup(t)
			m.updateProcKeys()
			if got := m.keys.Restart.Enabled(); got != tc.wantEnabled {
				t.Errorf("Restart.Enabled() = %v, want %v", got, tc.wantEnabled)
			}
		})
	}
}

// ── `r` keypress on a crashed proc actually restarts it ─────────────────────────

func TestHandleNormalKey_RestartKeyRevivesCrashedProc(t *testing.T) {
	// End-to-end check that pressing `r` on a crashed proc kicks off Start
	// (not just that the binding is enabled). We use `sleep 30` as the shell
	// — once the second start fires, the proc should be running again.
	m := modelWithProcs(t, map[string]string{"flaky": "exit 1"})
	runUntilStatus(t, findProc(t, m, "flaky"), m.mgr.Send(), process.StatusCrashed)

	// Swap the shell to a long-running command so the post-`r` start lands on
	// a process that won't immediately crash again — lets us observe the
	// running state without races.
	p := findProc(t, m, "flaky")
	p.Cfg.Shell = "sleep 30"
	t.Cleanup(func() { p.Stop() })

	m.updateProcKeys()
	if !m.keys.Restart.Enabled() {
		t.Fatal("precondition: Restart binding should be enabled on a crashed proc")
	}

	next, _ := m.Update(keypress('r'))
	_ = next

	deadline := time.After(2 * time.Second)
	for !p.IsRunning() {
		select {
		case <-deadline:
			t.Fatalf("crashed proc never restarted (status: %s)", p.Status())
		case <-time.After(20 * time.Millisecond):
		}
	}
}
