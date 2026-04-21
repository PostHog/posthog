package tui

import (
	"strings"
)

// recomputeFilter rebuilds the viewport with only lines matching searchQuery.
func (m *Model) recomputeFilter() {
	lines := m.searchableLines()
	if m.searchQuery == "" || len(lines) == 0 {
		m.viewport.SetContent(strings.Join(lines, "\n"))
		return
	}
	tokens := parseMatchTokens(m.searchQuery)
	if len(tokens) == 0 {
		m.viewport.SetContent(strings.Join(lines, "\n"))
		return
	}
	var filtered []string
	for _, line := range lines {
		if lineMatchesTokens(line, tokens) {
			filtered = append(filtered, line)
		}
	}
	if len(filtered) == 0 {
		m.viewport.SetContent("")
	} else {
		m.viewport.SetContent(strings.Join(filtered, "\n"))
	}
}
