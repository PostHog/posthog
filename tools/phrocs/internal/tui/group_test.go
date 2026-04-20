package tui

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// ── buildGroupedEntries ──────────────────────────────────────────────────────

func TestBuildGroupedEntries_noDimension(t *testing.T) {
	procs := []*process.Process{
		{Name: "alpha"},
		{Name: "beta"},
	}
	cfg := &config.Config{}
	entries := buildGroupedEntries(procs, "", cfg)
	if len(entries) != 2 {
		t.Fatalf("empty dim: want 2 entries, got %d", len(entries))
	}
	for i, e := range entries {
		if e.isHeader() {
			t.Errorf("entry %d should not be a header", i)
		}
		if e.proc != procs[i] {
			t.Errorf("entry %d proc mismatch", i)
		}
	}
}

func TestBuildGroupedEntries_withDimension(t *testing.T) {
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application"}}},
		{Name: "capture", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Ingestion"}}},
		{Name: "docker", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Infrastructure"}}},
	}
	cfg := &config.Config{
		GroupOrder: map[string][]string{
			"layer": {"Application", "Ingestion", "Infrastructure"},
		},
	}
	entries := buildGroupedEntries(procs, "layer", cfg)

	// Count headers and processes (spacers don't count)
	headers := 0
	processes := 0
	for _, e := range entries {
		if e.isHeader() {
			headers++
		} else if !e.spacer {
			processes++
		}
	}
	if processes != 3 {
		t.Errorf("want 3 process entries, got %d", processes)
	}
	if headers != 3 {
		t.Errorf("want 3 group headers, got %d", headers)
	}

	// Application should come before Ingestion which comes before Infrastructure
	var appIdx, ingIdx, infraIdx int
	for i, e := range entries {
		if e.isHeader() {
			switch e.groupHeader {
			case "Application":
				appIdx = i
			case "Ingestion":
				ingIdx = i
			case "Infrastructure":
				infraIdx = i
			}
		}
	}
	if appIdx >= ingIdx {
		t.Errorf("Application (%d) should come before Ingestion (%d)", appIdx, ingIdx)
	}
	if ingIdx >= infraIdx {
		t.Errorf("Ingestion (%d) should come before Infrastructure (%d)", ingIdx, infraIdx)
	}
}

func TestBuildGroupedEntries_emptyGroupsOmitted(t *testing.T) {
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application"}}},
	}
	cfg := &config.Config{
		GroupOrder: map[string][]string{
			"layer": {"Application", "Ingestion"},
		},
	}
	entries := buildGroupedEntries(procs, "layer", cfg)

	for _, e := range entries {
		if e.isHeader() && e.groupHeader == "Ingestion" {
			t.Error("Ingestion header should be omitted when no processes belong to it")
		}
	}
}

func TestBuildGroupedEntries_ungroupedFallback(t *testing.T) {
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application"}}},
		{Name: "mystery", Cfg: config.ProcConfig{}}, // no groups at all
	}
	cfg := &config.Config{
		GroupOrder: map[string][]string{
			"layer": {"Application"},
		},
	}
	entries := buildGroupedEntries(procs, "layer", cfg)

	hasUngrouped := false
	for _, e := range entries {
		if e.isHeader() && e.groupHeader == ungroupedName {
			hasUngrouped = true
		}
	}
	if !hasUngrouped {
		t.Error("process without groups should appear under Ungrouped header")
	}
}

func TestBuildGroupedEntries_pinnedGroup(t *testing.T) {
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application"}}},
		{Name: "info", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "pinned"}}},
	}
	cfg := &config.Config{}
	entries := buildGroupedEntries(procs, "layer", cfg)

	// Pinned process should be first, before any headers
	if len(entries) == 0 || entries[0].proc == nil || entries[0].proc.Name != "info" {
		t.Error("process with groups.layer=pinned should be first entry")
	}
	// Pinned should not have a header above it
	for _, e := range entries {
		if e.isHeader() && e.groupHeader == "pinned" {
			t.Error("pinned should not appear as a group header")
		}
	}
}

func TestBuildGroupedEntries_pinnedInOneDimensionGroupedInAnother(t *testing.T) {
	procs := []*process.Process{
		{Name: "info", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "pinned", "tech": "Other"}}},
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application", "tech": "Python"}}},
	}
	cfg := &config.Config{}

	// Pinned in layer
	layerEntries := buildGroupedEntries(procs, "layer", cfg)
	if len(layerEntries) == 0 || layerEntries[0].proc == nil || layerEntries[0].proc.Name != "info" {
		t.Error("info should be pinned when grouped by layer")
	}

	// Not pinned in tech — should appear under its group
	techEntries := buildGroupedEntries(procs, "tech", cfg)
	if len(techEntries) > 0 && techEntries[0].proc != nil && techEntries[0].proc.Name == "info" {
		t.Error("info should not be pinned when grouped by tech (it has tech=Other)")
	}
}

func TestBuildGroupedEntries_missingDimensionFallsToUngrouped(t *testing.T) {
	// Process has groups but not the active dimension
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"tech": "Rust"}}},
	}
	cfg := &config.Config{}
	entries := buildGroupedEntries(procs, "layer", cfg)

	hasUngrouped := false
	for _, e := range entries {
		if e.isHeader() && e.groupHeader == ungroupedName {
			hasUngrouped = true
		}
	}
	if !hasUngrouped {
		t.Error("process with groups but missing the active dimension should appear under Ungrouped")
	}
}

func TestBuildGroupedEntries_ungroupedAppearsAfterConfiguredGroups(t *testing.T) {
	procs := []*process.Process{
		{Name: "backend", Cfg: config.ProcConfig{Groups: map[string]string{"layer": "Application"}}},
		{Name: "mystery", Cfg: config.ProcConfig{}},
	}
	cfg := &config.Config{
		GroupOrder: map[string][]string{
			"layer": {"Application"},
		},
	}
	entries := buildGroupedEntries(procs, "layer", cfg)

	appIdx, ungroupedIdx := -1, -1
	for i, e := range entries {
		if e.isHeader() && e.groupHeader == "Application" {
			appIdx = i
		}
		if e.isHeader() && e.groupHeader == ungroupedName {
			ungroupedIdx = i
		}
	}
	if appIdx < 0 || ungroupedIdx < 0 {
		t.Fatalf("expected both Application and Ungrouped headers, got appIdx=%d ungroupedIdx=%d", appIdx, ungroupedIdx)
	}
	if ungroupedIdx <= appIdx {
		t.Errorf("Ungrouped (%d) should come after Application (%d)", ungroupedIdx, appIdx)
	}
}

// ── groupDimensions ──────────────────────────────────────────────────────────

func TestGroupDimensions(t *testing.T) {
	tests := []struct {
		name string
		cfg  *config.Config
		want []string
	}{
		{
			name: "no groups",
			cfg:  &config.Config{Procs: map[string]config.ProcConfig{"a": {Shell: "echo hi"}}},
			want: nil,
		},
		{
			name: "from procs",
			cfg: &config.Config{Procs: map[string]config.ProcConfig{
				"a": {Groups: map[string]string{"layer": "App", "tech": "Python"}},
				"b": {Groups: map[string]string{"layer": "Infra"}},
			}},
			want: []string{"layer", "tech"},
		},
		{
			name: "from group_order only",
			cfg:  &config.Config{GroupOrder: map[string][]string{"team": {"Platform", "Product"}}},
			want: []string{"team"},
		},
		{
			name: "extensible — multiple procs, overlapping dims",
			cfg: &config.Config{Procs: map[string]config.ProcConfig{
				"plain":   {Shell: "echo"},
				"simple":  {Shell: "echo", Groups: map[string]string{"layer": "App"}},
				"complex": {Shell: "echo", Groups: map[string]string{"tech": "Rust", "team": "Infra", "cost": "High"}},
			}},
			want: []string{"cost", "layer", "team", "tech"},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dims := groupDimensions(tc.cfg)
			if len(dims) != len(tc.want) {
				t.Fatalf("got %v, want %v", dims, tc.want)
			}
			for i := range dims {
				if dims[i] != tc.want[i] {
					t.Errorf("got %v, want %v", dims, tc.want)
					break
				}
			}
		})
	}
}

// ── TUI integration ──────────────────────────────────────────────────────────

func readyGroupModel(t *testing.T) Model {
	t.Helper()
	f := false
	procs := map[string]config.ProcConfig{
		"backend":        {Shell: "start-backend", Autostart: &f, Groups: map[string]string{"layer": "Application", "tech": "Python"}},
		"capture":        {Shell: "start-rust-service capture", Autostart: &f, Groups: map[string]string{"layer": "Ingestion", "tech": "Rust"}},
		"docker-compose": {Shell: "docker compose up", Autostart: &f, Groups: map[string]string{"layer": "Infrastructure", "tech": "Docker"}},
		"celery-worker":  {Shell: "start-celery worker", Autostart: &f, Groups: map[string]string{"layer": "Processing", "tech": "Python"}},
		"frontend":       {Shell: "start-frontend", Autostart: &f, Groups: map[string]string{"layer": "Application", "tech": "Frontend"}},
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
	return next.(Model)
}

func TestGroup_cycleWithG(t *testing.T) {
	m := readyGroupModel(t)
	if m.isGrouped() {
		t.Fatal("should start ungrouped")
	}
	m = update(m, keypress('g'))
	if m.activeGroupDim() != "layer" {
		t.Errorf("after first g: got %q, want layer", m.activeGroupDim())
	}
	m = update(m, keypress('g'))
	if m.activeGroupDim() != "tech" {
		t.Errorf("after second g: got %q, want tech", m.activeGroupDim())
	}
	m = update(m, keypress('g'))
	if m.isGrouped() {
		t.Errorf("after third g: should be ungrouped, got %q", m.activeGroupDim())
	}
}

func TestGroup_cyclesThroughAllDimensions(t *testing.T) {
	f := false
	procs := map[string]config.ProcConfig{
		"a": {Shell: "echo", Autostart: &f, Groups: map[string]string{"layer": "App", "tech": "Python", "team": "Platform", "cost": "High"}},
		"b": {Shell: "echo", Autostart: &f, Groups: map[string]string{"layer": "Infra"}},
	}
	cfg := &config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m = next.(Model)

	// Should have 4 dimensions: cost, layer, team, tech (alphabetical)
	if len(m.groupDims) != 4 {
		t.Fatalf("want 4 dimensions, got %d: %v", len(m.groupDims), m.groupDims)
	}

	// Cycle through all 4, then back to none
	expected := []string{"cost", "layer", "team", "tech", ""}
	for _, want := range expected {
		m = update(m, keypress('g'))
		got := m.activeGroupDim()
		if got != want {
			t.Errorf("after g: got %q, want %q", got, want)
		}
	}
}

func TestGroup_sidebarEntriesHaveHeaders(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer
	hasHeader := false
	for _, e := range m.sidebarEntries {
		if e.isHeader() {
			hasHeader = true
			break
		}
	}
	if !hasHeader {
		t.Error("grouped mode should have at least one header entry")
	}
}

func TestGroup_navigationDownSkipsHeadersAndSpacers(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer

	hasHeader, hasSpacer := false, false
	for _, e := range m.sidebarEntries {
		if e.isHeader() {
			hasHeader = true
		}
		if e.spacer {
			hasSpacer = true
		}
	}
	if !hasHeader {
		t.Fatal("test setup: expected at least one group header in entries")
	}
	if !hasSpacer {
		t.Fatal("test setup: expected at least one spacer in entries")
	}

	for i := 0; i < len(m.sidebarEntries); i++ {
		entry := m.sidebarEntries[m.entryCursor]
		if entry.isHeader() {
			t.Errorf("down: entryCursor %d landed on header %q", m.entryCursor, entry.groupHeader)
		}
		if entry.spacer {
			t.Errorf("down: entryCursor %d landed on spacer", m.entryCursor)
		}
		m = update(m, keypress('j'))
	}
}

func TestGroup_navigationUpSkipsHeadersAndSpacers(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer

	// Navigate to the last process
	for i := 0; i < len(m.sidebarEntries); i++ {
		m = update(m, keypress('j'))
	}

	for i := 0; i < len(m.sidebarEntries); i++ {
		entry := m.sidebarEntries[m.entryCursor]
		if entry.isHeader() {
			t.Errorf("up: entryCursor %d landed on header %q", m.entryCursor, entry.groupHeader)
		}
		if entry.spacer {
			t.Errorf("up: entryCursor %d landed on spacer", m.entryCursor)
		}
		m = update(m, keypress('k'))
	}
}

func TestGroup_navigationPreservesProcess(t *testing.T) {
	m := readyGroupModel(t)
	for i, p := range m.services {
		if p.Name == "capture" {
			m.servicesCursor = i
			break
		}
	}
	m = update(m, keypress('g')) // layer
	if p := m.activeProc(); p == nil || p.Name != "capture" {
		name := ""
		if p != nil {
			name = p.Name
		}
		t.Errorf("after grouping, active proc should be capture, got %q", name)
	}
}

func TestGroup_sortWithinGroups(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer
	m = update(m, keypress('o')) // SortCPU

	hasHeader := false
	for _, e := range m.sidebarEntries {
		if e.isHeader() {
			hasHeader = true
			break
		}
	}
	if !hasHeader {
		t.Error("sort change should preserve group headers")
	}
	if !m.isGrouped() {
		t.Error("should still be grouped after sort change")
	}
	if m.sortMode != SortCPU {
		t.Errorf("sortMode should be SortCPU, got %v", m.sortMode)
	}

	// Each process should appear under its correct group
	for i, e := range m.sidebarEntries {
		if e.isHeader() || e.proc == nil {
			continue
		}
		expectedGroup, ok := e.proc.Cfg.Groups["layer"]
		if !ok {
			expectedGroup = ungroupedName
		}
		foundHeader := ""
		for j := i - 1; j >= 0; j-- {
			if m.sidebarEntries[j].isHeader() {
				foundHeader = m.sidebarEntries[j].groupHeader
				break
			}
		}
		if foundHeader != expectedGroup {
			t.Errorf("process %q is under header %q, want %q", e.proc.Name, foundHeader, expectedGroup)
		}
	}
}

func TestGroup_cursorPreservedAcrossSortChange(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer

	for i := 0; i < len(m.sidebarEntries); i++ {
		if p := m.activeProc(); p != nil && p.Name == "frontend" {
			break
		}
		m = update(m, keypress('j'))
	}
	if p := m.activeProc(); p == nil || p.Name != "frontend" {
		t.Fatal("could not navigate to frontend")
	}

	m = update(m, keypress('o'))
	if p := m.activeProc(); p == nil || p.Name != "frontend" {
		name := ""
		if p := m.activeProc(); p != nil {
			name = p.Name
		}
		t.Errorf("after sort change, active proc should be frontend, got %q", name)
	}
}

func TestGroup_backToNoneRestoresFlat(t *testing.T) {
	m := readyGroupModel(t)
	m = update(m, keypress('g')) // layer
	m = update(m, keypress('g')) // tech
	m = update(m, keypress('g')) // none

	for _, e := range m.sidebarEntries {
		if e.isHeader() {
			t.Error("ungrouped should have no headers")
		}
	}
	if len(m.sidebarEntries) != len(m.services) {
		t.Errorf("ungrouped entries: got %d, want %d", len(m.sidebarEntries), len(m.services))
	}
}

func TestGroup_ungroupedProcessIsNavigable(t *testing.T) {
	f := false
	procs := map[string]config.ProcConfig{
		"backend": {Shell: "echo", Autostart: &f, Groups: map[string]string{"layer": "Application"}},
		"mystery": {Shell: "echo", Autostart: &f}, // no groups
	}
	cfg := &config.Config{
		Procs:            procs,
		MouseScrollSpeed: 3,
		Scrollback:       1000,
		GroupOrder: map[string][]string{
			"layer": {"Application"},
		},
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m = next.(Model)

	m = update(m, keypress('g')) // layer

	// Navigate down until we find "mystery"
	found := false
	for i := 0; i < len(m.sidebarEntries); i++ {
		if p := m.activeProc(); p != nil && p.Name == "mystery" {
			found = true
			break
		}
		m = update(m, keypress('j'))
	}
	if !found {
		t.Error("should be able to navigate to ungrouped process")
	}
}

func TestGroup_noGroupDimsDisablesGrouping(t *testing.T) {
	// Config with no groups at all
	f := false
	cfg := &config.Config{
		Procs: map[string]config.ProcConfig{
			"a": {Shell: "echo", Autostart: &f},
			"b": {Shell: "echo", Autostart: &f},
		},
		MouseScrollSpeed: 3,
		Scrollback:       1000,
	}
	mgr := process.NewManager(cfg)
	m := New(mgr, cfg, "", nil)
	next, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m = next.(Model)

	// Pressing g should do nothing
	m = update(m, keypress('g'))
	if m.isGrouped() {
		t.Error("g should not enable grouping when no dimensions exist")
	}
}
