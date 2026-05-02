package tui

import (
	"os"
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// readyShowAllModel creates a model with a small set of "active" processes and
// a registry config that has additional processes. The registry is injected
// directly via standbyRegProcs rather than requiring bin/mprocs.yaml on disk.
func readyShowAllModel(t *testing.T) Model {
	t.Helper()
	f := false
	procs := map[string]config.ProcConfig{
		"backend":  {Shell: "start-backend", Autostart: &f, Groups: map[string]string{"layer": "Application", "tech": "Python"}},
		"frontend": {Shell: "start-frontend", Autostart: &f, Groups: map[string]string{"layer": "Application", "tech": "Frontend"}},
	}
	cfg := &config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
		GroupOrder: map[string][]string{
			"layer": {"Application", "Processing", "Ingestion", "Infrastructure"},
			"tech":  {"Python", "Frontend", "Rust", "Docker"},
		},
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	model := next.(Model)

	// Inject standby processes as if loaded from registry
	model.standbyRegProcs = []*process.Process{
		process.NewStandbyProcess("capture", config.ProcConfig{
			Shell:      "start-rust-service capture",
			Capability: "event_ingestion",
			Groups:     map[string]string{"layer": "Ingestion", "tech": "Rust"},
		}),
		process.NewStandbyProcess("celery-worker", config.ProcConfig{
			Shell:      "start-celery worker",
			Capability: "celery_workers",
			Groups:     map[string]string{"layer": "Processing", "tech": "Python"},
		}),
		process.NewStandbyProcess("docker-compose", config.ProcConfig{
			Shell:  "docker compose up",
			Groups: map[string]string{"layer": "Infrastructure", "tech": "Docker"},
		}),
	}

	return model
}

// ── Toggle ──────────────────────────────────────────────────────────────────────

func TestShowAll_toggleAddsStandby(t *testing.T) {
	m := readyShowAllModel(t)
	if len(m.services) != 2 {
		t.Fatalf("initial: want 2 services, got %d", len(m.services))
	}

	// Toggle on
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	if len(m.services) != 5 {
		t.Fatalf("show all on: want 5 services, got %d", len(m.services))
	}

	// Verify standby processes are present
	standbyCount := 0
	for _, p := range m.services {
		if p.IsStandby() {
			standbyCount++
		}
	}
	if standbyCount != 3 {
		t.Errorf("want 3 standby procs, got %d", standbyCount)
	}
}

func TestShowAll_toggleOffRemovesStandby(t *testing.T) {
	m := readyShowAllModel(t)

	// Toggle on then off
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()
	m.showAllRegProcs = false
	m.refetchServices()
	m.sortServices()

	if len(m.services) != 2 {
		t.Fatalf("show all off: want 2 services, got %d", len(m.services))
	}
	for _, p := range m.services {
		if p.IsStandby() {
			t.Error("no standby procs should remain after toggle off")
		}
	}
}

// ── Config preservation ─────────────────────────────────────────────────────────

func TestShowAll_restoreConfigPreservesRuntimeSettings(t *testing.T) {
	// When toggling off, only Procs and GroupOrder should be replaced from disk.
	// Other config fields (Scrollback, MouseScrollSpeed, etc.) must be preserved
	// so runtime changes (e.g. from setup mode) survive the toggle.
	dir := t.TempDir()
	configPath := filepath.Join(dir, "mprocs.yaml")
	if err := os.WriteFile(configPath, []byte("procs:\n  backend: {shell: echo}\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	f := false
	cfg := &config.Config{
		Procs:            map[string]config.ProcConfig{"backend": {Shell: "echo", Autostart: &f}},
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, configPath, nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	model := next.(Model)

	// Simulate runtime mutation of non-Procs, non-GroupOrder fields
	model.cfg.MouseScrollSpeed = 99
	model.cfg.Scrollback = 42

	model.restoreConfigFromDisk()

	if model.cfg.MouseScrollSpeed != 99 {
		t.Errorf("MouseScrollSpeed should be preserved, got %d", model.cfg.MouseScrollSpeed)
	}
	if model.cfg.Scrollback != 42 {
		t.Errorf("Scrollback should be preserved, got %d", model.cfg.Scrollback)
	}
}

// ── Standby sort order ──────────────────────────────────────────────────────────

func TestShowAll_standbySortOrder(t *testing.T) {
	m := readyShowAllModel(t)
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortMode = SortStatus
	m.sortServices()

	// Standby processes should sort last
	lastRealIdx := -1
	firstStandbyIdx := -1
	for i, p := range m.services {
		if !p.IsStandby() {
			lastRealIdx = i
		}
		if p.IsStandby() && firstStandbyIdx == -1 {
			firstStandbyIdx = i
		}
	}
	if firstStandbyIdx <= lastRealIdx {
		t.Errorf("standby procs should sort after real procs, got first standby at %d, last real at %d",
			firstStandbyIdx, lastRealIdx)
	}
}

// ── Grouping interaction ────────────────────────────────────────────────────────

func TestShowAll_standbyAppearsInGroups(t *testing.T) {
	m := readyShowAllModel(t)
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	// Enable grouping by layer
	m.groupDimIndex = 0
	for i, d := range m.groupDims {
		if d == "layer" {
			m.groupDimIndex = i
			break
		}
	}
	m.rebuildSidebarEntries()

	// Check that standby processes appear under their correct group headers
	foundCapture := false
	for i, e := range m.sidebarEntries {
		if e.proc != nil && e.proc.Name == "capture" {
			foundCapture = true
			// Walk back to find the group header
			for j := i - 1; j >= 0; j-- {
				if m.sidebarEntries[j].isHeader() {
					if m.sidebarEntries[j].groupHeader != "Ingestion" {
						t.Errorf("capture should be under Ingestion, got %q", m.sidebarEntries[j].groupHeader)
					}
					break
				}
			}
		}
	}
	if !foundCapture {
		t.Error("capture standby should appear in grouped entries")
	}
}

// ── Navigation ──────────────────────────────────────────────────────────────────

func TestShowAll_navigationIncludesStandby(t *testing.T) {
	m := readyShowAllModel(t)
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	// Navigate through all processes
	visited := make(map[string]bool)
	for i := 0; i < len(m.services); i++ {
		if p := m.activeProc(); p != nil {
			visited[p.Name] = true
		}
		m = update(m, keypress('j'))
	}

	for _, name := range []string{"backend", "frontend", "capture", "celery-worker", "docker-compose"} {
		if !visited[name] {
			t.Errorf("should be able to navigate to %s", name)
		}
	}
}

// ── Cursor preservation ─────────────────────────────────────────────────────────

func TestShowAll_cursorPreservedOnToggle(t *testing.T) {
	m := readyShowAllModel(t)

	// Select frontend
	for i, p := range m.services {
		if p.Name == "frontend" {
			m.servicesCursor = i
			break
		}
	}

	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	if p := m.activeProc(); p == nil || p.Name != "frontend" {
		name := ""
		if p := m.activeProc(); p != nil {
			name = p.Name
		}
		t.Errorf("cursor should stay on frontend after toggle on, got %q", name)
	}

	m.showAllRegProcs = false
	m.refetchServices()
	m.sortServices()

	if p := m.activeProc(); p == nil || p.Name != "frontend" {
		name := ""
		if p := m.activeProc(); p != nil {
			name = p.Name
		}
		t.Errorf("cursor should stay on frontend after toggle off, got %q", name)
	}
}

// ── Key enablement ──────────────────────────────────────────────────────────────

func TestShowAll_keyEnablementByProcState(t *testing.T) {
	// Expected key enablement for each process state. Ensures standby processes
	// only expose Start, while other states follow the running/stopped rules.
	cases := []struct {
		name        string
		procName    string // name of the process to focus on (from readyShowAllModel)
		wantStart   bool
		wantStop    bool
		wantRestart bool
	}{
		{name: "standby", procName: "capture", wantStart: true},
		{name: "stopped", procName: "backend", wantStart: true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			m := readyShowAllModel(t)
			m.showAllRegProcs = true
			m.refetchServices()
			m.sortServices()

			for i, p := range m.services {
				if p.Name == tc.procName {
					m.servicesCursor = i
					break
				}
			}
			m.updateProcKeys()

			if m.keys.Start.Enabled() != tc.wantStart {
				t.Errorf("Start: got %v, want %v", m.keys.Start.Enabled(), tc.wantStart)
			}
			if m.keys.Stop.Enabled() != tc.wantStop {
				t.Errorf("Stop: got %v, want %v", m.keys.Stop.Enabled(), tc.wantStop)
			}
			if m.keys.Restart.Enabled() != tc.wantRestart {
				t.Errorf("Restart: got %v, want %v", m.keys.Restart.Enabled(), tc.wantRestart)
			}
		})
	}
}

// ── Promote standby ─────────────────────────────────────────────────────────────

func TestShowAll_promoteStandbyToReal(t *testing.T) {
	m := readyShowAllModel(t)
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	// Navigate to capture (standby)
	for i, p := range m.services {
		if p.Name == "capture" {
			m.servicesCursor = i
			break
		}
	}

	if p := m.activeProc(); p == nil || !p.IsStandby() {
		t.Fatal("active proc should be standby capture")
	}

	real, ok := m.promoteStandby()
	if !ok {
		t.Fatal("promoteStandby should succeed")
	}
	if real.Name != "capture" {
		t.Errorf("promoted proc name: got %q, want capture", real.Name)
	}
	if real.IsStandby() {
		t.Error("promoted proc should not be standby")
	}

	// capture should no longer be in standbyRegProcs
	for _, p := range m.standbyRegProcs {
		if p.Name == "capture" {
			t.Error("capture should be removed from standbyRegProcs after promotion")
		}
	}

	// It should still appear in services (as real)
	found := false
	for _, p := range m.services {
		if p.Name == "capture" {
			found = true
			if p.IsStandby() {
				t.Error("capture in services should be real, not standby")
			}
		}
	}
	if !found {
		t.Error("capture should still appear in services after promotion")
	}
}

func TestShowAll_promotedProcessSurvivesToggleOff(t *testing.T) {
	m := readyShowAllModel(t)
	m.showAllRegProcs = true
	m.refetchServices()
	m.sortServices()

	// Promote capture
	for i, p := range m.services {
		if p.Name == "capture" {
			m.servicesCursor = i
			break
		}
	}
	m.promoteStandby()

	// Toggle off — promoted process should remain (it's real now)
	m.showAllRegProcs = false
	m.refetchServices()
	m.sortServices()

	found := false
	for _, p := range m.services {
		if p.Name == "capture" {
			found = true
		}
	}
	if !found {
		t.Error("promoted process should survive toggle-off")
	}
}
