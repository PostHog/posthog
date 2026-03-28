package tui

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// Updates the viewport's StyleLineFunc to highlight the
// current copy selection. Must be called after any change to copyMode,
// copyAnchor, or copyCursor.
func (m *Model) applyCopyStyle() {
	if !m.copyMode {
		m.viewport.StyleLineFunc = nil
		return
	}
	cursor := m.copyCursor

	// When no anchor is set, only the cursor line is highlighted so the user
	// can navigate to the desired start position before committing.
	if m.copyAnchor < 0 {
		m.viewport.StyleLineFunc = func(idx int) lipgloss.Style {
			if idx == cursor {
				return copyModeStyle
			}
			return lipgloss.NewStyle()
		}
		return
	}

	lo := min(m.copyAnchor, cursor)
	hi := max(m.copyAnchor, cursor)
	m.viewport.StyleLineFunc = func(idx int) lipgloss.Style {
		if idx == cursor {
			return copyModeStyle
		}
		if idx >= lo && idx <= hi {
			return lipgloss.NewStyle().Background(colorDarkGrey)
		}
		return lipgloss.NewStyle()
	}
}

// Scrolls the viewport so copyCursor is visible.
func (m *Model) ensureCopyCursorVisible() {
	h := m.viewport.Height()
	if m.copyCursor < m.viewport.YOffset() {
		m.viewport.SetYOffset(m.copyCursor)
	} else if m.copyCursor >= m.viewport.YOffset()+h {
		m.viewport.SetYOffset(m.copyCursor - h + 1)
	}
}

// Returns the plain text of the selected line range, with
// ANSI escape codes stripped so the clipboard gets clean text.
func (m Model) copySelectedText() string {
	lines := m.searchableLines()
	if len(lines) == 0 {
		return ""
	}
	anchor := m.copyAnchor
	if anchor < 0 {
		anchor = m.copyCursor
	}
	lo := max(0, min(anchor, m.copyCursor))
	hi := min(len(lines)-1, max(anchor, m.copyCursor))
	var sb strings.Builder
	for i := lo; i <= hi; i++ {
		sb.WriteString(ansi.Strip(lines[i]))
		if i < hi {
			sb.WriteByte('\n')
		}
	}
	return sb.String()
}
