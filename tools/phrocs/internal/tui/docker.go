package tui

import (
	"image/color"
	"strings"

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
		m.containerOffset = max(0, maxOffset)
	}

	if m.containerCursor < m.containerOffset {
		m.containerOffset = m.containerCursor
	} else if m.containerCursor >= m.containerOffset+h {
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
		m.containerLogStream = docker.StartContainerLogStream(m.composeArgs, svc, m.mgr.Send())
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
	innerW := containerSidebarWidth - 1
	totalEntries := m.containerEntryCount()

	start := max(0, min(m.containerOffset, max(0, totalEntries-1)))
	end := min(totalEntries, start+h)

	var rows []string
	for i := start; i < end; i++ {
		var icon, name string
		var iconColor color.Color
		if i == 0 {
			icon, name, iconColor = "🐋", "Status", colorBlue
		} else {
			c := m.containers[i-1]
			icon = docker.ContainerStateIcon(c.State)
			name = truncate(c.Service, innerW-3)
			iconColor = docker.ContainerStateColor(c.State)
		}
		rows = append(rows, renderSidebarRow(icon, name, iconColor, i == m.containerCursor, innerW))
	}

	for i := end - start; i < h; i++ {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}

	style := borderStyle
	if m.focusedPane == focusContainers {
		style = borderFocusedStyle
	}
	return style.Height(h).Render(strings.Join(rows, "\n"))
}
