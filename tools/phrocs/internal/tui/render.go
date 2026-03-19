package tui

import (
	"fmt"
	"strings"
	"time"

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

			leftGap := max((innerW-labelW)/2, 0)
			rightGap := max(innerW-labelW-leftGap, 0)

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

	spacerW := max(m.width-lipgloss.Width(stripesStyle)-lipgloss.Width(brand)-lipgloss.Width(procInfo)-lipgloss.Width(meta), 0)
	spacer := lipgloss.NewStyle().Width(spacerW).Render("")
	return lipgloss.JoinHorizontal(lipgloss.Top, stripesStyle, brand, spacer, procInfo, "•", meta)
}

func (m Model) renderSidebar() string {
	h := m.sidebarHeight()

	// Usable column width inside the border
	innerW := sidebarWidth - 1

	// Determine the vertical slice of the services list to render based
	// on the current cursor position and servicesOffset
	start := min(max(m.servicesOffset, 0), max(0, len(m.services)-1))
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

		name := truncate(p.Name, innerW-3)
		rows = append(rows, renderSidebarRow(iconChar, name, iconColor, i == m.servicesCursor, innerW))
	}

	// Pad remaining rows so the sidebar border extends the full height
	for i := end - start; i < h; i++ {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}

	style := borderStyle
	if m.focusedPane == focusServices {
		style = borderFocusedStyle
	}
	return style.Height(h).Render(strings.Join(rows, "\n"))
}

func (m Model) sidebarHeight() int {
	fh := footerHeightShort
	if m.showHelp {
		fh = footerHeightFull
	}
	h := m.height - headerHeight - fh
	return max(h, 1)
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
		m.servicesOffset = max(maxOffset, 0)
	}

	if m.servicesCursor < m.servicesOffset {
		m.servicesOffset = m.servicesCursor
	}
	if m.servicesCursor >= m.servicesOffset+h {
		m.servicesOffset = m.servicesCursor - h + 1
	}
}

func (m Model) renderOutput() string {
	var style = borderStyle
	if m.focusedPane == focusOutput {
		style = borderFocusedStyle
	}
	content := lipgloss.JoinHorizontal(lipgloss.Top, m.viewportWithIndicator())
	return style.Render(content)
}

// Overlays a -line counter in the top-right corner of the viewport
func (m Model) viewportWithIndicator() string {
	view := m.viewport.View()
	if m.hedgehogMode {
		view = m.overlayHedgehog(view)
	}
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
	} else if m.infoMode {
		hint := "-- INFO --  i/esc: close"
		return footerStyle.Width(m.width - 2).Render(
			lipgloss.NewStyle().Foreground(colorYellow).Render(hint),
		)
	} else if m.searchMode {
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

// Rebuilds the info content and sets it on the viewport.
func (m *Model) refreshInfoContent() {
	info := m.renderInfo()
	lines := strings.Split(info, "\n")
	m.viewport.SetContent(strings.Join(lines, "\n"))
}

func (m Model) renderInfo() string {
	p := m.activeProc()
	if p == nil {
		return ""
	}
	snap := p.Snapshot()

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(colorYellow)
	labelStyle := lipgloss.NewStyle().Foreground(colorGrey).Width(20)
	valueStyle := lipgloss.NewStyle().Foreground(colorWhite)

	row := func(label, value string) string {
		return labelStyle.Render(label) + valueStyle.Render(value)
	}

	var lines []string
	lines = append(lines, "")

	// Status
	icon := statusIconChar(p.Status())
	iconColor := statusIconColor(p.Status())
	styledIcon := lipgloss.NewStyle().Foreground(iconColor).Render(icon)
	lines = append(lines, labelStyle.Render("  Status")+styledIcon+" "+valueStyle.Render(snap.Status))

	// PID
	if snap.PID > 0 {
		lines = append(lines, row("  PID", fmt.Sprintf("%d", snap.PID)))
	}

	// Ready
	readyStr := "no"
	if snap.Ready {
		readyStr = "yes"
	}
	lines = append(lines, row("  Ready", readyStr))

	// Exit code
	if snap.ExitCode != nil {
		lines = append(lines, row("  Exit code", fmt.Sprintf("%d", *snap.ExitCode)))
	}

	// Timing
	lines = append(lines, "")
	lines = append(lines, titleStyle.Render("  Timing"))

	if !snap.StartedAt.IsZero() {
		lines = append(lines, row("  Started", snap.StartedAt.Format(time.RFC3339)))
		lines = append(lines, row("  Uptime", formatDuration(time.Since(snap.StartedAt))))
	}
	if snap.StartupDurationS != nil {
		lines = append(lines, row("  Startup", fmt.Sprintf("%.1fs", *snap.StartupDurationS)))
	}

	// Resources (only if metrics have been sampled)
	if snap.MemRSSMB != nil {
		lines = append(lines, "")
		lines = append(lines, titleStyle.Render("  Resources"))

		lines = append(lines, row("  Memory (RSS)", fmt.Sprintf("%.1f MB", *snap.MemRSSMB)))
		if snap.PeakMemRSSMB != nil {
			lines = append(lines, row("  Peak memory", fmt.Sprintf("%.1f MB", *snap.PeakMemRSSMB)))
		}
		if snap.CPUPercent != nil {
			lines = append(lines, row("  CPU", fmt.Sprintf("%.1f%%", *snap.CPUPercent)))
		}
		if snap.CPUTimeS != nil {
			lines = append(lines, row("  CPU time", fmt.Sprintf("%.1fs", *snap.CPUTimeS)))
		}
		if snap.ThreadCount != nil {
			lines = append(lines, row("  Threads", fmt.Sprintf("%d", *snap.ThreadCount)))
		}
		if snap.ChildProcessCount != nil {
			lines = append(lines, row("  Children", fmt.Sprintf("%d", *snap.ChildProcessCount)))
		}
		if snap.FDCount != nil {
			lines = append(lines, row("  File descriptors", fmt.Sprintf("%d", *snap.FDCount)))
		}
	}

	// Config
	lines = append(lines, "")
	lines = append(lines, titleStyle.Render("  Config"))
	lines = append(lines, row("  Command", p.Cfg.Shell))
	if p.Cfg.ReadyPattern != "" {
		lines = append(lines, row("  Ready pattern", p.Cfg.ReadyPattern))
	}
	if p.Cfg.Autorestart {
		lines = append(lines, row("  Autorestart", "yes"))
	}

	// Buffered lines
	lines = append(lines, row("  Buffered lines", fmt.Sprintf("%d", len(p.Lines()))))

	return strings.Join(lines, "\n")
}

func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%.0fs", d.Seconds())
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm %ds", int(d.Minutes()), int(d.Seconds())%60)
	}
	return fmt.Sprintf("%dh %dm", int(d.Hours()), int(d.Minutes())%60)
}
