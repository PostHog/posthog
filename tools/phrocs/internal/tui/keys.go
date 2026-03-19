package tui

import (
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
)

// Resets all search state and clears viewport highlighting.
func (m *Model) clearSearch() {
	m.searchQuery = ""
	m.searchMatches = nil
	m.searchCursor = 0
	m.viewport.StyleLineFunc = nil
}

// Forwards a message to the viewport and tracks scroll position.
func (m *Model) forwardToViewport(msg tea.Msg) tea.Cmd {
	var cmd tea.Cmd
	m.viewport, cmd = m.viewport.Update(msg)
	m.viewportAtBottom = m.viewport.AtBottom()
	return cmd
}

// Cycles the focused pane forward (+1) or backward (-1).
func (m *Model) cyclePane(dir int) {
	panes := []focusPane{focusServices, focusOutput}
	if m.isDockerMode() {
		panes = append(panes, focusContainers)
	}
	for i, p := range panes {
		if p == m.focusedPane {
			m.focusedPane = panes[(i+dir+len(panes))%len(panes)]
			m.dbg("focus: → %d", m.focusedPane)
			return
		}
	}
}

func (m Model) handleSearchKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {
	case key.Matches(msg, m.keys.Quit), msg.Code == tea.KeyEscape:
		m.searchMode = false
		m.clearSearch()
		m = m.applySize()
	case key.Matches(msg, m.keys.SearchNext):
		if len(m.searchMatches) > 0 {
			m.searchCursor = (m.searchCursor + 1) % len(m.searchMatches)
			m.applySearchStyle()
			m.jumpToCurrentMatch()
		}
	case key.Matches(msg, m.keys.SearchPrev):
		if len(m.searchMatches) > 0 {
			m.searchCursor = (m.searchCursor - 1 + len(m.searchMatches)) % len(m.searchMatches)
			m.applySearchStyle()
			m.jumpToCurrentMatch()
		}
	case key.Matches(msg, m.keys.Backspace):
		if len(m.searchQuery) > 0 {
			runes := []rune(m.searchQuery)
			m.searchQuery = string(runes[:len(runes)-1])
			m.recomputeSearch()
		}
	default:
		// Search consumes all printable characters for the query
		s := msg.String()
		var ch string
		if s == "space" {
			ch = " "
		} else if runes := []rune(s); len(runes) == 1 && runes[0] >= 32 {
			ch = s
		}
		if ch != "" {
			m.searchQuery += ch
			m.recomputeSearch()
		}
	}
	return m, cmds, true
}

func (m Model) handleCopyKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {
	case key.Matches(msg, m.keys.Quit), msg.Code == tea.KeyEscape:
		m.dbg("copy mode: exit")
		m.copyMode = false
		m.applyCopyStyle()
		m = m.applySize()

	case key.Matches(msg, m.keys.CopyMode):
		if m.copyAnchor < 0 {
			m.copyAnchor = m.copyCursor
			m.dbg("copy mode: anchor set at line %d", m.copyAnchor)
		} else if m.copyCursor != m.copyAnchor {
			text := m.copySelectedText()
			m.dbg("copy mode: copied %d lines", strings.Count(text, "\n")+1)
			m.copyMode = false
			m.applyCopyStyle()
			m = m.applySize()
			cmds = append(cmds, tea.SetClipboard(text))
		} else {
			m.copyAnchor = -1
			m.dbg("copy mode: anchor cleared")
		}
		m.applyCopyStyle()

	case key.Matches(msg, m.keys.NextProc):
		if m.copyCursor < m.viewport.TotalLineCount()-1 {
			m.copyCursor++
			m.ensureCopyCursorVisible()
			m.applyCopyStyle()
		}

	case key.Matches(msg, m.keys.PrevProc):
		if m.copyCursor > 0 {
			m.copyCursor--
			m.ensureCopyCursorVisible()
			m.applyCopyStyle()
		}

	case key.Matches(msg, m.keys.GotoTop):
		m.copyCursor = 0
		m.ensureCopyCursorVisible()
		m.applyCopyStyle()

	case key.Matches(msg, m.keys.GotoBottom):
		if total := m.viewport.TotalLineCount(); total > 0 {
			m.copyCursor = total - 1
		}
		m.ensureCopyCursorVisible()
		m.applyCopyStyle()

	default:
		return m, cmds, false
	}
	return m, cmds, true
}

func (m Model) handleInfoKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {

	case key.Matches(msg, m.keys.Info), msg.Code == tea.KeyEscape:
		m.infoMode = false
		if !m.isDockerMode() {
			m.viewport.SetContent(m.buildContent())
			m.viewport.GotoBottom()
			m.viewportAtBottom = true
		}
		m.dbg("info mode: exit")

	default:
		return m, cmds, false
	}
	return m, cmds, true
}

func (m Model) handleHedgehogKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {
	case key.Matches(msg, m.keys.Hedgehog), msg.Code == tea.KeyEscape:
		m.hedgehogMode = false
		m.dbg("hedgehog mode: exit")

	case msg.Code == tea.KeySpace:
		// Jump only when on the ground
		if m.hedgehogY == 0 {
			m.hedgehogVelY = 1
			m.hedgehogY = 1
			m.dbg("hedgehog: jump!")
		}

	default:
		return m, cmds, false
	}
	return m, cmds, true
}

func (m Model) handleNormalKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	switch {
	case key.Matches(msg, m.keys.Quit):
		m.mgr.StopAll()
		return m, tea.Quit

	case key.Matches(msg, m.keys.Help):
		m.showHelp = !m.showHelp
		m.dbg("help toggled: showHelp=%v", m.showHelp)
		m = m.applySize()

	case key.Matches(msg, m.keys.NextPane):
		m.cyclePane(+1)

	case key.Matches(msg, m.keys.PrevPane):
		m.cyclePane(-1)

	case key.Matches(msg, m.keys.NextProc):
		if m.focusedPane == focusServices {
			if m.servicesCursor < len(m.services)-1 {
				prev := m.servicesCursor
				m.servicesCursor++
				m.ensureSidebarCursorVisible()
				m.dbg("proc selected: %d→%d (%s)", prev, m.servicesCursor, m.services[m.servicesCursor].Name)
				var loadCmds []tea.Cmd
				m, loadCmds = m.loadActiveProc()
				cmds = append(cmds, loadCmds...)
			}
		} else if m.focusedPane == focusContainers && m.isDockerMode() {
			if m.containerCursor < m.containerEntryCount()-1 {
				m.containerCursor++
				m.ensureContainerCursorVisible()
				m.dbg("container selected: %d", m.containerCursor)
				m = m.loadContainerView()
			}
		} else {
			cmds = append(cmds, m.forwardToViewport(msg))
		}

	case key.Matches(msg, m.keys.PrevProc):
		if m.focusedPane == focusServices {
			if m.servicesCursor > 0 {
				prev := m.servicesCursor
				m.servicesCursor--
				m.ensureSidebarCursorVisible()
				m.dbg("proc selected: %d→%d (%s)", prev, m.servicesCursor, m.services[m.servicesCursor].Name)
				var loadCmds []tea.Cmd
				m, loadCmds = m.loadActiveProc()
				cmds = append(cmds, loadCmds...)
			}
		} else if m.focusedPane == focusContainers && m.isDockerMode() {
			if m.containerCursor > 0 {
				m.containerCursor--
				m.ensureContainerCursorVisible()
				m.dbg("container selected: %d", m.containerCursor)
				m = m.loadContainerView()
			}
		} else {
			cmds = append(cmds, m.forwardToViewport(msg))
		}

	case key.Matches(msg, m.keys.GotoTop):
		m.dbg("viewport: goto top")
		m.viewport.GotoTop()
		m.viewportAtBottom = false

	case key.Matches(msg, m.keys.GotoBottom):
		m.dbg("viewport: goto bottom")
		m.viewport.GotoBottom()
		m.viewportAtBottom = true

	case key.Matches(msg, m.keys.Restart):
		if p := m.activeProc(); p != nil {
			m.dbg("restart: proc=%s", p.Name)
			send := m.mgr.Send()
			go p.Restart(send)
		}

	case key.Matches(msg, m.keys.Stop):
		if p := m.activeProc(); p != nil {
			m.dbg("stop: proc=%s", p.Name)
			p.Stop()
		}

	case key.Matches(msg, m.keys.Search):
		m.searchMode = true
		m.clearSearch()
		m = m.applySize()

	case key.Matches(msg, m.keys.CopyMode):
		m.copyMode = true
		m = m.applySize()
		m.copyCursor = m.viewport.YOffset()
		m.copyAnchor = -1
		m.applyCopyStyle()
		m.dbg("copy mode: enter at line %d", m.copyCursor)

	case key.Matches(msg, m.keys.Info):
		m.infoMode = true
		m.refreshInfoContent()
		m.viewport.GotoTop()
		m.dbg("info mode: enter")

	case key.Matches(msg, m.keys.Hedgehog):
		m.hedgehogMode = !m.hedgehogMode
		m.dbg("hedgehog mode: %v", m.hedgehogMode)
		if m.hedgehogMode {
			m.hedgehogX = 0
			m.hedgehogDir = 1
			m.hedgehogFrame = 0
			cmds = append(cmds, hedgehogTick())
		}

	default:
		if m.focusedPane == focusOutput {
			cmds = append(cmds, m.forwardToViewport(msg))
		}
	}

	return m, tea.Batch(cmds...)
}
