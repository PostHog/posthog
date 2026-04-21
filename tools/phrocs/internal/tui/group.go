package tui

import (
	"sort"

	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/process"
)

const ungroupedName = "Ungrouped"
const pinnedKey = "pinned" // reserved group value: pinned at the top, no header

// sidebarEntry represents either a group header, a spacer, or a process in the grouped sidebar.
type sidebarEntry struct {
	// Only one of these is set.
	groupHeader string           // non-empty for header rows
	proc        *process.Process // non-nil for process rows
	spacer      bool             // empty row for visual separation

	// procIndex is the index into m.services for process entries,
	// allowing navigation to map back to the flat services slice.
	procIndex int
}

func (e sidebarEntry) isHeader() bool {
	return e.groupHeader != ""
}

func (e sidebarEntry) isNonSelectable() bool {
	return e.isHeader() || e.spacer
}

// groupDimensions discovers the available grouping dimensions from the config.
// User-declared dimensions (from `groups:` on each proc) come first, the
// inferred `capability` dimension is appended.
func groupDimensions(cfg *config.Config) []string {
	seen := make(map[string]bool)
	for _, pc := range cfg.Procs {
		for dim := range pc.Groups {
			seen[dim] = true
		}
	}
	// Also include dimensions from group_order even if no process uses them yet
	for dim := range cfg.GroupOrder {
		seen[dim] = true
	}

	hasCapability := seen[config.CapabilityGroupKey]
	delete(seen, config.CapabilityGroupKey)

	dims := make([]string, 0, len(seen)+1)
	for dim := range seen {
		dims = append(dims, dim)
	}
	sort.Strings(dims)
	if hasCapability {
		dims = append(dims, config.CapabilityGroupKey)
	}
	return dims
}

// groupOrderFor returns the display order for a given dimension.
// If group_order is configured, uses that. Otherwise discovers groups from
// processes in the order they first appear.
func groupOrderFor(dim string, cfg *config.Config, services []*process.Process) []string {
	if order, ok := cfg.GroupOrder[dim]; ok && len(order) > 0 {
		return order
	}
	// Discover from processes, preserving first-seen order
	seen := make(map[string]bool)
	var order []string
	for _, p := range services {
		if g, ok := p.Cfg.Groups[dim]; ok && !seen[g] {
			seen[g] = true
			order = append(order, g)
		}
	}
	return order
}

// buildGroupedEntries creates an ordered list of sidebar entries with group headers
// interspersed among processes.
// When dim is empty, returns a flat list with no headers.
func buildGroupedEntries(services []*process.Process, dim string, cfg *config.Config) []sidebarEntry {
	if dim == "" {
		entries := make([]sidebarEntry, len(services))
		for i, p := range services {
			entries[i] = sidebarEntry{proc: p, procIndex: i}
		}
		return entries
	}

	groupOrder := groupOrderFor(dim, cfg, services)

	// Bucket processes by group; "pinned" processes go to the top without a header
	var pinned []sidebarEntry
	groups := make(map[string][]sidebarEntry)
	for i, p := range services {
		g, ok := p.Cfg.Groups[dim]
		if !ok {
			g = ungroupedName
		}
		if g == pinnedKey {
			pinned = append(pinned, sidebarEntry{proc: p, procIndex: i})
			continue
		}
		groups[g] = append(groups[g], sidebarEntry{proc: p, procIndex: i})
	}

	// Build ordered entries: pinned first, then groups with headers.
	// A spacer row is inserted before each group header for visual separation.
	entries := append([]sidebarEntry{}, pinned...)
	firstGroup := len(pinned) == 0

	// Emit groups in configured order first
	emitted := make(map[string]bool)
	for _, g := range groupOrder {
		procs := groups[g]
		if len(procs) == 0 {
			continue
		}
		if !firstGroup {
			entries = append(entries, sidebarEntry{spacer: true})
		}
		firstGroup = false
		entries = append(entries, sidebarEntry{groupHeader: g})
		entries = append(entries, procs...)
		emitted[g] = true
	}

	// Emit any remaining groups not in the configured order (alphabetically),
	// including "Ungrouped"
	var remaining []string
	for g := range groups {
		if !emitted[g] {
			remaining = append(remaining, g)
		}
	}
	sort.Strings(remaining)
	for _, g := range remaining {
		procs := groups[g]
		if !firstGroup {
			entries = append(entries, sidebarEntry{spacer: true})
		}
		firstGroup = false
		entries = append(entries, sidebarEntry{groupHeader: g})
		entries = append(entries, procs...)
	}

	return entries
}
