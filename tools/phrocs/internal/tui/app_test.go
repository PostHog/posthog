package tui

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// testManager creates a Manager with the named stub processes (no autostart).
func testManager(names ...string) *process.Manager {
	f := false
	procs := make(map[string]config.ProcConfig, len(names))
	for _, n := range names {
		procs[n] = config.ProcConfig{Shell: "true", Autostart: &f}
	}
	return process.NewManager(&config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	})
}

// readyModel returns a model that has processed a WindowSizeMsg and is ready.
func readyModel(t *testing.T, names ...string) Model {
	t.Helper()
	mgr := testManager(names...)
	m := New(mgr, 3, nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	return next.(Model)
}

func keypress(r rune) tea.KeyPressMsg {
	return tea.KeyPressMsg{Code: r, Text: string(r)}
}

func specialKey(code rune) tea.KeyPressMsg {
	return tea.KeyPressMsg{Code: code}
}

func update(m Model, msg tea.Msg) Model {
	next, _ := m.Update(msg)
	return next.(Model)
}

// ── New() initial state ───────────────────────────────────────────────────────

func TestNew_initialState(t *testing.T) {
	mgr := testManager("backend", "frontend")
	m := New(mgr, 3, nil)
	if m.ready {
		t.Error("model should not be ready before WindowSizeMsg")
	}
	if m.cursor != 0 {
		t.Errorf("cursor: got %d, want 0", m.cursor)
	}
	if m.focusedPane != focusSidebar {
		t.Error("initial focus should be sidebar")
	}
	if !m.atBottom {
		t.Error("atBottom should be true initially")
	}
	if m.copyMode {
		t.Error("should not be in copy mode initially")
	}
}

func TestUpdate_windowSizeSetsReady(t *testing.T) {
	mgr := testManager("backend")
	m := New(mgr, 3, nil)
	m = update(m, tea.WindowSizeMsg{Width: 120, Height: 40})
	if !m.ready {
		t.Error("model should be ready after WindowSizeMsg")
	}
	if m.width != 120 {
		t.Errorf("width: got %d, want 120", m.width)
	}
	if m.height != 40 {
		t.Errorf("height: got %d, want 40", m.height)
	}
}

// ── Sidebar navigation ────────────────────────────────────────────────────────

func TestNavigation_nextProc(t *testing.T) {
	m := readyModel(t, "backend", "celery", "frontend")
	// k = next proc
	m = update(m, keypress('k'))
	if m.cursor != 1 {
		t.Errorf("cursor after k: got %d, want 1", m.cursor)
	}
	m = update(m, keypress('k'))
	if m.cursor != 2 {
		t.Errorf("cursor after k k: got %d, want 2", m.cursor)
	}
}

func TestNavigation_prevProc(t *testing.T) {
	m := readyModel(t, "backend", "celery", "frontend")
	m.cursor = 2
	// j = prev proc
	m = update(m, keypress('j'))
	if m.cursor != 1 {
		t.Errorf("cursor after j: got %d, want 1", m.cursor)
	}
}

func TestNavigation_clampsAtBottom(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.cursor = 1
	m = update(m, keypress('k'))
	if m.cursor != 1 {
		t.Errorf("cursor should clamp at %d, got %d", 1, m.cursor)
	}
}

func TestNavigation_clampsAtTop(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.cursor = 0
	m = update(m, keypress('j'))
	if m.cursor != 0 {
		t.Errorf("cursor should clamp at 0, got %d", m.cursor)
	}
}

func TestNavigation_arrowKeys(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m = update(m, specialKey(tea.KeyDown))
	if m.cursor != 1 {
		t.Errorf("cursor after down: got %d, want 1", m.cursor)
	}
	m = update(m, specialKey(tea.KeyUp))
	if m.cursor != 0 {
		t.Errorf("cursor after up: got %d, want 0", m.cursor)
	}
}

// ── Focus ─────────────────────────────────────────────────────────────────────

func TestFocus_swapWithTab(t *testing.T) {
	m := readyModel(t, "backend")
	if m.focusedPane != focusSidebar {
		t.Fatal("expected sidebar focus initially")
	}
	m = update(m, specialKey(tea.KeyTab))
	if m.focusedPane != focusOutput {
		t.Error("tab should switch to output focus")
	}
	m = update(m, specialKey(tea.KeyTab))
	if m.focusedPane != focusSidebar {
		t.Error("second tab should return to sidebar focus")
	}
}

func TestFocus_mouseClickSidebar(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	// Click second row in sidebar (row 1 = y=headerHeight+1)
	m = update(m, tea.MouseClickMsg{Button: tea.MouseLeft, X: 5, Y: headerHeight + 1})
	if m.focusedPane != focusSidebar {
		t.Error("click in sidebar should focus sidebar")
	}
	if m.cursor != 1 {
		t.Errorf("click on row 1: cursor should be 1, got %d", m.cursor)
	}
}

func TestFocus_mouseClickOutput(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, tea.MouseClickMsg{Button: tea.MouseLeft, X: sidebarWidth + 10, Y: 5})
	if m.focusedPane != focusOutput {
		t.Error("click in output pane should focus output")
	}
}

// ── Help ──────────────────────────────────────────────────────────────────────

func TestHelp_toggle(t *testing.T) {
	m := readyModel(t, "backend")
	if m.showHelp {
		t.Fatal("showHelp should be false initially")
	}
	m = update(m, keypress('?'))
	if !m.showHelp {
		t.Error("? should show help")
	}
	m = update(m, keypress('?'))
	if m.showHelp {
		t.Error("second ? should hide help")
	}
}

// ── Copy mode ─────────────────────────────────────────────────────────────────

func TestCopyMode_enterAndExit(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('c'))
	if !m.copyMode {
		t.Error("c should enter copy mode")
	}
	if m.copyAnchor != -1 {
		t.Errorf("copyAnchor should be -1 on entry, got %d", m.copyAnchor)
	}
	m = update(m, specialKey(tea.KeyEscape))
	if m.copyMode {
		t.Error("esc should exit copy mode")
	}
}

func TestCopyMode_setAnchor(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('c')) // enter copy mode
	// First c press in copy mode sets the anchor at the current cursor position
	m = update(m, keypress('c'))
	if m.copyAnchor != m.copyCursor {
		t.Errorf("first c in copy mode should set anchor to copyCursor (%d), got %d", m.copyCursor, m.copyAnchor)
	}
}

func TestCopyMode_navigation(t *testing.T) {
	m := readyModel(t, "backend")
	// Populate some lines so the viewport has content to navigate.
	// AppendLine mirrors the readLoop append step; OutputMsg triggers the TUI
	// to rebuild the viewport from p.Lines().
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"line 1", "line 2", "line 3"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend", Line: line})
	}
	m = update(m, keypress('c')) // enter copy mode
	initial := m.copyCursor

	// k = next line in copy mode
	m = update(m, keypress('k'))
	if m.copyCursor != initial+1 {
		t.Errorf("k in copy mode: copyCursor want %d, got %d", initial+1, m.copyCursor)
	}
	// j = prev line in copy mode
	m = update(m, keypress('j'))
	if m.copyCursor != initial {
		t.Errorf("j in copy mode: copyCursor want %d, got %d", initial, m.copyCursor)
	}
}

func TestCopyMode_exitOnProcSwitch(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m = update(m, keypress('c'))
	if !m.copyMode {
		t.Fatal("should be in copy mode")
	}
	// Mouse-clicking a different process in the sidebar calls loadActiveProc,
	// which always exits copy mode.
	m = update(m, tea.MouseClickMsg{Button: tea.MouseLeft, X: 5, Y: headerHeight + 1})
	if m.copyMode {
		t.Error("switching process should exit copy mode")
	}
}

// ── Process output and status messages ───────────────────────────────────────

func TestOutputMsg_activeProc(t *testing.T) {
	m := readyModel(t, "backend")
	// AppendLine puts the line into p.lines so buildContent sees it when the
	// TUI handles the OutputMsg.
	p, _ := m.mgr.Get("backend")
	p.AppendLine("hello world")
	before := m.viewport.TotalLineCount()
	m = update(m, process.OutputMsg{Name: "backend", Line: "hello world"})
	after := m.viewport.TotalLineCount()
	if after != before+1 {
		t.Errorf("OutputMsg for active proc: line count want %d, got %d", before+1, after)
	}
}

func TestOutputMsg_inactiveProc(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	// cursor is on backend (index 0); send output for frontend
	before := m.viewport.TotalLineCount()
	m = update(m, process.OutputMsg{Name: "frontend", Line: "not visible"})
	after := m.viewport.TotalLineCount()
	if after != before {
		t.Error("OutputMsg for inactive proc should not update viewport")
	}
}

func TestStatusMsg_updatesCursor(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.cursor = 1
	// Simulate enough removals to make cursor out of bounds — a StatusMsg
	// should clamp cursor safely.  We can't actually remove procs without
	// Manager internals, so just verify that a StatusMsg for a known proc
	// doesn't panic and doesn't move the cursor unnecessarily.
	m = update(m, process.StatusMsg{Name: "backend", Status: process.StatusRunning})
	if m.cursor > len(m.procs)-1 {
		t.Errorf("cursor %d out of bounds after StatusMsg", m.cursor)
	}
}

// ── Viewport scroll anchors ───────────────────────────────────────────────────

func TestGotoBottom_setsAtBottom(t *testing.T) {
	m := readyModel(t, "backend")
	m.atBottom = false
	m = update(m, specialKey(tea.KeyEnd))
	if !m.atBottom {
		t.Error("end key should set atBottom=true")
	}
}

func TestGotoTop_clearsAtBottom(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, specialKey(tea.KeyHome))
	if m.atBottom {
		t.Error("home key should set atBottom=false")
	}
}
