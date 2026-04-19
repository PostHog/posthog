package tui

import (
	"fmt"
	"os/exec"
	"runtime"
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
)

// procViewerCmd returns an exec.Cmd for the best available process viewer,
// filtered to the given root PID where possible. Falls back to unfiltered
// viewers when PID filtering isn't supported. Returns nil if none found.
//
// Priority: htop (PID-filtered) > btop (unfiltered) > top (PID-filtered).
func procViewerCmd(pid int) *exec.Cmd {
	pidStr := fmt.Sprintf("%d", pid)

	// htop: tree view + PID filter on all platforms
	if path, err := exec.LookPath("htop"); err == nil {
		return exec.Command(path, "-t", "-p", pidStr)
	}

	// btop: no PID filter support
	if path, err := exec.LookPath("btop"); err == nil {
		return exec.Command(path)
	}

	// top: PID-filtered, syntax differs by OS
	if path, err := exec.LookPath("top"); err == nil {
		if runtime.GOOS == "darwin" {
			return exec.Command(path, "-pid", pidStr)
		}
		// Linux top uses -p
		return exec.Command(path, "-p", pidStr)
	}

	return nil
}

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

// Handles viewport navigation keys (home/end/pgup/pgdn). Returns true if the
// key was consumed.
func (m *Model) handleViewportNavKey(msg tea.KeyPressMsg, cmds *[]tea.Cmd) bool {
	switch {
	case key.Matches(msg, m.keys.GotoTop):
		m.dbg("viewport: home → goto top")
		m.viewport.GotoTop()
		m.viewportAtBottom = false
	case key.Matches(msg, m.keys.GotoBottom):
		m.dbg("viewport: end → goto bottom")
		m.viewport.GotoBottom()
		m.viewportAtBottom = true
	case key.Matches(msg, m.keys.ScrollUp), key.Matches(msg, m.keys.ScrollDown):
		*cmds = append(*cmds, m.forwardToViewport(msg))
	default:
		return false
	}
	return true
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
	case msg.Code == tea.KeyEscape:
		m.searchMode = false
		m.clearSearch()
		m = m.applySize()
	case key.Matches(msg, m.keys.CommitFilter):
		// Preserve query; drop search-only match state before switching to filter
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
		m.searchMode = false
		m.filterMode = true
		m.recomputeFilter()
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
		if m.handleViewportNavKey(msg, &cmds) {
			break
		}
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

func (m Model) handleFilterKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {
	case msg.Code == tea.KeyEscape:
		m.filterMode = false
		m.searchQuery = ""
		m.reloadActiveLines()
		m = m.applySize()
		if m.viewportAtBottom {
			m.viewport.GotoBottom()
		}
	case key.Matches(msg, m.keys.ToggleFilter):
		// Preserve query; restore unfiltered viewport and rebuild search match state
		m.filterMode = false
		m.reloadActiveLines()
		m.searchMode = true
		m.recomputeSearch()
		m.jumpToCurrentMatch()
		m = m.applySize()
	case key.Matches(msg, m.keys.Backspace):
		if len(m.searchQuery) > 0 {
			runes := []rune(m.searchQuery)
			m.searchQuery = string(runes[:len(runes)-1])
			m.recomputeFilter()
		} else {
			// Backspace on empty query exits filter back to search
			m.filterMode = false
			m.reloadActiveLines()
			m.searchMode = true
			m.recomputeSearch()
			m.jumpToCurrentMatch()
			m = m.applySize()
		}
	default:
		if m.handleViewportNavKey(msg, &cmds) {
			break
		}
		s := msg.String()
		var ch string
		if s == "space" {
			ch = " "
		} else if runes := []rune(s); len(runes) == 1 && runes[0] >= 32 {
			ch = s
		}
		if ch != "" {
			m.searchQuery += ch
			m.recomputeFilter()
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

	case key.Matches(msg, m.keys.NextProc), key.Matches(msg, m.keys.KeyDown):
		if m.copyCursor < m.viewport.TotalLineCount()-1 {
			m.copyCursor++
			m.ensureCopyCursorVisible()
			m.applyCopyStyle()
		}

	case key.Matches(msg, m.keys.PrevProc), key.Matches(msg, m.keys.KeyUp):
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

	case key.Matches(msg, m.keys.InfoMode), msg.Code == tea.KeyEscape:
		m.infoMode = false
		m.disableAllMetrics()
		if !m.isDockerMode() {
			m.reloadActiveLines()
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


// updateProcKeys enables/disables start, stop, and restart bindings
// based on the active process state.
func (m *Model) updateProcKeys() {
	p := m.activeProc()
	if p == nil {
		m.keys.Start.SetEnabled(false)
		m.keys.Stop.SetEnabled(false)
		m.keys.Restart.SetEnabled(false)
		m.keys.ClearLogs.SetEnabled(false)
		return
	}
	running := p.IsRunning()
	m.keys.Start.SetEnabled(!running)
	m.keys.Stop.SetEnabled(running)
	m.keys.Restart.SetEnabled(running)
	m.keys.ClearLogs.SetEnabled(running)
}

func (m Model) handleNormalKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	// When the active process is waiting for input, buffer keystrokes and send them on Enter.
	p := m.activeProc()
	procHasPrompt := p != nil && m.focusedPane == focusOutput && p.HasPrompt()
	// Control keys are excluded so navigation still works.
	isControlKey := key.Matches(msg, m.keys.NextPane) ||
		key.Matches(msg, m.keys.PrevPane) ||
		key.Matches(msg, m.keys.GotoTop) ||
		key.Matches(msg, m.keys.GotoBottom) ||
		key.Matches(msg, m.keys.ScrollDown) ||
		key.Matches(msg, m.keys.ScrollUp)

	if procHasPrompt && !isControlKey {
		var input []byte

		switch msg.Code {
		case tea.KeyEnter:
			input = []byte(m.inputBuffer + "\r")
			m.inputBuffer = ""
		case tea.KeyBackspace:
			if len(m.inputBuffer) > 0 {
				runes := []rune(m.inputBuffer)
				m.inputBuffer = string(runes[:len(runes)-1])
			}
		case tea.KeySpace:
			m.inputBuffer += " "
		case tea.KeyDown:
			input = []byte("\x1b[B")
		case tea.KeyUp:
			input = []byte("\x1b[A")
		case tea.KeyRight:
			input = []byte("\x1b[C")
		case tea.KeyLeft:
			input = []byte("\x1b[D")
		case tea.KeyTab:
			input = []byte("\t")
		case tea.KeyDelete:
			m.inputBuffer = ""
		default:
			s := msg.String()
			if runes := []rune(s); len(runes) == 1 && runes[0] >= 32 {
				m.inputBuffer += s
			}
		}

		if input != nil {
			if err := p.WriteInput(input); err != nil {
				m.dbg("pty write error: %v", err)
			} else {
				m.dbg("pty send: %q", input)
			}
		}
		return m, tea.Batch(cmds...)
	}

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

	case key.Matches(msg, m.keys.NextProc), key.Matches(msg, m.keys.KeyDown):
		if m.focusedPane == focusServices {
			moved := false
			if m.isGrouped() {
				moved = m.nextProcEntry()
			} else if m.servicesCursor < len(m.services)-1 {
				m.servicesCursor++
				moved = true
			}
			if moved {
				m.ensureSidebarCursorVisible()
				m.updateProcKeys()
				m.dbg("proc selected: %s", m.services[m.servicesCursor].Name)
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

	case key.Matches(msg, m.keys.PrevProc), key.Matches(msg, m.keys.KeyUp):
		if m.focusedPane == focusServices {
			moved := false
			if m.isGrouped() {
				moved = m.prevProcEntry()
			} else if m.servicesCursor > 0 {
				m.servicesCursor--
				moved = true
			}
			if moved {
				m.ensureSidebarCursorVisible()
				m.updateProcKeys()
				m.dbg("proc selected: %s", m.services[m.servicesCursor].Name)
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

	case msg.Code == tea.KeyEscape:
		if !m.viewportAtBottom {
			m.dbg("viewport: escape → goto bottom")
			m.viewport.GotoBottom()
			m.viewportAtBottom = true
		}

	case key.Matches(msg, m.keys.Start):
		if p := m.activeProc(); p != nil && !p.IsRunning() {
			m.dbg("start: proc=%s", p.Name)
			send := m.mgr.Send()
			go func() { _ = p.Start(send) }()
		}

	case key.Matches(msg, m.keys.Restart):
		if p := m.activeProc(); p != nil && p.IsRunning() {
			m.dbg("restart: proc=%s", p.Name)
			send := m.mgr.Send()
			go p.Restart(send)
		}

	case key.Matches(msg, m.keys.Stop):
		if p := m.activeProc(); p != nil && p.IsRunning() {
			m.dbg("stop: proc=%s", p.Name)
			p.Stop()
		}

	case key.Matches(msg, m.keys.ClearLogs):
		if p := m.activeProc(); p != nil && p.IsRunning() {
			m.dbg("clear logs: proc=%s", p.Name)
			p.ClearLines()
			var loadCmds []tea.Cmd
			m, loadCmds = m.loadActiveProc()
			cmds = append(cmds, loadCmds...)
		}

	case key.Matches(msg, m.keys.SearchMode):
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

	case key.Matches(msg, m.keys.Sort):
		m.sortMode = (m.sortMode + 1) % SortMode(sortModeCount)
		m.sortServices()
		m.dbg("sort: %s", m.sortMode)

	case key.Matches(msg, m.keys.Group):
		m.cycleGroup()
		m.rebuildSidebarEntries()
		m.ensureSidebarCursorVisible()
		m.dbg("group: %s", m.activeGroupDim())

	case key.Matches(msg, m.keys.InfoMode):
		m.infoMode = true
		m.toggleMetricsOnSelectedProc()
		m.refreshInfoContent()
		m.viewport.GotoTop()
		m.dbg("info mode: enter")

	case key.Matches(msg, m.keys.SetupMode):
		m = m.enterSetupMode()
		m.dbg("setup mode: enter")

	case key.Matches(msg, m.keys.Hedgehog):
		m.hedgehogMode = !m.hedgehogMode
		m.dbg("hedgehog mode: %v", m.hedgehogMode)
		if m.hedgehogMode {
			m.hedgehogX = 0
			m.hedgehogDir = 1
			m.hedgehogFrame = 0
			cmds = append(cmds, hedgehogTick())
		}

	case key.Matches(msg, m.keys.ProcViewer):
		if p := m.activeProc(); p != nil {
			if pid := p.PID(); pid > 0 {
				cmd := procViewerCmd(pid)
				if cmd != nil {
					m.dbg("proc viewer: %s %v", cmd.Path, cmd.Args)
					return m, tea.ExecProcess(cmd, nil)
				}
			}
		}

	case key.Matches(msg, m.keys.LazyDocker):
		if path, err := exec.LookPath("lazydocker"); err == nil {
			args := []string{}
			for _, f := range m.composeArgs.Files {
				args = append(args, "-f", f)
			}
			m.dbg("lazydocker: %v", args)
			c := exec.Command(path, args...)
			return m, tea.ExecProcess(c, nil)
		}

	default:
		if m.handleViewportNavKey(msg, &cmds) {
			break
		}
		if m.focusedPane == focusOutput {
			cmds = append(cmds, m.forwardToViewport(msg))
		}
	}

	return m, tea.Batch(cmds...)
}
