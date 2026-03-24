package tui

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/docker"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// testConfig creates a Config with the named stub processes (no autostart).
func testConfig(names ...string) *config.Config {
	f := false
	procs := make(map[string]config.ProcConfig, len(names))
	for _, n := range names {
		procs[n] = config.ProcConfig{Shell: "true", Autostart: &f}
	}
	return &config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
}

// readyModel returns a model that has processed a WindowSizeMsg and is ready.
func readyModel(t *testing.T, names ...string) Model {
	t.Helper()
	cfg := testConfig(names...)
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	return next.(Model)
}

func readyDockerModel(t *testing.T) Model {
	t.Helper()
	f := false
	cfg := &config.Config{
		Procs: map[string]config.ProcConfig{
			"docker": {Shell: "docker compose -f docker-compose.dev.yml up", Autostart: &f},
		},
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	dockerModel := next.(Model)
	dockerModel.containers = []docker.DockerContainer{{Service: "web"}}
	dockerModel.containerCursor = 1
	dockerModel.containerLines = []string{"regular line", "error: failed"}
	return dockerModel
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
	cfg := testConfig("backend", "frontend")
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, nil)
	if m.ready {
		t.Error("model should not be ready before WindowSizeMsg")
	}
	if m.servicesCursor != 0 {
		t.Errorf("cursor: got %d, want 0", m.servicesCursor)
	}
	if m.focusedPane != focusServices {
		t.Error("initial focus should be sidebar")
	}
	if !m.viewportAtBottom {
		t.Error("atBottom should be true initially")
	}
	if m.copyMode {
		t.Error("should not be in copy mode initially")
	}
}

func TestUpdate_windowSizeSetsReady(t *testing.T) {
	cfg := testConfig("backend")
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, nil)
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
	// j = next proc
	m = update(m, keypress('j'))
	if m.servicesCursor != 1 {
		t.Errorf("cursor after j: got %d, want 1", m.servicesCursor)
	}
	m = update(m, keypress('j'))
	if m.servicesCursor != 2 {
		t.Errorf("cursor after j j: got %d, want 2", m.servicesCursor)
	}
}

func TestNavigation_prevProc(t *testing.T) {
	m := readyModel(t, "backend", "celery", "frontend")
	m.servicesCursor = 2
	// k = prev proc
	m = update(m, keypress('k'))
	if m.servicesCursor != 1 {
		t.Errorf("cursor after k: got %d, want 1", m.servicesCursor)
	}
}

func TestNavigation_clampsAtBottom(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.servicesCursor = 1
	m = update(m, keypress('j'))
	if m.servicesCursor != 1 {
		t.Errorf("cursor should clamp at %d, got %d", 1, m.servicesCursor)
	}
}

func TestNavigation_clampsAtTop(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.servicesCursor = 0
	m = update(m, keypress('k'))
	if m.servicesCursor != 0 {
		t.Errorf("cursor should clamp at 0, got %d", m.servicesCursor)
	}
}

func TestNavigation_arrowKeys(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m = update(m, specialKey(tea.KeyDown))
	if m.servicesCursor != 1 {
		t.Errorf("cursor after down: got %d, want 1", m.servicesCursor)
	}
	m = update(m, specialKey(tea.KeyUp))
	if m.servicesCursor != 0 {
		t.Errorf("cursor after up: got %d, want 0", m.servicesCursor)
	}
}

// ── Focus ─────────────────────────────────────────────────────────────────────

func TestFocus_swapWithTab(t *testing.T) {
	m := readyModel(t, "backend")
	if m.focusedPane != focusServices {
		t.Fatal("expected sidebar focus initially")
	}
	m = update(m, specialKey(tea.KeyTab))
	if m.focusedPane != focusOutput {
		t.Error("tab should switch to output focus")
	}
	m = update(m, specialKey(tea.KeyTab))
	if m.focusedPane != focusServices {
		t.Error("second tab should return to sidebar focus")
	}
}

func TestFocus_mouseClickSidebar(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	// Click second row in sidebar: header (1) + top border (1) + first row (1) = Y=3
	m = update(m, tea.MouseClickMsg{Button: tea.MouseLeft, X: 5, Y: headerHeight + 2})
	if m.focusedPane != focusServices {
		t.Error("click in sidebar should focus sidebar")
	}
	if m.servicesCursor != 1 {
		t.Errorf("click on row 1: cursor should be 1, got %d", m.servicesCursor)
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
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"line 1", "line 2", "line 3"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = update(m, keypress('c')) // enter copy mode
	initial := m.copyCursor

	// j = next line in copy mode
	m = update(m, keypress('j'))
	if m.copyCursor != initial+1 {
		t.Errorf("j in copy mode: copyCursor want %d, got %d", initial+1, m.copyCursor)
	}
	// k = prev line in copy mode
	m = update(m, keypress('k'))
	if m.copyCursor != initial {
		t.Errorf("k in copy mode: copyCursor want %d, got %d", initial, m.copyCursor)
	}
}

func TestCopyMode_exitOnProcSwitch(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m = update(m, keypress('c'))
	if !m.copyMode {
		t.Fatal("should be in copy mode")
	}
	// Mouse-clicking a different process in the sidebar calls loadActiveProc,
	// which always exits copy mode. Y=headerHeight+2 hits the second sidebar row.
	m = update(m, tea.MouseClickMsg{Button: tea.MouseLeft, X: 5, Y: headerHeight + 2})
	if m.copyMode {
		t.Error("switching process should exit copy mode")
	}
}

// ── Search ────────────────────────────────────────────────────────────────────

func TestSearch_enterAndExit(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('/'))
	if !m.searchMode {
		t.Error("/ should enter search mode")
	}
	m = update(m, specialKey(tea.KeyEscape))
	if m.searchMode {
		t.Error("esc should exit search mode")
	}
	if m.searchQuery != "" {
		t.Error("esc should clear query")
	}
}

func TestSearch_typeQuery(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))
	if m.searchQuery != "err" {
		t.Errorf("typed 'err', got %q", m.searchQuery)
	}
}

func TestSearch_spaceInQuery(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('/'))
	m = update(m, keypress('h'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeySpace, Text: "space"})
	m = update(m, keypress('w'))
	if m.searchQuery != "h w" {
		t.Errorf("space in query: want %q, got %q", "h w", m.searchQuery)
	}
}

func TestSearch_backspace(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeyBackspace, Text: "backspace"})
	if m.searchQuery != "e" {
		t.Errorf("after backspace want %q, got %q", "e", m.searchQuery)
	}
}

func TestSearch_matchesHighlighted(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"hello world", "error here", "another error"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))
	if len(m.searchMatches) != 2 {
		t.Errorf("want 2 matches for 'err', got %d", len(m.searchMatches))
	}
}

func TestSearch_enterConfirmsAndKeepsMatches(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"foo", "bar", "foo again"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = update(m, keypress('/'))
	m = update(m, keypress('f'))
	m = update(m, keypress('o'))
	m = update(m, keypress('o'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if m.searchQuery != "foo" {
		t.Errorf("query should be preserved after enter, got %q", m.searchQuery)
	}
	if len(m.searchMatches) != 2 {
		t.Errorf("matches should persist after enter, want 2 got %d", len(m.searchMatches))
	}
}

func TestSearch_navigateWithEnter(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"match one", "no match", "match two"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	// Enter search and confirm
	m = update(m, keypress('/'))
	for _, ch := range "match" {
		m = update(m, keypress(ch))
	}
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if m.searchCursor != 1 {
		t.Fatalf("after enter cursor should be 1, got %d", m.searchCursor)
	}
	// ↵ → next match
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if m.searchCursor != 2 {
		t.Errorf("enter: want cursor 2, got %d", m.searchCursor)
	}
	// ⇧↵ → prev match
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Mod: tea.ModShift, Text: "shift+enter"})
	if m.searchCursor != 1 {
		t.Errorf("shift+enter: want cursor 1, got %d", m.searchCursor)
	}
}

func TestSearch_incrementalUpdate(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	// Seed two lines, start a search, then deliver a new matching line.
	for _, line := range []string{"error log", "info log"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	// Activate search
	m = update(m, keypress('/'))
	for _, ch := range "error" {
		m = update(m, keypress(ch))
	}
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if len(m.searchMatches) != 1 {
		t.Fatalf("want 1 match for 'error', got %d", len(m.searchMatches))
	}
	// New matching line arrives — recomputeSearch picks it up
	p.AppendLine("another error")
	m = update(m, process.OutputMsg{Name: "backend"})
	if len(m.searchMatches) != 2 {
		t.Errorf("after new matching line: want 2 matches, got %d", len(m.searchMatches))
	}
}

func TestSearch_eviction(t *testing.T) {
	// Use a tiny scrollback (3 lines) so eviction happens quickly.
	f := false
	cfg := &config.Config{
		Procs:            map[string]config.ProcConfig{"svc": {Shell: "true", Autostart: &f}},
		MouseScrollSpeed: 3,
		Scrollback:       3,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, nil)
	m = update(m, tea.WindowSizeMsg{Width: 120, Height: 40})
	p, _ := mgr.Get("svc")

	// Fill the scrollback: lines 0,1,2 = "err0","ok1","err2"
	for _, line := range []string{"err0", "ok1", "err2"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "svc"})
	}
	// Search for "err" → matches at indices 0 and 2
	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if len(m.searchMatches) != 2 {
		t.Fatalf("want 2 matches, got %d", len(m.searchMatches))
	}

	// Append "ok3" — evicts "err0" (index 0).
	// Buffer becomes: ["ok1","err2","ok3"] at indices 0,1,2.
	// "err0" is gone; "err2" shifts to index 1; new line "ok3" at index 2.
	p.AppendLine("ok3")
	m = update(m, process.OutputMsg{Name: "svc"})
	if len(m.searchMatches) != 1 {
		t.Errorf("after evicting matching line: want 1 match, got %d", len(m.searchMatches))
	}
	if m.searchMatches[0] != 1 {
		t.Errorf("surviving match should be at index 1, got %d", m.searchMatches[0])
	}
}

func TestSearch_escClearsActiveSearch(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	p.AppendLine("something")
	m = update(m, process.OutputMsg{Name: "backend"})
	// Build a search result, then exit typing mode
	m = update(m, keypress('/'))
	m = update(m, keypress('s'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeyEnter, Text: "enter"})
	if m.searchQuery == "" {
		t.Fatal("search query should be set")
	}
	// Esc in normal mode should clear the search
	m = update(m, specialKey(tea.KeyEscape))
	if m.searchQuery != "" {
		t.Error("esc in normal mode should clear search query")
	}
	if len(m.searchMatches) != 0 {
		t.Error("esc should clear search matches")
	}
}

func TestSearch_dockerUsesContainerLogs(t *testing.T) {
	m := readyDockerModel(t)

	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))

	if len(m.searchMatches) != 1 {
		t.Fatalf("want 1 docker log match for 'err', got %d", len(m.searchMatches))
	}
	if m.searchMatches[0] != 1 {
		t.Fatalf("docker match index: want 1, got %d", m.searchMatches[0])
	}
}

func TestSearch_dockerIgnoresProcessLines(t *testing.T) {
	m := readyDockerModel(t)
	p, _ := m.mgr.Get("docker")
	p.AppendLine("error from process stream")

	m = update(m, keypress('/'))
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))

	if len(m.searchMatches) != 1 {
		t.Fatalf("want 1 match from container logs only, got %d", len(m.searchMatches))
	}
	if m.searchMatches[0] != 1 {
		t.Fatalf("docker match index: want 1, got %d", m.searchMatches[0])
	}
}

func TestSearch_dockerIncrementalLogLineUpdatesMatches(t *testing.T) {
	m := readyDockerModel(t)
	m.searchQuery = "err"
	m.recomputeSearch()

	m = update(m, docker.ContainerLogLineMsg{Service: "web", Line: "new error line"})

	if len(m.searchMatches) != 2 {
		t.Fatalf("want 2 matches after new docker log line, got %d", len(m.searchMatches))
	}
	if m.searchMatches[1] != 2 {
		t.Fatalf("new docker match index: want 2, got %d", m.searchMatches[1])
	}
}

func TestCopySelectedText_dockerUsesContainerLogs(t *testing.T) {
	m := readyDockerModel(t)
	m.containerLines = []string{"first", "\x1b[31msecond\x1b[0m", "third"}
	m.copyMode = true
	m.copyAnchor = 0
	m.copyCursor = 1

	got := m.copySelectedText()
	want := "first\nsecond"
	if got != want {
		t.Fatalf("copySelectedText docker: want %q, got %q", want, got)
	}
}

// ── Process output and status messages ───────────────────────────────────────

func TestOutputMsg_activeProc(t *testing.T) {
	m := readyModel(t, "backend")
	// AppendLine puts the line into p.lines; OutputMsg triggers buildContent.
	p, _ := m.mgr.Get("backend")
	p.AppendLine("hello world")
	before := m.viewport.TotalLineCount()
	m = update(m, process.OutputMsg{Name: "backend"})
	after := m.viewport.TotalLineCount()
	if after != before+1 {
		t.Errorf("OutputMsg for active proc: line count want %d, got %d", before+1, after)
	}
}

func TestOutputMsg_inactiveProc(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	// cursor is on backend (index 0); send output for frontend
	before := m.viewport.TotalLineCount()
	m = update(m, process.OutputMsg{Name: "frontend"})
	after := m.viewport.TotalLineCount()
	if after != before {
		t.Error("OutputMsg for inactive proc should not update viewport")
	}
}

func TestStatusMsg_updatesCursor(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	m.servicesCursor = 1
	// Simulate enough removals to make cursor out of bounds — a StatusMsg
	// should clamp cursor safely.  We can't actually remove procs without
	// Manager internals, so just verify that a StatusMsg for a known proc
	// doesn't panic and doesn't move the cursor unnecessarily.
	m = update(m, process.StatusMsg{Name: "backend", Status: process.StatusRunning})
	if m.servicesCursor > len(m.services)-1 {
		t.Errorf("cursor %d out of bounds after StatusMsg", m.servicesCursor)
	}
}

// ── Viewport scroll anchors ───────────────────────────────────────────────────

func TestGotoBottom_setsAtBottom(t *testing.T) {
	m := readyModel(t, "backend")
	m.viewportAtBottom = false
	m = update(m, specialKey(tea.KeyEnd))
	if !m.viewportAtBottom {
		t.Error("end key should set atBottom=true")
	}
}

func TestGotoTop_clearsAtBottom(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, specialKey(tea.KeyHome))
	if m.viewportAtBottom {
		t.Error("home key should set atBottom=false")
	}
}

// ── Sorting ──────────────────────────────────────────────────────────────────

func serviceNames(m Model) []string {
	names := make([]string, len(m.services))
	for i, p := range m.services {
		names[i] = p.Name
	}
	return names
}

func TestSort_defaultIsName(t *testing.T) {
	m := readyModel(t, "frontend", "backend", "celery")
	got := serviceNames(m)
	want := []string{"backend", "celery", "frontend"}
	for i, n := range got {
		if n != want[i] {
			t.Errorf("index %d: got %q, want %q (full: %v)", i, n, want[i], got)
		}
	}
}

func TestSort_cycleWithO(t *testing.T) {
	m := readyModel(t, "backend", "frontend")
	if m.sortMode != SortName {
		t.Fatalf("initial sort mode: got %v, want SortName", m.sortMode)
	}
	m = update(m, keypress('o'))
	if m.sortMode != SortCPU {
		t.Errorf("after first o: got %v, want SortCPU", m.sortMode)
	}
	m = update(m, keypress('o'))
	if m.sortMode != SortRAM {
		t.Errorf("after second o: got %v, want SortRAM", m.sortMode)
	}
	m = update(m, keypress('o'))
	if m.sortMode != SortStatus {
		t.Errorf("after third o: got %v, want SortStatus", m.sortMode)
	}
	m = update(m, keypress('o'))
	if m.sortMode != SortName {
		t.Errorf("after fourth o: got %v, want SortName (wrap)", m.sortMode)
	}
}

func TestSort_cursorPreservedAcrossModes(t *testing.T) {
	m := readyModel(t, "alpha", "beta", "gamma")
	// Select "gamma" (last in alphabetical order)
	m = update(m, keypress('j'))
	m = update(m, keypress('j'))
	if m.services[m.servicesCursor].Name != "gamma" {
		t.Fatalf("cursor should be on gamma, got %s", m.services[m.servicesCursor].Name)
	}
	// Cycle sort — cursor should stay on gamma
	m = update(m, keypress('o'))
	if m.services[m.servicesCursor].Name != "gamma" {
		t.Errorf("after sort cycle, cursor should stay on gamma, got %s", m.services[m.servicesCursor].Name)
	}
}

func TestSort_cursorPreservedOnStatusMsg(t *testing.T) {
	m := readyModel(t, "alpha", "beta", "gamma")
	// After init+sort, order is alphabetical: alpha, beta, gamma.
	// Navigate to the last entry.
	m = update(m, keypress('j'))
	m = update(m, keypress('j'))
	selected := m.services[m.servicesCursor].Name
	if selected != "gamma" {
		t.Fatalf("cursor should be on gamma, got %s (order: %v)", selected, serviceNames(m))
	}
	// StatusMsg re-fetches and re-sorts — cursor should stay on gamma
	m = update(m, process.StatusMsg{Name: "alpha", Status: process.StatusRunning})
	if m.services[m.servicesCursor].Name != "gamma" {
		t.Errorf("after StatusMsg, cursor should stay on gamma, got %s", m.services[m.servicesCursor].Name)
	}
}

func TestSort_statusOrder(t *testing.T) {
	// All test processes start as StatusStopped since we don't call Start().
	// With equal statuses, status sort falls back to alphabetical.
	m := readyModel(t, "gamma", "alpha", "beta")
	m.sortMode = SortStatus
	m.sortServices()

	got := serviceNames(m)
	want := []string{"alpha", "beta", "gamma"}
	for i, n := range got {
		if n != want[i] {
			t.Errorf("status sort index %d: got %q, want %q (full: %v)", i, n, want[i], got)
		}
	}
}

func TestSort_statusSortOrder(t *testing.T) {
	// Verify the rank function directly
	tests := []struct {
		status process.Status
		want   int
	}{
		{process.StatusRunning, 0},
		{process.StatusPending, 1},
		{process.StatusCrashed, 2},
		{process.StatusStopped, 3},
		{process.StatusDone, 4},
	}
	for i, tt := range tests {
		got := statusSortOrder(tt.status)
		if got != tt.want {
			t.Errorf("statusSortOrder(%v): got %d, want %d (index %d)", tt.status, got, tt.want, i)
		}
	}
}

func TestSort_infoSortsAlphabetically(t *testing.T) {
	m := readyModel(t, "info", "backend", "alpha")
	got := serviceNames(m)
	want := []string{"info", "alpha", "backend"}
	for i, n := range got {
		if n != want[i] {
			t.Errorf("index %d: got %q, want %q (full: %v)", i, n, want[i], got)
		}
	}
}
