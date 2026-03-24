package tui

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// Recomputes searchMatches from current process output
func (m *Model) recomputeSearch() {
	if m.searchQuery == "" {
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
		return
	}
	lines := m.searchableLines()
	if len(lines) == 0 {
		m.searchMatches = nil
		return
	}
	query := strings.ToLower(m.searchQuery)
	m.searchMatches = nil
	for i, line := range lines {
		if strings.Contains(strings.ToLower(ansi.Strip(line)), query) {
			m.searchMatches = append(m.searchMatches, i)
		}
	}
	if m.searchCursor >= len(m.searchMatches) {
		m.searchCursor = max(len(m.searchMatches)-1, 0)
	}
	m.applySearchStyle()
}

// Updates the viewport's StyleLineFunc to highlight search matches.
func (m *Model) applySearchStyle() {
	if len(m.searchMatches) == 0 {
		m.viewport.StyleLineFunc = nil
		return
	}
	matchSet := make(map[int]bool, len(m.searchMatches))
	for _, idx := range m.searchMatches {
		matchSet[idx] = true
	}
	current := m.searchMatches[m.searchCursor]
	m.viewport.StyleLineFunc = func(idx int) lipgloss.Style {
		if idx == current {
			return searchCurrentMatchStyle
		}
		if matchSet[idx] {
			return searchMatchStyle
		}
		return lipgloss.NewStyle()
	}
}

// Incrementally maintains searchMatches when a single new line arrives
// (used by docker container log streaming which still delivers individual lines).
func (m *Model) updateSearchForLine(line string, lineIndex int, evicted bool) {
	if evicted && len(m.searchMatches) > 0 {
		// The line at index 0 was dropped; remove it from matches if present.
		if m.searchMatches[0] == 0 {
			m.searchMatches = m.searchMatches[1:]
			if m.searchCursor > 0 {
				m.searchCursor--
			} else if len(m.searchMatches) == 0 {
				m.searchCursor = 0
			}
		}
		// All remaining indices shifted down by one.
		for i := range m.searchMatches {
			m.searchMatches[i]--
		}
	}
	if strings.Contains(strings.ToLower(ansi.Strip(line)), strings.ToLower(m.searchQuery)) {
		m.searchMatches = append(m.searchMatches, lineIndex)
	}
	m.applySearchStyle()
}

func (m Model) searchableLines() []string {
	if m.isDockerMode() {
		return m.containerLines
	}
	p := m.activeProc()
	if p == nil {
		return nil
	}
	return p.Lines()
}

// Scrolls the viewport so the current search match is centered.
func (m *Model) jumpToCurrentMatch() {
	if len(m.searchMatches) == 0 {
		return
	}
	lineIdx := m.searchMatches[m.searchCursor]
	h := m.viewport.Height()
	offset := max(lineIdx-h/2, 0)
	m.viewport.SetYOffset(offset)
	m.viewportAtBottom = m.viewport.AtBottom()
}
