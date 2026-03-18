package tui

import tea "charm.land/bubbletea/v2"

func (m Model) handleMouseClick(msg tea.MouseClickMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	if msg.Button == tea.MouseLeft {
		// Sidebar is from x=0 to x=sidebarWidth-1, content starts at y=headerHeight
		if msg.X < sidebarWidth && msg.Y >= headerHeight {
			m.focusedPane = focusServices
			m.dbg("focus: mouse click → sidebar")
			row := msg.Y - headerHeight - 1
			idx := m.servicesOffset + row
			if idx >= 0 && idx < len(m.services) {
				prev := m.servicesCursor
				m.servicesCursor = idx
				m.ensureSidebarCursorVisible()
				if prev != m.servicesCursor {
					m.dbg("proc selected (mouse): %d→%d (%s)", prev, m.servicesCursor, m.services[m.servicesCursor].Name)
					var loadCmds []tea.Cmd
					m, loadCmds = m.loadActiveProc()
					return m, tea.Batch(loadCmds...)
				}
			}
		} else if m.isDockerMode() && msg.X >= m.width-containerSidebarWidth && msg.Y >= headerHeight {
			// Clicked in container sidebar
			m.focusedPane = focusContainers
			m.dbg("focus: mouse click → containers")
			row := msg.Y - headerHeight - 1
			idx := m.containerOffset + row
			if idx >= 0 && idx < m.containerEntryCount() {
				prev := m.containerCursor
				m.containerCursor = idx
				m.ensureContainerCursorVisible()
				if prev != m.containerCursor {
					m.dbg("container selected (mouse): %d", m.containerCursor)
					m = m.loadContainerView()
				}
				return m, nil
			}
		} else if msg.X >= sidebarWidth {
			// Clicked in output pane
			m.focusedPane = focusOutput
			m.dbg("focus: mouse click → output")
		}
	}
	// Forward clicks outside sidebar to viewport
	var vpCmd tea.Cmd
	m.viewport, vpCmd = m.viewport.Update(msg)
	cmds = append(cmds, vpCmd)

	return m, tea.Batch(cmds...)
}
