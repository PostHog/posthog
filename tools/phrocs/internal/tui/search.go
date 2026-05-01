package tui

import (
	"charm.land/lipgloss/v2"
)

// recomputeSearch fetches lines and delegates to recomputeSearchWith.
func (m *Model) recomputeSearch() {
	if m.searchQuery == "" {
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
		return
	}
	m.recomputeSearchWith(m.searchableLines())
}

// recomputeSearchWith scans the provided lines for the current query.
// Use this when lines are already available to avoid a redundant copy.
func (m *Model) recomputeSearchWith(lines []string) {
	if len(lines) == 0 {
		m.searchMatches = nil
		return
	}
	tokens := parseMatchTokens(m.searchQuery)
	m.searchMatches = nil
	for i, line := range lines {
		if lineMatchesTokens(line, tokens) {
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
	if lineMatchesQuery(line, m.searchQuery) {
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
