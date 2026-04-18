package tui

import (
	"sort"
	"strings"

	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// toggleShowAll toggles the display of all registry processes.
// When enabled, processes from bin/mprocs.yaml that are not in the current
// config appear as standby entries in the sidebar.
func (m *Model) toggleShowAll() {
	m.showAll = !m.showAll
	if m.showAll {
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
	m.standbyProcs = nil
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

	m.standbyProcs = nil
	for _, name := range registry.OrderedNames() {
		if existing[name] {
			continue
		}
		pcfg := registry.Procs[name]
		m.standbyProcs = append(m.standbyProcs, process.NewStandbyProcess(name, pcfg))
	}
	m.dbg("show all: loaded %d standby processes", len(m.standbyProcs))
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
func (m *Model) standbyInfoLines(p *process.Process) []string {
	lines := []string{
		"",
		"  Not in current intent config — press 's' to start",
		"",
	}
	if p.Cfg.Shell != "" {
		lines = append(lines, "  Command: "+p.Cfg.Shell)
	} else if len(p.Cfg.Cmd) > 0 {
		lines = append(lines, "  Command: "+strings.Join(p.Cfg.Cmd, " "))
	}
	if p.Cfg.Capability != "" {
		lines = append(lines, "  Capability: "+p.Cfg.Capability)
	}
	if len(p.Cfg.Groups) > 0 {
		dims := make([]string, 0, len(p.Cfg.Groups))
		for dim := range p.Cfg.Groups {
			dims = append(dims, dim)
		}
		sort.Strings(dims)
		for _, dim := range dims {
			lines = append(lines, "  Group: "+dim+"="+p.Cfg.Groups[dim])
		}
	}
	return lines
}
