package tui

import (
	"fmt"
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
	"github.com/posthog/posthog/phrocs/internal/process"
)

func (m Model) renderHeader() string {
	brand := headerBrandStyle.Render("phrocs")

	running := 0
	for _, p := range m.services {
		if p.Status() == process.StatusRunning {
			running++
		}
	}
	meta := headerMetaStyle.Render(fmt.Sprintf("%d running", running))

	if m.copyMode {
		if p := m.activeProc(); p != nil {
			label := labelStyle.Render(p.Name)

			stripesW := lipgloss.Width(stripesStyle)

			labelW := lipgloss.Width(label)
			innerW := m.width - stripesW - lipgloss.Width(brand) - lipgloss.Width(meta)

			leftGap := (innerW - labelW) / 2
			if leftGap < 0 {
				leftGap = 0
			}
			rightGap := innerW - labelW - leftGap
			if rightGap < 0 {
				rightGap = 0
			}
			left := lipgloss.NewStyle().Width(leftGap).Render("")
			right := lipgloss.NewStyle().Width(rightGap).Render("")

			return lipgloss.JoinHorizontal(lipgloss.Top, stripesStyle, brand, left, label, right, meta)
		}
	}

	var procInfo string
	if p := m.activeProc(); p != nil {
		if pid := p.PID(); pid > 0 {
			procInfo = headerMetaStyle.Render(fmt.Sprintf("PID %d", pid))
		}
	}

	spacerW := m.width - lipgloss.Width(stripesStyle) - lipgloss.Width(brand) - lipgloss.Width(procInfo) - lipgloss.Width(meta)
	if spacerW < 0 {
		spacerW = 0
	}
	spacer := lipgloss.NewStyle().Width(spacerW).Render("")
	return lipgloss.JoinHorizontal(lipgloss.Top, stripesStyle, brand, spacer, procInfo, "•", meta)
}

func (m Model) renderSidebar() string {
	h := m.sidebarHeight()
	if h < 1 {
		h = 1
	}

	// Usable column width inside the border
	innerW := sidebarWidth - 1

	start := m.servicesOffset
	if start < 0 {
		start = 0
	}
	if start > max(0, len(m.services)-1) {
		start = max(0, len(m.services)-1)
	}
	end := min(len(m.services), start+h)

	var rows []string
	for i := start; i < end; i++ {
		p := m.services[i]
		iconChar := statusIconChar(p.Status())
		// For pending processes, swap in the current spinner frame. Strip ANSI
		// from spinner.View() so the raw character can be safely composed inside
		// the surrounding lipgloss styles without breaking their background colour.
		if p.Status() == process.StatusPending {
			iconChar = ansi.Strip(m.spinner.View())
		}
		iconColor := statusIconColor(p.Status())

		// Reserve 3 visible chars for left-padding (1) + icon (1) + space (1)
		name := truncate(p.Name, innerW-3)

		// Render icon and name as *separate* lipgloss segments that share the
		// same background colour. This avoids embedding pre-rendered ANSI
		// strings (which carry their own \033[m reset) inside an outer style,
		// which would silently terminate the background highlight after the icon
		// and make the active-row cursor invisible.
		if i == m.servicesCursor {
			base := lipgloss.NewStyle().Background(colorDarkGrey).Bold(true)
			iconSeg := base.PaddingLeft(1).Foreground(iconColor).Render(iconChar)
			// Width covers the remaining columns: innerW minus the 2 chars
			// already consumed by PaddingLeft + icon
			nameSeg := base.Foreground(colorWhite).Width(innerW - 2).Render(" " + name)
			rows = append(rows, iconSeg+nameSeg)
		} else {
			iconSeg := lipgloss.NewStyle().PaddingLeft(1).Foreground(iconColor).Render(iconChar)
			nameSeg := lipgloss.NewStyle().Foreground(colorGrey).Width(innerW - 2).Render(" " + name)
			rows = append(rows, iconSeg+nameSeg)
		}
	}

	// Pad remaining rows so the sidebar border extends the full height
	for i := end - start; i < h; i++ {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}

	var style lipgloss.Style
	if m.focusedPane == focusServices {
		style = borderFocusedStyle
	} else {
		style = borderStyle
	}
	return style.Height(h).Render(strings.Join(rows, "\n"))
}

func (m Model) sidebarHeight() int {
	fh := footerHeightShort
	if m.showHelp {
		fh = footerHeightFull
	}
	h := m.height - headerHeight - fh
	if h < 1 {
		return 1
	}
	return h
}

// Keep selected process row within the visible
// sidebar window by adjusting servicesOffset
func (m *Model) ensureSidebarCursorVisible() {
	h := m.sidebarHeight()
	if len(m.services) <= h {
		m.servicesOffset = 0
		return
	}

	maxOffset := len(m.services) - h
	if m.servicesOffset > maxOffset {
		m.servicesOffset = maxOffset
	}
	if m.servicesOffset < 0 {
		m.servicesOffset = 0
	}

	if m.servicesCursor < m.servicesOffset {
		m.servicesOffset = m.servicesCursor
	}
	if m.servicesCursor >= m.servicesOffset+h {
		m.servicesOffset = m.servicesCursor - h + 1
	}
}

func (m Model) renderOutput() string {
	var style lipgloss.Style
	if m.focusedPane == focusOutput {
		style = borderFocusedStyle
	} else {
		style = borderStyle
	}
	content := lipgloss.JoinHorizontal(lipgloss.Top, m.viewportWithIndicator())
	return style.Render(content)
}

// Overlays a -line counter in the top-right corner of the viewport
func (m Model) viewportWithIndicator() string {
	view := m.viewport.View()
	total := m.viewport.TotalLineCount()
	if total <= m.viewport.Height() {
		return view
	}

	scrollLines := total - m.viewport.YOffset() - m.viewport.Height()
	if scrollLines <= 0 {
		return view
	}

	indicator := scrollIndicatorStyle.Render(fmt.Sprintf("-%d", scrollLines))
	indicatorW := lipgloss.Width(indicator)

	lines := strings.Split(view, "\n")
	if len(lines) == 0 {
		return view
	}
	firstLine := lines[0]
	firstLineW := lipgloss.Width(firstLine)
	if firstLineW >= indicatorW {
		// Truncate the first line to make room for the indicator
		lines[0] = ansi.Truncate(firstLine, firstLineW-indicatorW, "") + indicator
	}
	return strings.Join(lines, "\n")
}

func (m Model) renderFooter() string {
	if m.copyMode {
		var hint string
		if m.copyAnchor < 0 {
			hint = fmt.Sprintf("-- COPY MODE --  line %d  ↑/↓: navigate  c: mark start  esc: cancel", m.copyCursor+1)
		} else {
			lo := min(m.copyAnchor, m.copyCursor) + 1
			hi := max(m.copyAnchor, m.copyCursor) + 1
			hint = fmt.Sprintf("-- COPY MODE --  lines %d–%d  ↑/↓: extend  c: copy  esc: cancel", lo, hi)
		}
		return footerStyle.Width(m.width - 2).Render(
			lipgloss.NewStyle().Foreground(colorBlue).Render(hint),
		)
	}
	if m.searchMode {
		var matchInfo string
		if m.searchQuery == "" {
			matchInfo = ""
		} else if len(m.searchMatches) == 0 {
			matchInfo = "  [no matches]"
		} else {
			matchInfo = fmt.Sprintf("  [%d/%d]", m.searchCursor+1, len(m.searchMatches))
		}
		prompt := lipgloss.NewStyle().Foreground(colorYellow).Render(fmt.Sprintf("/ %s▌%s", m.searchQuery, matchInfo))
		return footerStyle.Width(m.width - 2).Render(prompt)
	}
	if m.searchQuery != "" {
		var matchInfo string
		if len(m.searchMatches) == 0 {
			matchInfo = fmt.Sprintf("search: %q  [no matches]  esc: leave", m.searchQuery)
		} else {
			matchInfo = fmt.Sprintf("search: %q  [%d/%d]  ↵/⇧↵: navigate  esc: leave", m.searchQuery, m.searchCursor+1, len(m.searchMatches))
		}
		return footerStyle.Width(m.width - 2).Render(
			lipgloss.NewStyle().Foreground(colorYellow).Render(matchInfo),
		)
	}
	var content string
	if m.showHelp {
		content = m.help.FullHelpView(m.keys.FullHelp())
	} else {
		content = m.help.ShortHelpView(m.keys.ShortHelp())
	}
	return footerStyle.Width(m.width - 2).Render(content)
}
