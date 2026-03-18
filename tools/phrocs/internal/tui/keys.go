package tui

import (
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
)

func (m Model) handleSearchKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	s := msg.String()
	switch {
	case key.Matches(msg, m.keys.Quit), key.Matches(msg, m.keys.CopyEsc):
		m.searchMode = false
		m.searchQuery = ""
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
		m = m.applySize()
	case s == "enter":
		m.searchMode = false
		m = m.applySize()
		// Keep matches visible
		if len(m.searchMatches) > 0 {
			m.searchCursor = 0
			m.applySearchStyle()
			m.jumpToCurrentMatch()
		}
	case s == "backspace" || s == "ctrl+h":
		if len(m.searchQuery) > 0 {
			runes := []rune(m.searchQuery)
			m.searchQuery = string(runes[:len(runes)-1])
			m.recomputeSearch()
		}
	case key.Matches(msg, m.keys.Search):
		// Ignore repeated '/' while already searching
	default:
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
	return m, tea.Batch(cmds...)
}

func (m Model) handleCopyKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	switch {
	case key.Matches(msg, m.keys.Quit), key.Matches(msg, m.keys.CopyEsc):
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
			m.dbg("copy mode: copied %d lines", len(text)-len(strings.ReplaceAll(text, "\n", ""))+1)
			m.copyMode = false
			m.applyCopyStyle()
			m = m.applySize()
			return m, tea.SetClipboard(text)
		} else {
			m.copyAnchor = -1
			m.dbg("copy mode: anchor cleared")
		}
		m.applyCopyStyle()

	case key.Matches(msg, m.keys.NextProc):
		total := m.viewport.TotalLineCount()
		if m.copyCursor < total-1 {
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
		total := m.viewport.TotalLineCount()
		if total > 0 {
			m.copyCursor = total - 1
		}
		m.ensureCopyCursorVisible()
		m.applyCopyStyle()
	}
	return m, tea.Batch(cmds...)
}

func (m Model) handleNormalKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	switch {
	case key.Matches(msg, m.keys.Quit):
		m.mgr.StopAll()
		return m, tea.Quit

	case key.Matches(msg, m.keys.Help):
		m.showHelp = !m.showHelp
		m.dbg("help toggled: showHelp=%v", m.showHelp)
		// Recompute sizes since footer height may change
		m = m.applySize()

	case key.Matches(msg, m.keys.NextPane):
		if m.isDockerMode() {
			switch m.focusedPane {
			case focusServices:
				m.focusedPane = focusOutput
				m.dbg("focus: sidebar → output")
			case focusOutput:
				m.focusedPane = focusContainers
				m.dbg("focus: output → containers")
			case focusContainers:
				m.focusedPane = focusServices
				m.dbg("focus: containers → sidebar")
			}
		} else {
			if m.focusedPane == focusServices {
				m.focusedPane = focusOutput
				m.dbg("focus: sidebar → output")
			} else {
				m.focusedPane = focusServices
				m.dbg("focus: output → sidebar")
			}
		}

	case key.Matches(msg, m.keys.PrevPane):
		if m.isDockerMode() {
			switch m.focusedPane {
			case focusServices:
				m.focusedPane = focusContainers
				m.dbg("focus: sidebar → containers")
			case focusContainers:
				m.focusedPane = focusOutput
				m.dbg("focus: containers → output")
			case focusOutput:
				m.focusedPane = focusServices
				m.dbg("focus: output → sidebar")
			}
		} else {
			if m.focusedPane == focusServices {
				m.focusedPane = focusOutput
				m.dbg("focus: sidebar → output")
			} else {
				m.focusedPane = focusServices
				m.dbg("focus: output → sidebar")
			}
		}

	case key.Matches(msg, m.keys.NextProc):
		// When services focused: navigate to next process
		// When docker sidebar focused: navigate to next container
		// When output focused: scroll down
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
			total := m.containerEntryCount()
			if m.containerCursor < total-1 {
				m.containerCursor++
				m.ensureContainerCursorVisible()
				m.dbg("container selected: %d", m.containerCursor)
				m = m.loadContainerView()
			}
		} else {
			// Forward to viewport for scrolling
			var vpCmd tea.Cmd
			m.viewport, vpCmd = m.viewport.Update(msg)
			cmds = append(cmds, vpCmd)
			m.viewportAtBottom = m.viewport.AtBottom()
		}

	case key.Matches(msg, m.keys.PrevProc):
		// When sidebar focused: navigate to previous process
		// When container sidebar focused: navigate to previous container
		// When output focused: scroll up
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
			// Forward to viewport for scrolling
			var vpCmd tea.Cmd
			m.viewport, vpCmd = m.viewport.Update(msg)
			cmds = append(cmds, vpCmd)
			m.viewportAtBottom = m.viewport.AtBottom()
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
		m.searchQuery = ""
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
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

	case key.Matches(msg, m.keys.CopyEsc):
		// Clear active search if any (esc has no other effect in normal mode)
		if m.searchQuery != "" {
			m.searchQuery = ""
			m.searchMatches = nil
			m.searchCursor = 0
			m.viewport.StyleLineFunc = nil
		}

	case key.Matches(msg, m.keys.CopyMode):
		// Enter copy mode
		m.copyMode = true
		// Expand the viewport to full width before recording the cursor
		// position so YOffset stays meaningful after the resize
		m = m.applySize()
		// Place cursor at top of visible area; anchor is unset until
		// the user presses 'c' again to mark the selection start
		m.copyCursor = m.viewport.YOffset()
		m.copyAnchor = -1
		m.applyCopyStyle()
		m.dbg("copy mode: enter at line %d", m.copyCursor)

	default:
		// Forward remaining key events to the viewport when focused
		if m.focusedPane == focusOutput {
			var vpCmd tea.Cmd
			m.viewport, vpCmd = m.viewport.Update(msg)
			cmds = append(cmds, vpCmd)
			m.viewportAtBottom = m.viewport.AtBottom()
		}
	}

	return m, tea.Batch(cmds...)
}
