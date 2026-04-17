package tui

import (
	"fmt"
	"strings"
	"time"

	"charm.land/bubbles/v2/key"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
	sharedpalette "github.com/posthog/posthog/phrocs/internal/palette"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// Triggers warning icon and banner
const highMemoryMB = 2048

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

	var sortInfo string
	if m.sortMode != SortName {
		sortInfo = headerMetaStyle.Render(fmt.Sprintf("▼ %s", m.sortMode))
	}

	spacerW := max(m.width-lipgloss.Width(stripesStyle)-lipgloss.Width(brand)-lipgloss.Width(sortInfo)-lipgloss.Width(procInfo)-lipgloss.Width(meta)-1, 0)
	spacer := lipgloss.NewStyle().Width(spacerW).Render("")
	return lipgloss.JoinHorizontal(lipgloss.Top, stripesStyle, brand, spacer, sortInfo, procInfo, "•", meta)
}

func (m Model) renderSidebar() string {
	h := m.sidebarHeight()

	// Usable column width inside the border
	innerW := m.effectiveSidebarWidth() - 1

	// Determine the vertical slice of the services list to render based
	// on the current cursor position and servicesOffset
	start := min(max(m.servicesOffset, 0), max(0, len(m.services)-1))
	canScrollUp, canScrollDown, visibleH := m.sidebarScrollState()
	visibleEnd := min(len(m.services), start+visibleH)

	var rows []string

	if canScrollUp {
		rows = append(rows, scrollArrowStyle.Width(innerW).Render("▲"))
	}

	for i := start; i < visibleEnd; i++ {
		p := m.services[i]
		status := p.Status()
		iconChar := statusIconChar(status)
		// For pending processes, swap in the current spinner frame. Strip ANSI
		// from spinner.View() so the raw character can be safely composed inside
		// the surrounding lipgloss styles without breaking their background colour.
		if status == process.StatusPending {
			iconChar = ansi.Strip(m.spinner.View())
		}
		iconColor := statusIconColor(status)

		name := truncate(p.Name, innerW-3)
		rows = append(rows, renderSidebarRow(sidebarRow{
			icon:      iconChar,
			name:      name,
			iconColor: iconColor,
			selected:  i == m.servicesCursor,
			unread:    p.Unread(),
			innerW:    innerW,
			isDark:    m.isDark,
		}))
	}

	if canScrollDown {
		rows = append(rows, scrollArrowStyle.Width(innerW).Render("▼"))
	}

	// Pad remaining rows so the sidebar border extends the full height
	for len(rows) < h {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}

	return borderFor(m.isDark, m.focusedPane == focusServices).Height(h).Render(strings.Join(rows, "\n"))
}

func (m Model) sidebarHeight() int {
	fh := m.footerHeight()
	h := m.height - headerHeight - fh
	return max(h, 1)
}

// sidebarScrollState computes whether scroll arrows are needed and how many
// process rows fit. Arrows are derived from offset and list length only,
// avoiding the circular dependency where arrow visibility depends on visible
// count which depends on arrow visibility.
func (m Model) sidebarScrollState() (canScrollUp, canScrollDown bool, visibleH int) {
	h := m.sidebarHeight()
	n := len(m.services)
	if n <= h {
		return false, false, h
	}

	start := min(max(m.servicesOffset, 0), max(0, n-1))
	canScrollUp = start > 0
	// Tentatively deduct one row for the up arrow
	avail := h
	if canScrollUp {
		avail--
	}
	// Check whether the remaining rows can show everything from start onward
	canScrollDown = start+avail < n
	if canScrollDown {
		avail--
	}
	return canScrollUp, canScrollDown, max(avail, 1)
}

// Keep selected process row within the visible
// sidebar window by adjusting servicesOffset
func (m *Model) ensureSidebarCursorVisible() {
	_, _, h := m.sidebarScrollState()
	if len(m.services) <= m.sidebarHeight() {
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
	content := lipgloss.JoinHorizontal(lipgloss.Top, m.viewportWithIndicator())
	if m.isFullScreen() {
		return content
	}
	return borderFor(m.isDark, m.focusedPane == focusOutput).Render(content)
}

// Overlays a -line counter in the top-right corner of the viewport
// and appends the typed input buffer after the last output line.
func (m Model) viewportWithIndicator() string {
	view := m.viewport.View()
	if m.hedgehogMode {
		view = m.overlayHedgehog(view)
	}
	if m.infoMode {
		return view
	}

	lines := strings.Split(view, "\n")

	// Show a cursor after the last line when the process is waiting for input.
	if p := m.activeProc(); p != nil {
		showCursor := m.focusedPane == focusOutput && p.HasPrompt()
		if showCursor {
			lastLine := len(lines) - 1
			lines[lastLine] = strings.TrimRight(lines[lastLine], " ") + " " + m.inputBuffer + "▌"
		}
	}

	total := m.viewport.TotalLineCount()
	scrollLines := total - m.viewport.YOffset() - m.viewport.Height()
	if scrollLines > 0 && len(lines) > 0 {
		indicator := scrollIndicatorStyle.Render(fmt.Sprintf("-%d", scrollLines))
		indicatorW := lipgloss.Width(indicator)
		firstLine := lines[0]
		firstLineW := lipgloss.Width(firstLine)
		if firstLineW >= indicatorW {
			lines[0] = ansi.Truncate(firstLine, firstLineW-indicatorW, "") + indicator
		}
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
	} else if m.filterMode {
		matchInfo := ""
		if m.searchQuery != "" {
			if count := m.viewport.TotalLineCount(); count == 0 {
				matchInfo = "  [no matches]"
			} else {
				matchInfo = fmt.Sprintf("  [%d lines]", count)
			}
		}
		prompt := lipgloss.NewStyle().Foreground(colorGreen).Render(fmt.Sprintf("| %s▌%s", m.searchQuery, matchInfo))
		return footerStyle.Width(m.width - 2).Render(m.joinPromptWithHelp(prompt, m.keys.FilterModeHelp()))
	} else if m.searchMode {
		matchInfo := ""
		if m.searchQuery != "" {
			if len(m.searchMatches) == 0 {
				matchInfo = "  [no matches]"
			} else {
				matchInfo = fmt.Sprintf("  [%d/%d]", m.searchCursor+1, len(m.searchMatches))
			}
		}
		prompt := lipgloss.NewStyle().Foreground(colorYellow).Render(fmt.Sprintf("/ %s▌%s", m.searchQuery, matchInfo))
		return footerStyle.Width(m.width - 2).Render(m.joinPromptWithHelp(prompt, m.keys.SearchModeHelp()))
	} else if m.setupMode {
		var hint string
		if m.setupError != "" {
			escAction := "cancel"
			if m.setupStep == 2 {
				escAction = "back"
			}
			hint = "-- SETUP --  " + m.setupError + "  esc: " + escAction
		} else if m.setupStep == 1 {
			hint = "-- SETUP --  ↑/↓: navigate  space: toggle  enter: next  esc: cancel"
		} else {
			hint = "-- SETUP --  ↑/↓: navigate  space: toggle  enter: save & apply  esc: back"
		}
		return footerStyle.Width(m.width - 2).Render(
			lipgloss.NewStyle().Foreground(colorGreen).Render(hint),
		)
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
	if m.hideHelp {
		return ""
	}
	var content string
	if m.showHelp {
		content = m.help.FullHelpView(m.keys.FullHelp())
	} else {
		content = m.help.ShortHelpView(m.keys.ShortHelp())
	}
	return footerStyle.Width(m.width - 2).Render(content)
}

// Joins a prompt line with a help bar, or returns the prompt alone when help
// is hidden — keeps search/filter footer height consistent with footerHeight().
func (m Model) joinPromptWithHelp(prompt string, helpBindings []key.Binding) string {
	if m.hideHelp {
		return prompt
	}
	return lipgloss.JoinVertical(lipgloss.Left, prompt, m.help.ShortHelpView(helpBindings))
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
	labelStyle := lipgloss.NewStyle().Foreground(colorBrightBlack).Width(20)
	valueStyle := lipgloss.NewStyle()

	row := func(label, value string) string {
		return labelStyle.Render(label) + valueStyle.Render(value)
	}

	var lines []string

	// High memory warning banner
	if snap.MemRSSMB != nil && *snap.MemRSSMB >= highMemoryMB {
		lines = append(lines, warnStyle.Width(m.viewport.Width()).Render(fmt.Sprintf("  %s High memory usage: %.0f MB", sharedpalette.IconWarning, *snap.MemRSSMB)))
	}

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
	if len(p.Cfg.Cmd) > 0 {
		lines = append(lines, row("  Command", strings.Join(p.Cfg.Cmd, " ")))
	} else {
		lines = append(lines, row("  Command", p.Cfg.Shell))
	}
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
