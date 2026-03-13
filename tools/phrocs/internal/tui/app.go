package tui

import (
	"fmt"
	"log"
	"os/exec"
	"strings"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
	"github.com/posthog/posthog/phrocs/internal/process"
)

type focusPane int

const (
	focusSidebar focusPane = iota
	focusOutput
)

type Model struct {
	mgr   *process.Manager
	procs []*process.Process

	// Currently selected process in the sidebar
	cursor int
	// First visible process row in the sidebar
	sidebarOffset int

	// Tracks which pane has focus (sidebar or output)
	focusedPane focusPane

	viewport viewport.Model
	// Tracks whether the viewport is auto-scrolling to the tail of output
	atBottom bool

	// Copy mode: keyboard-driven line selection within the output pane
	copyMode   bool
	copyAnchor int
	copyCursor int

	// Search mode: output line filtering
	searchMode    bool
	searchQuery   string
	searchMatches []int // line indices that contain the match
	searchCursor  int   // index into searchMatches (current highlighted match)

	keys     keyMap
	help     help.Model
	spinner  spinner.Model
	showHelp bool

	width  int
	height int
	ready  bool

	mouseScrollSpeed int

	// Writes go to /tmp/phrocs-debug.log
	log *log.Logger
}

// Pass a non-nil logger to enable debug logging (key inputs, selection changes, etc.)
func New(mgr *process.Manager, mouseScrollSpeed int, logger *log.Logger) Model {
	keys := defaultKeyMap()

	// Enable docker key only if lazydocker is installed
	if _, err := exec.LookPath("lazydocker"); err == nil {
		keys.Docker.SetEnabled(true)
	}

	return Model{
		mgr:              mgr,
		procs:            mgr.Procs(),
		cursor:           0,
		sidebarOffset:    0,
		focusedPane:      focusSidebar,
		atBottom:         true,
		mouseScrollSpeed: mouseScrollSpeed,
		keys:             keys,
		help:             help.New(),
		spinner:          spinner.New(spinner.WithSpinner(spinner.MiniDot)),
		log:              logger,
	}
}

func (m Model) dbg(format string, args ...any) {
	if m.log != nil {
		m.log.Printf(format, args...)
	}
}

// Note: Processes are started externally before p.Run()
func (m Model) Init() tea.Cmd {
	return tea.Batch(tea.RequestBackgroundColor, m.spinner.Tick)
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {

	case tea.WindowSizeMsg:
		m.dbg("resize: %dx%d", msg.Width, msg.Height)
		m.width = msg.Width
		m.height = msg.Height
		m = m.applySize()

	case tea.BackgroundColorMsg:
		isDark := msg.IsDark()
		m.help.Styles = help.DefaultStyles(isDark)

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)

	case process.OutputMsg:
		// Rebuild viewport content only for the active process to keep rendering cheap
		if m.ready && m.activeProc() != nil && m.activeProc().Name == msg.Name {
			m.viewport.SetContent(m.buildContent())
			// Don't auto-scroll while the user is selecting text in copy mode
			if m.atBottom && !m.copyMode {
				m.viewport.GotoBottom()
			}
			// Incrementally update search matches to avoid rescanning the full
			// scrollback on every new line — O(M) per line instead of O(N).
			if m.searchQuery != "" {
				m.updateSearchForNewLine(msg)
			}
		}

	case process.StatusMsg:
		m.dbg("status: proc=%s status=%s", msg.Name, msg.Status)
		// Re-fetch the process slice so status icons refresh on next render
		m.procs = m.mgr.Procs()
		if m.cursor >= len(m.procs) {
			m.cursor = max(0, len(m.procs)-1)
		}
		m.ensureSidebarCursorVisible()

	case tea.KeyPressMsg:
		m.dbg("key: %q", msg.String())

		// Search mode: '/' to enter, type to filter, enter to confirm,
		// esc to leave, enter/shift+enter to navigate matches.
		if m.searchMode {
			s := msg.String()
			switch {
			case key.Matches(msg, m.keys.Quit), key.Matches(msg, m.keys.CopyEsc):
				m.searchMode = false
				m.searchQuery = ""
				m.searchMatches = nil
				m.searchCursor = 0
				m.viewport.StyleLineFunc = nil
			case s == "enter":
				m.searchMode = false
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

		// Copy mode consumes most keys. First press 'c' to enter,
		// navigate with ↑/↓, press 'c' again to set the selection anchor, then
		// navigate to extend the selection, then 'c' to yank.
		if m.copyMode {
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
					m.dbg("copy mode: copied %d lines", strings.Count(text, "\n")+1)
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

		switch {
		case key.Matches(msg, m.keys.Quit):
			m.mgr.StopAll()
			return m, tea.Quit

		case key.Matches(msg, m.keys.Help):
			m.showHelp = !m.showHelp
			m.dbg("help toggled: showHelp=%v", m.showHelp)
			// Recompute sizes since footer height may change
			m = m.applySize()

		case key.Matches(msg, m.keys.SwapFocus):
			if m.focusedPane == focusSidebar {
				m.focusedPane = focusOutput
				m.dbg("focus: sidebar → output")
			} else {
				m.focusedPane = focusSidebar
				m.dbg("focus: output → sidebar")
			}

		case key.Matches(msg, m.keys.NextProc):
			// When sidebar focused: navigate to next process
			// When output focused: scroll down
			if m.focusedPane == focusSidebar {
				if m.cursor < len(m.procs)-1 {
					prev := m.cursor
					m.cursor++
					m.ensureSidebarCursorVisible()
					m.dbg("proc selected: %d→%d (%s)", prev, m.cursor, m.procs[m.cursor].Name)
					m = m.loadActiveProc()
				}
			} else {
				// Forward to viewport for scrolling
				var vpCmd tea.Cmd
				m.viewport, vpCmd = m.viewport.Update(msg)
				cmds = append(cmds, vpCmd)
				m.atBottom = m.viewport.AtBottom()
			}

		case key.Matches(msg, m.keys.PrevProc):
			// When sidebar focused: navigate to previous process
			// When output focused: scroll up
			if m.focusedPane == focusSidebar {
				if m.cursor > 0 {
					prev := m.cursor
					m.cursor--
					m.ensureSidebarCursorVisible()
					m.dbg("proc selected: %d→%d (%s)", prev, m.cursor, m.procs[m.cursor].Name)
					m = m.loadActiveProc()
				}
			} else {
				// Forward to viewport for scrolling
				var vpCmd tea.Cmd
				m.viewport, vpCmd = m.viewport.Update(msg)
				cmds = append(cmds, vpCmd)
				m.atBottom = m.viewport.AtBottom()
			}

		case key.Matches(msg, m.keys.GotoTop):
			m.dbg("viewport: goto top")
			m.viewport.GotoTop()
			m.atBottom = false

		case key.Matches(msg, m.keys.GotoBottom):
			m.dbg("viewport: goto bottom")
			m.viewport.GotoBottom()
			m.atBottom = true

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

		case key.Matches(msg, m.keys.Docker):
			m.dbg("docker: launching lazydocker")
			return m, tea.ExecProcess(exec.Command("lazydocker"), nil)

		case key.Matches(msg, m.keys.Search):
			m.searchMode = true
			m.searchQuery = ""
			m.searchMatches = nil
			m.searchCursor = 0
			m.viewport.StyleLineFunc = nil

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
				m.atBottom = m.viewport.AtBottom()
			}
		}

	case tea.MouseClickMsg:
		// Handle left clicks in the sidebar to select a process
		if msg.Button == tea.MouseLeft {
			// Sidebar is from x=0 to x=sidebarWidth-1, content starts at y=headerHeight
			if msg.X < sidebarWidth && msg.Y >= headerHeight {
				m.focusedPane = focusSidebar
				m.dbg("focus: mouse click → sidebar")
				row := msg.Y - headerHeight - 1
				idx := m.sidebarOffset + row
				if idx >= 0 && idx < len(m.procs) {
					prev := m.cursor
					m.cursor = idx
					m.ensureSidebarCursorVisible()
					if prev != m.cursor {
						m.dbg("proc selected (mouse): %d→%d (%s)", prev, m.cursor, m.procs[m.cursor].Name)
						m = m.loadActiveProc()
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

	case tea.MouseMsg:
		// Forward other mouse events (wheel, motion, etc.) to viewport
		var vpCmd tea.Cmd
		m.viewport, vpCmd = m.viewport.Update(msg)
		cmds = append(cmds, vpCmd)
		m.atBottom = m.viewport.AtBottom()
	}

	return m, tea.Batch(cmds...)
}

func (m Model) View() tea.View {
	if !m.ready {
		v := tea.NewView("\n  Initialising...\n")
		v.AltScreen = true
		v.MouseMode = tea.MouseModeCellMotion
		return v
	}
	var middle string
	if m.copyMode {
		middle = m.renderOutput()
	} else {
		middle = lipgloss.JoinHorizontal(lipgloss.Top, m.renderSidebar(), m.renderOutput())
	}
	v := tea.NewView(lipgloss.JoinVertical(
		lipgloss.Left,
		m.renderHeader(),
		middle,
		m.renderFooter(),
	))
	v.AltScreen = true
	// Disable mouse capture in copy mode so the terminal handles native text
	// selection within the expanded output pane
	if m.copyMode {
		v.MouseMode = tea.MouseModeNone
	} else {
		v.MouseMode = tea.MouseModeCellMotion
	}
	return v
}

func (m Model) activeProc() *process.Process {
	if len(m.procs) == 0 || m.cursor >= len(m.procs) {
		return nil
	}
	return m.procs[m.cursor]
}

// Recalculates viewport/sidebar dimensions whenever the terminal resizes
// or the footer height changes
func (m Model) applySize() Model {
	fh := footerHeightShort
	if m.showHelp {
		fh = footerHeightFull
	}
	contentH := m.height - headerHeight - fh
	if contentH < 1 {
		contentH = 1
	}
	// In copy mode the sidebar is hidden, so the viewport fills the full width.
	// The PTY width is always the sidebar-adjusted value so processes don't
	// receive a spurious resize when the user enters or exits copy mode
	ptyW := m.width - sidebarWidth
	if ptyW < 1 {
		ptyW = 1
	}
	// Reduce the viewport width to account for borders
	vpW := ptyW - horizontalBorderCount
	if m.copyMode {
		vpW = m.width - horizontalBorderCount
	}

	if !m.ready {
		m.viewport = viewport.New(viewport.WithWidth(vpW), viewport.WithHeight(contentH))
		m.viewport.MouseWheelDelta = m.mouseScrollSpeed
		m.ready = true
		m = m.loadActiveProc()
	} else {
		m.viewport.SetWidth(vpW)
		m.viewport.SetHeight(contentH)
	}

	m.ensureSidebarCursorVisible()

	// Keep every pty window size in sync with the sidebar-adjusted width so
	// programs that detect terminal width (webpack, Django dev-server) reflow
	// correctly, and are not affected by copy mode toggling
	for _, p := range m.procs {
		p.Resize(uint16(ptyW), uint16(contentH))
	}

	return m
}

// Reloads the viewport with the selected process's output.
// Switching processes always exits copy mode and search typing mode,
// but preserves the search query so matches are shown in the new process.
func (m Model) loadActiveProc() Model {
	if !m.ready {
		return m
	}
	m.copyMode = false
	m.searchMode = false
	m.viewport.StyleLineFunc = nil
	m.viewport.SetContent(m.buildContent())
	if m.atBottom {
		m.viewport.GotoBottom()
	}
	// Recompute search matches for the newly selected process
	if m.searchQuery != "" {
		m.recomputeSearch()
	}
	return m
}

// Joins the active process's output lines into a viewport content string
func (m Model) buildContent() string {
	p := m.activeProc()
	if p == nil {
		return ""
	}
	return strings.Join(p.Lines(), "\n")
}

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
	p := m.activeProc()
	if p == nil {
		return ""
	}
	lines := p.Lines()
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

// Recomputes searchMatches from current process output
func (m *Model) recomputeSearch() {
	if m.searchQuery == "" {
		m.searchMatches = nil
		m.searchCursor = 0
		m.viewport.StyleLineFunc = nil
		return
	}
	p := m.activeProc()
	if p == nil {
		m.searchMatches = nil
		return
	}
	query := strings.ToLower(m.searchQuery)
	lines := p.Lines()
	m.searchMatches = nil
	for i, line := range lines {
		if strings.Contains(strings.ToLower(ansi.Strip(line)), query) {
			m.searchMatches = append(m.searchMatches, i)
		}
	}
	if m.searchCursor >= len(m.searchMatches) {
		if len(m.searchMatches) > 0 {
			m.searchCursor = len(m.searchMatches) - 1
		} else {
			m.searchCursor = 0
		}
	}
	m.applySearchStyle()
}

// Updates the viewport's StyleLineFunc to highlight search matches.
func (m *Model) applySearchStyle() {
	if len(m.searchMatches) == 0 {
		m.viewport.StyleLineFunc = nil
		return
	}
	matchSet := make(map[int]bool, len(m.searchMatches))
	for _, idx := range m.searchMatches {
		matchSet[idx] = true
	}
	current := m.searchMatches[m.searchCursor]
	m.viewport.StyleLineFunc = func(idx int) lipgloss.Style {
		if idx == current {
			return searchCurrentMatchStyle
		}
		if matchSet[idx] {
			return searchMatchStyle
		}
		return lipgloss.NewStyle()
	}
}

// Incrementally maintains searchMatches when a single new line arrives.
// Adjusts existing indices for scrollback eviction, then checks the new line.
// This keeps search O(M) per incoming line rather than O(N).
func (m *Model) updateSearchForNewLine(msg process.OutputMsg) {
	if msg.Evicted && len(m.searchMatches) > 0 {
		// The line at index 0 was dropped; remove it from matches if present.
		if m.searchMatches[0] == 0 {
			m.searchMatches = m.searchMatches[1:]
			if m.searchCursor > 0 {
				m.searchCursor--
			} else if len(m.searchMatches) == 0 {
				m.searchCursor = 0
			}
		}
		// All remaining indices shifted down by one.
		for i := range m.searchMatches {
			m.searchMatches[i]--
		}
	}
	if strings.Contains(strings.ToLower(ansi.Strip(msg.Line)), strings.ToLower(m.searchQuery)) {
		m.searchMatches = append(m.searchMatches, msg.LineIndex)
	}
	m.applySearchStyle()
}

// Scrolls the viewport so the current search match is centered.
func (m *Model) jumpToCurrentMatch() {
	if len(m.searchMatches) == 0 {
		return
	}
	lineIdx := m.searchMatches[m.searchCursor]
	h := m.viewport.Height()
	offset := lineIdx - h/2
	if offset < 0 {
		offset = 0
	}
	m.viewport.SetYOffset(offset)
	m.atBottom = m.viewport.AtBottom()
}

func (m Model) renderHeader() string {
	brand := headerBrandStyle.Render("phrocs")

	running := 0
	for _, p := range m.procs {
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

	start := m.sidebarOffset
	if start < 0 {
		start = 0
	}
	if start > max(0, len(m.procs)-1) {
		start = max(0, len(m.procs)-1)
	}
	end := min(len(m.procs), start+h)

	var rows []string
	for i := start; i < end; i++ {
		p := m.procs[i]
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
		if i == m.cursor {
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
	if m.focusedPane == focusSidebar {
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
// sidebar window by adjusting sidebarOffset
func (m *Model) ensureSidebarCursorVisible() {
	h := m.sidebarHeight()
	if len(m.procs) <= h {
		m.sidebarOffset = 0
		return
	}

	maxOffset := len(m.procs) - h
	if m.sidebarOffset > maxOffset {
		m.sidebarOffset = maxOffset
	}
	if m.sidebarOffset < 0 {
		m.sidebarOffset = 0
	}

	if m.cursor < m.sidebarOffset {
		m.sidebarOffset = m.cursor
	}
	if m.cursor >= m.sidebarOffset+h {
		m.sidebarOffset = m.cursor - h + 1
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
