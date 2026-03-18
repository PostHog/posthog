package tui

import (
	"strings"

	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/docker"
)

// Returns true when the active process is a docker-compose process
func (m Model) isDockerMode() bool {
	p := m.activeProc()
	return p != nil && docker.IsDockerComposeShell(p.Cfg.Shell)
}

// Returns the service name of the selected container, or "" for status view
func (m Model) selectedContainerService() string {
	if m.containerCursor <= 0 || m.containerCursor > len(m.containers) {
		return ""
	}
	return m.containers[m.containerCursor-1].Service
}

// Returns the total number of entries in the container sidebar (1 status + N containers)
func (m Model) containerEntryCount() int {
	return 1 + len(m.containers)
}

func (m *Model) ensureContainerCursorVisible() {
	h := m.sidebarHeight()
	total := m.containerEntryCount()
	if total <= h {
		m.containerOffset = 0
		return
	}

	maxOffset := total - h
	if m.containerOffset > maxOffset {
		m.containerOffset = maxOffset
	}
	if m.containerOffset < 0 {
		m.containerOffset = 0
	}

	if m.containerCursor < m.containerOffset {
		m.containerOffset = m.containerCursor
	}
	if m.containerCursor >= m.containerOffset+h {
		m.containerOffset = m.containerCursor - h + 1
	}
}

// Updates the viewport when the container selection changes
func (m Model) loadContainerView() Model {
	if m.containerLogStream != nil {
		m.containerLogStream.Stop()
		m.containerLogStream = nil
	}
	m.containerLines = nil

	svc := m.selectedContainerService()
	if svc == "" {
		// Status view
		m.viewport.SetContent(docker.RenderContainerStatusTable(m.containers, m.viewport.Width()))
		m.viewport.GotoTop()
		m.viewportAtBottom = false
	} else {
		// Start streaming logs for the selected container
		m.containerLogStream = docker.StartContainerLogStream(m.composeFile, svc, m.mgr.Send())
		m.viewport.SetContent("")
		m.viewportAtBottom = true
	}
	if m.searchQuery != "" {
		m.recomputeSearch()
	}
	return m
}

func (m Model) renderContainerSidebar() string {
	h := m.sidebarHeight()
	if h < 1 {
		h = 1
	}

	innerW := containerSidebarWidth - 1
	totalEntries := m.containerEntryCount()

	start := m.containerOffset
	if start < 0 {
		start = 0
	}
	if start > max(0, totalEntries-1) {
		start = max(0, totalEntries-1)
	}
	end := min(totalEntries, start+h)

	var rows []string
	for i := start; i < end; i++ {
		if i == 0 {
			// "Status" overview row
			icon := "◻"
			name := "Status"
			if m.containerCursor == 0 {
				base := lipgloss.NewStyle().Background(colorDarkGrey).Bold(true)
				iconSeg := base.PaddingLeft(1).Foreground(colorBlue).Render(icon)
				nameSeg := base.Foreground(colorWhite).Width(innerW - 2).Render(" " + name)
				rows = append(rows, iconSeg+nameSeg)
			} else {
				iconSeg := lipgloss.NewStyle().PaddingLeft(1).Foreground(colorBlue).Render(icon)
				nameSeg := lipgloss.NewStyle().Foreground(colorGrey).Width(innerW - 2).Render(" " + name)
				rows = append(rows, iconSeg+nameSeg)
			}
		} else {
			c := m.containers[i-1]
			icon := docker.ContainerStateIcon(c.State)
			iconColor := docker.ContainerStateColor(c.State)
			name := truncate(c.Service, innerW-3)

			if i == m.containerCursor {
				base := lipgloss.NewStyle().Background(colorDarkGrey).Bold(true)
				iconSeg := base.PaddingLeft(1).Foreground(iconColor).Render(icon)
				nameSeg := base.Foreground(colorWhite).Width(innerW - 2).Render(" " + name)
				rows = append(rows, iconSeg+nameSeg)
			} else {
				iconSeg := lipgloss.NewStyle().PaddingLeft(1).Foreground(iconColor).Render(icon)
				nameSeg := lipgloss.NewStyle().Foreground(colorGrey).Width(innerW - 2).Render(" " + name)
				rows = append(rows, iconSeg+nameSeg)
			}
		}
	}

	// Pad remaining rows so the sidebar border extends the full height
	for i := end - start; i < h; i++ {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}

	var style lipgloss.Style
	if m.focusedPane == focusContainers {
		style = borderFocusedStyle
	} else {
		style = borderStyle
	}
	return style.Height(h).Render(strings.Join(rows, "\n"))
}
