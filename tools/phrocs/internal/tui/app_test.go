package tui

import (
	"fmt"
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
	m := New(mgr, cfg, "", nil)
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
	m := New(mgr, cfg, "", nil)
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
	m := New(mgr, cfg, "", nil)
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
	m := New(mgr, cfg, "", nil)
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

func TestSearch_tabCommitsToFilter(t *testing.T) {
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
	m = update(m, specialKey(tea.KeyTab))
	if m.searchMode {
		t.Error("search mode should be off after tab (committed)")
	}
	if !m.filterMode {
		t.Error("filter mode should be on after tab")
	}
	if m.searchQuery != "foo" {
		t.Errorf("query should be preserved after commit, got %q", m.searchQuery)
	}
	if m.viewport.TotalLineCount() != 2 {
		t.Errorf("filter should show 2 matching lines, got %d", m.viewport.TotalLineCount())
	}
}

func TestSearch_navigateWithArrows(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"match one", "nothing here", "match two"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = update(m, keypress('/'))
	for _, ch := range "match" {
		m = update(m, keypress(ch))
	}
	if len(m.searchMatches) != 2 {
		t.Fatalf("want 2 matches, got %d", len(m.searchMatches))
	}
	if m.searchCursor != 0 {
		t.Fatalf("initial cursor should be 0, got %d", m.searchCursor)
	}
	// ↓ → next match
	m = update(m, specialKey(tea.KeyDown))
	if m.searchCursor != 1 {
		t.Errorf("down: want cursor 1, got %d", m.searchCursor)
	}
	// ↑ → prev match
	m = update(m, specialKey(tea.KeyUp))
	if m.searchCursor != 0 {
		t.Errorf("up: want cursor 0, got %d", m.searchCursor)
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
	// Use a tiny scrollback (3 lines) and small window so the VT emulator
	// screen is just 1 row, causing scrollback eviction after 4 lines.
	f := false
	cfg := &config.Config{
		Procs:            map[string]config.ProcConfig{"svc": {Shell: "true", Autostart: &f}},
		MouseScrollSpeed: 3,
		Scrollback:       3,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	m = update(m, tea.WindowSizeMsg{Width: 120, Height: 5})
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
	// Build a search result, then exit via esc
	m = update(m, keypress('/'))
	m = update(m, keypress('s'))
	if m.searchQuery == "" {
		t.Fatal("search query should be set")
	}
	m = update(m, specialKey(tea.KeyEscape))
	if m.searchQuery != "" {
		t.Error("esc should clear search query")
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

// ── Filter ────────────────────────────────────────────────────────────────────

// enterFilterMode opens search via / and commits to filter via tab.
func enterFilterMode(m Model) Model {
	m = update(m, keypress('/'))
	m = update(m, specialKey(tea.KeyTab))
	return m
}

func TestFilter_enterAndExit(t *testing.T) {
	m := readyModel(t, "backend")
	m = enterFilterMode(m)
	if !m.filterMode {
		t.Error("/ then tab should enter filter mode")
	}
	m = update(m, specialKey(tea.KeyEscape))
	if m.filterMode {
		t.Error("esc should exit filter mode")
	}
	if m.searchQuery != "" {
		t.Error("esc should clear query")
	}
}

func TestFilter_typeQuery(t *testing.T) {
	m := readyModel(t, "backend")
	m = enterFilterMode(m)
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, keypress('r'))
	if m.searchQuery != "err" {
		t.Errorf("typed 'err', got %q", m.searchQuery)
	}
}

func TestFilter_backspace(t *testing.T) {
	m := readyModel(t, "backend")
	m = enterFilterMode(m)
	m = update(m, keypress('e'))
	m = update(m, keypress('r'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeyBackspace, Text: "backspace"})
	if m.searchQuery != "e" {
		t.Errorf("after backspace want %q, got %q", "e", m.searchQuery)
	}
}

func TestFilter_showsOnlyMatchingLines(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"hello world", "error here", "another error", "info log"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = enterFilterMode(m)
	for _, ch := range "error" {
		m = update(m, keypress(ch))
	}
	// Only 2 lines contain "error", so the viewport should have 2 lines
	if m.viewport.TotalLineCount() != 2 {
		t.Errorf("want 2 filtered lines, got %d", m.viewport.TotalLineCount())
	}
}

func TestFilter_noMatchShowsEmpty(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	p.AppendLine("hello world")
	m = update(m, process.OutputMsg{Name: "backend"})
	m = enterFilterMode(m)
	for _, ch := range "zzz" {
		m = update(m, keypress(ch))
	}
	if m.viewport.TotalLineCount() != 0 {
		t.Errorf("want 0 lines for no matches, got %d", m.viewport.TotalLineCount())
	}
}

func TestFilter_emptyQueryShowsAllLines(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"line 1", "line 2", "line 3"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	before := m.viewport.TotalLineCount()
	m = enterFilterMode(m)
	// With empty filter query, all lines should be visible
	if m.viewport.TotalLineCount() != before {
		t.Errorf("empty filter should show all lines: want %d, got %d", before, m.viewport.TotalLineCount())
	}
}

func TestFilter_isFullScreen(t *testing.T) {
	m := readyModel(t, "backend")
	m = enterFilterMode(m)
	if !m.isFullScreen() {
		t.Error("filter mode should be full screen")
	}
}

func TestFilter_liveUpdate(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	p.AppendLine("error one")
	m = update(m, process.OutputMsg{Name: "backend"})
	m = enterFilterMode(m)
	for _, ch := range "error" {
		m = update(m, keypress(ch))
	}
	if m.viewport.TotalLineCount() != 1 {
		t.Fatalf("want 1 filtered line initially, got %d", m.viewport.TotalLineCount())
	}
	// New matching line arrives
	p.AppendLine("error two")
	m = update(m, process.OutputMsg{Name: "backend"})
	if m.viewport.TotalLineCount() != 2 {
		t.Errorf("after new matching line: want 2 filtered lines, got %d", m.viewport.TotalLineCount())
	}
}

func TestFilter_exitRestoresAllLines(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"error one", "info two", "error three"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	before := m.viewport.TotalLineCount()
	// Enter filter, type query
	m = enterFilterMode(m)
	for _, ch := range "error" {
		m = update(m, keypress(ch))
	}
	if m.viewport.TotalLineCount() >= before {
		t.Fatal("filter should reduce visible lines")
	}
	// Exit filter
	m = update(m, specialKey(tea.KeyEscape))
	if m.viewport.TotalLineCount() != before {
		t.Errorf("after exit, want %d lines restored, got %d", before, m.viewport.TotalLineCount())
	}
}

func TestFilter_negativeExcludesLines(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"error: crash", "debug: verbose", "info: started", "warning: slow"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = enterFilterMode(m)
	// Type "!debug"
	m = update(m, tea.KeyPressMsg{Code: '!', Mod: tea.ModShift, Text: "!"})
	for _, ch := range "debug" {
		m = update(m, keypress(ch))
	}
	// Should show 3 lines (all except "debug: verbose")
	if m.viewport.TotalLineCount() != 3 {
		t.Errorf("want 3 lines excluding debug, got %d", m.viewport.TotalLineCount())
	}
}

func TestFilter_multipleNegatives(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"error: crash", "debug: verbose", "info: started", "warning: slow"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = enterFilterMode(m)
	// Type "!debug !warning" (two negative tokens separated by space)
	for _, ch := range "!debug" {
		if ch == '!' {
			m = update(m, tea.KeyPressMsg{Code: '!', Mod: tea.ModShift, Text: "!"})
		} else {
			m = update(m, keypress(ch))
		}
	}
	m = update(m, tea.KeyPressMsg{Code: tea.KeySpace, Text: "space"})
	for _, ch := range "!warning" {
		if ch == '!' {
			m = update(m, tea.KeyPressMsg{Code: '!', Mod: tea.ModShift, Text: "!"})
		} else {
			m = update(m, keypress(ch))
		}
	}
	// Should show 2 lines (error + info)
	if m.viewport.TotalLineCount() != 2 {
		t.Errorf("want 2 lines excluding debug+warning, got %d", m.viewport.TotalLineCount())
	}
}

func TestFilter_spaceInQuery(t *testing.T) {
	m := readyModel(t, "backend")
	m = enterFilterMode(m)
	m = update(m, keypress('h'))
	m = update(m, tea.KeyPressMsg{Code: tea.KeySpace, Text: "space"})
	m = update(m, keypress('w'))
	if m.searchQuery != "h w" {
		t.Errorf("space in filter query: want %q, got %q", "h w", m.searchQuery)
	}
}

func TestFilter_clearedOnProcSwitch(t *testing.T) {
	m := readyModel(t, "alpha", "beta")
	m = enterFilterMode(m)
	m = update(m, keypress('x'))
	if m.searchQuery != "x" {
		t.Fatal("query should be set")
	}
	// Switch to next proc
	m = update(m, specialKey(tea.KeyEscape)) // exit filter first (clears query)
	m = update(m, keypress('j'))             // move to beta
	if m.searchQuery != "" {
		t.Error("query should be cleared on proc switch")
	}
	if m.filterMode {
		t.Error("filter mode should be cleared on proc switch")
	}
}

func TestSearch_homeEndScrollsViewport(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for i := 0; i < 100; i++ {
		p.AppendLine(fmt.Sprintf("line %d", i))
	}
	m = update(m, process.OutputMsg{Name: "backend"})
	m = update(m, keypress('/'))
	m.viewport.GotoBottom()
	m = update(m, specialKey(tea.KeyHome))
	if m.viewport.YOffset() != 0 {
		t.Errorf("home in search mode: want YOffset 0, got %d", m.viewport.YOffset())
	}
	m = update(m, specialKey(tea.KeyEnd))
	if !m.viewport.AtBottom() {
		t.Error("end in search mode: viewport should be at bottom")
	}
}

func TestFilter_homeEndScrollsViewport(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for i := 0; i < 100; i++ {
		p.AppendLine(fmt.Sprintf("line %d", i))
	}
	m = update(m, process.OutputMsg{Name: "backend"})
	m = enterFilterMode(m)
	m.viewport.GotoBottom()
	m = update(m, specialKey(tea.KeyHome))
	if m.viewport.YOffset() != 0 {
		t.Errorf("home in filter mode: want YOffset 0, got %d", m.viewport.YOffset())
	}
	m = update(m, specialKey(tea.KeyEnd))
	if !m.viewport.AtBottom() {
		t.Error("end in filter mode: viewport should be at bottom")
	}
}

func TestFilter_backspaceOnEmptyGoesBackToSearch(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	p.AppendLine("hello")
	m = update(m, process.OutputMsg{Name: "backend"})
	m = enterFilterMode(m)
	if !m.filterMode || m.searchQuery != "" {
		t.Fatalf("setup: filterMode=%v query=%q", m.filterMode, m.searchQuery)
	}
	m = update(m, tea.KeyPressMsg{Code: tea.KeyBackspace, Text: "backspace"})
	if m.filterMode {
		t.Error("filter mode should be off after backspace on empty query")
	}
	if !m.searchMode {
		t.Error("search mode should be on after backspace on empty query")
	}
}

func TestFilter_tabGoesBackToSearch(t *testing.T) {
	m := readyModel(t, "backend")
	p, _ := m.mgr.Get("backend")
	for _, line := range []string{"error here", "info ok", "another error"} {
		p.AppendLine(line)
		m = update(m, process.OutputMsg{Name: "backend"})
	}
	m = enterFilterMode(m)
	for _, ch := range "error" {
		m = update(m, keypress(ch))
	}
	// Tab → back to search mode
	m = update(m, specialKey(tea.KeyTab))
	if m.filterMode {
		t.Error("filter mode should be off after toggle")
	}
	if !m.searchMode {
		t.Error("search mode should be on after toggle")
	}
	if m.searchQuery != "error" {
		t.Errorf("query should carry over, got %q", m.searchQuery)
	}
	if len(m.searchMatches) != 2 {
		t.Errorf("want 2 search matches, got %d", len(m.searchMatches))
	}
}

func TestNormal_fDoesNotEnterFilterMode(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('f'))
	if m.filterMode {
		t.Error("f in normal mode should not enter filter mode")
	}
	if m.searchMode {
		t.Error("f in normal mode should not enter search mode")
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
	// AppendLine writes to the VT emulator; OutputMsg triggers a full reload.
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

// ── Setup mode ──────────────────────────────────────────────────────────────

func setupModel(t *testing.T) Model {
	t.Helper()
	m := readyModel(t, "backend", "frontend")
	m.setupMode = true
	m.setupStep = 1
	m.setupEntries = []config.Intent{
		{Name: "web", Description: "Web app"},
		{Name: "analytics", Description: "Analytics pipeline"},
		{Name: "api", Description: "API server"},
	}
	m.setupCursor = 0
	m.setupOffset = 0
	m.setupChecked = map[string]bool{"web": true}
	m.setupError = ""
	return m
}

func TestSetup_navigation(t *testing.T) {
	m := setupModel(t)
	m = update(m, keypress('j'))
	if m.setupCursor != 1 {
		t.Errorf("j: cursor want 1, got %d", m.setupCursor)
	}
	m = update(m, keypress('j'))
	if m.setupCursor != 2 {
		t.Errorf("j j: cursor want 2, got %d", m.setupCursor)
	}
	m = update(m, keypress('j'))
	if m.setupCursor != 2 {
		t.Errorf("j at bottom: cursor should clamp at 2, got %d", m.setupCursor)
	}
	m = update(m, keypress('k'))
	if m.setupCursor != 1 {
		t.Errorf("k: cursor want 1, got %d", m.setupCursor)
	}
}

func TestSetup_arrowKeys(t *testing.T) {
	m := setupModel(t)
	m = update(m, specialKey(tea.KeyDown))
	if m.setupCursor != 1 {
		t.Errorf("down: cursor want 1, got %d", m.setupCursor)
	}
	m = update(m, specialKey(tea.KeyUp))
	if m.setupCursor != 0 {
		t.Errorf("up: cursor want 0, got %d", m.setupCursor)
	}
}

func TestSetup_clampsAtTop(t *testing.T) {
	m := setupModel(t)
	m = update(m, keypress('k'))
	if m.setupCursor != 0 {
		t.Errorf("k at top: cursor should stay 0, got %d", m.setupCursor)
	}
}

func TestSetup_toggle(t *testing.T) {
	m := setupModel(t)
	if !m.setupChecked["web"] {
		t.Fatal("web should be checked initially")
	}
	// Toggle web off
	m = update(m, specialKey(tea.KeySpace))
	if m.setupChecked["web"] {
		t.Error("space should uncheck web")
	}
	// Toggle web back on
	m = update(m, specialKey(tea.KeySpace))
	if !m.setupChecked["web"] {
		t.Error("second space should check web")
	}
}

func TestSetup_toggleDifferentEntry(t *testing.T) {
	m := setupModel(t)
	m = update(m, keypress('j')) // move to analytics
	m = update(m, specialKey(tea.KeySpace))
	if !m.setupChecked["analytics"] {
		t.Error("space on analytics should check it")
	}
	if !m.setupChecked["web"] {
		t.Error("web should remain checked")
	}
}

func TestSetup_escExitsFromStep1(t *testing.T) {
	m := setupModel(t)
	m = update(m, specialKey(tea.KeyEscape))
	if m.setupMode {
		t.Error("esc from step 1 should exit setup mode")
	}
	if m.focusedPane != focusServices {
		t.Error("exiting setup should focus sidebar")
	}
}

func TestSetup_escExitsFromStep2(t *testing.T) {
	m := setupModel(t)
	m.setupStep = 2
	m.setupEntries = []config.Intent{{Name: "proc1"}, {Name: "proc2"}}
	m.setupChecked = map[string]bool{"proc1": true, "proc2": true}
	m = update(m, specialKey(tea.KeyEscape))
	if m.setupMode {
		t.Error("esc from step 1 should exit setup mode")
	}
	if m.focusedPane != focusServices {
		t.Error("exiting setup should focus sidebar")
	}
}

func TestSetup_gotoTopAndBottom(t *testing.T) {
	m := setupModel(t)
	m = update(m, specialKey(tea.KeyEnd))
	if m.setupCursor != 2 {
		t.Errorf("end: cursor want 2, got %d", m.setupCursor)
	}
	m = update(m, specialKey(tea.KeyHome))
	if m.setupCursor != 0 {
		t.Errorf("home: cursor want 0, got %d", m.setupCursor)
	}
}

func TestSetup_isFullScreen(t *testing.T) {
	m := setupModel(t)
	if !m.isFullScreen() {
		t.Error("setup mode should be full screen")
	}
}

func TestSetup_handleListUnitsMsg(t *testing.T) {
	m := setupModel(t)
	m.handleListUnitsMsg(listUnitsMsg{
		units:    []string{"backend", "celery", "frontend"},
		intents:  []string{"web"},
		excluded: map[string]bool{"celery": true},
	})
	if m.setupStep != 2 {
		t.Errorf("step: want 2, got %d", m.setupStep)
	}
	if len(m.setupEntries) != 3 {
		t.Fatalf("entries: want 3, got %d", len(m.setupEntries))
	}
	if !m.setupChecked["backend"] {
		t.Error("backend should be checked")
	}
	if m.setupChecked["celery"] {
		t.Error("celery should be unchecked (excluded)")
	}
	if !m.setupChecked["frontend"] {
		t.Error("frontend should be checked")
	}
	if len(m.setupIntents) != 1 || m.setupIntents[0] != "web" {
		t.Errorf("intents: want [web], got %v", m.setupIntents)
	}
}

func TestSetup_handleListUnitsMsgError(t *testing.T) {
	m := setupModel(t)
	m.handleListUnitsMsg(listUnitsMsg{err: fmt.Errorf("hogli failed")})
	if m.setupError == "" {
		t.Error("error message should be set")
	}
	if m.setupStep != 1 {
		t.Error("should remain on step 1 after error")
	}
}

func TestSetup_handleDevApplyMsgError(t *testing.T) {
	m := setupModel(t)
	m.handleDevApplyMsg(devApplyMsg{err: fmt.Errorf("apply failed")})
	if m.setupError == "" {
		t.Error("error message should be set")
	}
	if !m.setupMode {
		t.Error("should remain in setup mode after error")
	}
}

// ── Hedgehog mode ───────────────────────────────────────────────────────────

func TestHedgehog_enterAndExit(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('h'))
	if !m.hedgehogMode {
		t.Error("h should enter hedgehog mode")
	}
	if m.hedgehogX != 0 {
		t.Errorf("initial X: got %d, want 0", m.hedgehogX)
	}
	if m.hedgehogDir != 1 {
		t.Errorf("initial dir: got %d, want 1 (right)", m.hedgehogDir)
	}
	m = update(m, keypress('h'))
	if m.hedgehogMode {
		t.Error("second h should exit hedgehog mode")
	}
}

func TestHedgehog_exitWithEscape(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('h'))
	if !m.hedgehogMode {
		t.Fatal("should be in hedgehog mode")
	}
	m = update(m, specialKey(tea.KeyEscape))
	if m.hedgehogMode {
		t.Error("esc should exit hedgehog mode")
	}
}

func TestHedgehog_jump(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('h'))
	if m.hedgehogY != 0 {
		t.Fatalf("initial Y: got %d, want 0", m.hedgehogY)
	}
	m = update(m, specialKey(tea.KeySpace))
	if m.hedgehogY != 1 {
		t.Errorf("Y after jump: got %d, want 1", m.hedgehogY)
	}
	if m.hedgehogVelY != 1 {
		t.Errorf("velY after jump: got %d, want 1", m.hedgehogVelY)
	}
}

func TestHedgehog_jumpOnlyFromGround(t *testing.T) {
	m := readyModel(t, "backend")
	m = update(m, keypress('h'))
	// First jump
	m = update(m, specialKey(tea.KeySpace))
	y := m.hedgehogY
	vel := m.hedgehogVelY
	// Second jump while airborne should be ignored
	m = update(m, specialKey(tea.KeySpace))
	if m.hedgehogY != y || m.hedgehogVelY != vel {
		t.Error("space while airborne should not change Y or velY")
	}
}

func TestHedgehog_advanceMoves(t *testing.T) {
	m := readyModel(t, "backend")
	m.hedgehogMode = true
	m.hedgehogDir = 1
	m.hedgehogX = 0
	m.hedgehogFrame = 0

	m.advanceHedgehog()
	if m.hedgehogX != 1 {
		t.Errorf("X after advance: got %d, want 1", m.hedgehogX)
	}
	if m.hedgehogFrame != 1 {
		t.Errorf("frame after advance: got %d, want 1", m.hedgehogFrame)
	}
}

func TestHedgehog_bounceAtEdge(t *testing.T) {
	m := readyModel(t, "backend")
	m.hedgehogMode = true
	spriteW := len(hedgehogFramesRight[0][0])
	m.hedgehogX = m.viewport.Width() - spriteW
	m.hedgehogDir = 1

	m.advanceHedgehog()
	if m.hedgehogDir != -1 {
		t.Errorf("dir after hitting right edge: got %d, want -1", m.hedgehogDir)
	}
}

func TestHedgehog_bounceAtLeftEdge(t *testing.T) {
	m := readyModel(t, "backend")
	m.hedgehogMode = true
	m.hedgehogX = 0
	m.hedgehogDir = -1

	m.advanceHedgehog()
	if m.hedgehogDir != 1 {
		t.Errorf("dir after hitting left edge: got %d, want 1", m.hedgehogDir)
	}
}

func TestHedgehog_gravity(t *testing.T) {
	m := readyModel(t, "backend")
	m.hedgehogMode = true
	m.hedgehogY = 2
	m.hedgehogVelY = 0
	m.hedgehogDir = 1

	m.advanceHedgehog()
	if m.hedgehogY != 2 {
		t.Errorf("Y with velY=0 at Y=2: got %d, want 2", m.hedgehogY)
	}
	// Y>0 and velY=0 means gravity pulls down: velY becomes -1
	if m.hedgehogVelY != -1 {
		t.Errorf("velY should decrease by 1, got %d", m.hedgehogVelY)
	}

	m.advanceHedgehog()
	// Y=2+(-1)=1, velY=-1-1=-2
	if m.hedgehogY != 1 {
		t.Errorf("Y after gravity: got %d, want 1", m.hedgehogY)
	}

	m.advanceHedgehog()
	// Y=1+(-2)=-1 → clamped to 0
	if m.hedgehogY != 0 {
		t.Errorf("Y should clamp to 0, got %d", m.hedgehogY)
	}
	if m.hedgehogVelY != 0 {
		t.Errorf("velY should reset to 0 on landing, got %d", m.hedgehogVelY)
	}
}
