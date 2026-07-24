package tui

import (
	"sort"
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// toggleShowAll toggles the display of all registry processes.
// When enabled, processes from bin/mprocs.yaml that are not in the current
// config appear as standby entries in the sidebar.
func (m *Model) toggleShowAll() {
	m.showAllRegProcs = !m.showAllRegProcs
	if m.showAllRegProcs {
		m.loadStandbyProcs()
	} else {
		m.restoreConfigFromDisk()
	}
	m.refetchServices()
	m.sortServices()
}

// restoreConfigFromDisk reloads Procs and GroupOrder from disk, restoring them to their
// clean state without any registry entries that were merged during show-all.
// Only these two fields are replaced — other config values (scrollback,
// mouse speed, etc.) are left untouched to preserve any runtime changes.
// Promoted processes are unaffected — they live in the manager, not the config.
func (m *Model) restoreConfigFromDisk() {
	m.standbyRegProcs = nil
	if m.configPath == "" {
		return
	}
	cfg, err := config.Load(m.configPath)
	if err != nil {
		m.dbg("show all: config reload failed: %v", err)
		return
	}
	m.cfg.Procs = cfg.Procs
	m.cfg.GroupOrder = cfg.GroupOrder
	m.groupDims = groupDimensions(m.cfg)
}

// loadStandbyProcs loads the full process registry and creates standby process
// objects for every entry not already managed.
func (m *Model) loadStandbyProcs() {
	registry, err := config.LoadRegistry()
	if err != nil {
		m.dbg("show all: registry load error: %v", err)
		return
	}
	if registry == nil {
		m.dbg("show all: registry not found")
		return
	}

	// Enrich the running config with registry entries so grouping works
	m.enrichConfigFromRegistry(registry)

	existing := make(map[string]bool)
	for _, p := range m.mgr.Procs() {
		existing[p.Name] = true
	}

	m.standbyRegProcs = nil
	for _, name := range registry.OrderedNames() {
		if existing[name] {
			continue
		}
		pcfg := registry.Procs[name]
		m.standbyRegProcs = append(m.standbyRegProcs, process.NewStandbyProcess(name, pcfg))
	}
	m.dbg("show all: loaded %d standby processes", len(m.standbyRegProcs))
}

// enrichConfigFromRegistry adds missing procs and group_order entries from the
// registry into the running config so that standby processes appear in their
// correct groups and groupDimensions discovers all available dimensions.
func (m *Model) enrichConfigFromRegistry(registry *config.Config) {
	if m.cfg.GroupOrder == nil {
		m.cfg.GroupOrder = make(map[string][]string)
	}
	for dim, order := range registry.GroupOrder {
		if _, ok := m.cfg.GroupOrder[dim]; !ok {
			m.cfg.GroupOrder[dim] = order
		}
	}
	for name, pcfg := range registry.Procs {
		if _, ok := m.cfg.Procs[name]; !ok {
			m.cfg.Procs[name] = pcfg
		}
	}
	m.groupDims = groupDimensions(m.cfg)
}

// promoteStandby converts a standby process into a real managed process.
// Returns the newly created real process and true, or nil and false if the
// active process is not standby.
func (m *Model) promoteStandby() (*process.Process, bool) {
	p := m.activeProc()
	if p == nil || !p.IsStandby() {
		return nil, false
	}

	real := m.mgr.Add(p.Name, p.Cfg, m.cfg.Scrollback, m.cfg.Shell)
	m.dbg("show all: promoted standby %s to real process", p.Name)

	m.refetchServices()
	m.sortServices()
	return real, true
}

// standbyInfoLines returns placeholder content for a standby process.
// All labelled rows align their values to a single absolute column, regardless
// of indent depth, so top-level and indented rows visually line up.
func (m *Model) standbyInfoLines(p *process.Process) []string {
	const valueCol = 16 // absolute column where key-value values begin

	bold := lipgloss.NewStyle().Bold(true)
	subtle := lipgloss.NewStyle().Foreground(colorBrightBlack)

	row := func(indent int, label, value string) string {
		w := max(valueCol-indent, 1)
		return strings.Repeat(" ", indent) + bold.Width(w).Render(label) + value
	}
	section := func(title string) string {
		return "  " + bold.Render(title)
	}

	lines := []string{
		"",
		"  " + subtle.Render("Not in your current intent config — press ") +
			bold.Render("s") +
			subtle.Render(" to start"),
	}

	// Command — on its own, with a blank line separating it from the rest
	switch {
	case p.Cfg.Shell != "":
		lines = append(lines, "", row(2, "Command", inlineShell(p.Cfg.Shell)))
	case len(p.Cfg.Cmd) > 0:
		lines = append(lines, "", row(2, "Command", strings.Join(p.Cfg.Cmd, " ")))
	}

	if p.Cfg.Capability != "" {
		lines = append(lines, "", row(2, "Capability", p.Cfg.Capability))
	}

	if len(p.Cfg.Groups) > 0 {
		dims := make([]string, 0, len(p.Cfg.Groups))
		for dim := range p.Cfg.Groups {
			dims = append(dims, dim)
		}
		sort.Strings(dims)
		lines = append(lines, "", section("Groups"))
		for _, dim := range dims {
			lines = append(lines, row(4, dim, p.Cfg.Groups[dim]))
		}
	}

	return lines
}

// inlineShell collapses bash line-continuations ("\\\n") and other newlines in
// a multi-line shell block into a single readable line, for display only.
func inlineShell(s string) string {
	s = strings.ReplaceAll(s, "\\\n", " ")
	return strings.Join(strings.Fields(s), " ")
}
