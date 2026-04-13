package tui

import (
	"log"
	"sort"
	"strings"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/docker"
	"github.com/posthog/posthog/phrocs/internal/process"
)

type focusPane int

const (
	focusServices focusPane = iota
	focusOutput
	focusContainers
)

type SortMode int

const (
	SortName SortMode = iota
	SortCPU
	SortRAM
	SortStatus
	sortModeCount // sentinel for cycling
)

func (s SortMode) String() string {
	switch s {
	case SortName:
		return "name"
	case SortCPU:
		return "CPU"
	case SortRAM:
		return "RAM"
	case SortStatus:
		return "status"
	default:
		return "name"
	}
}

type Model struct {
	mgr *process.Manager

	focusedPane focusPane

	// Center viewport with output of the active process
	viewport         viewport.Model
	viewportAtBottom bool
	activeLines      []string

	// Copy mode: keyboard-driven line selection within the output pane
	copyMode   bool
	copyAnchor int
	copyCursor int

	// Search / filter query — shared between searchMode (highlights matches)
	// and filterMode (shows only matching lines)
	searchMode    bool
	filterMode    bool
	searchQuery   string
	searchMatches []int // line indices that contain the match
	searchCursor  int   // index into searchMatches (current highlighted match)

	// Sidebar with list of processes, always visible (when not in copy mode)
	services       []*process.Process
	servicesCursor int
	servicesOffset int
	sortMode       SortMode

	// Docker container sidebar (visible when docker-compose proc is selected)
	containers         []docker.DockerContainer
	containerCursor    int // 0 = status overview, 1+ = container index
	containerOffset    int
	containerLines     []string
	containerLogStream *docker.ContainerLogStream
	composeArgs        docker.ComposeArgs

	// Buffered text for PTY input when the output pane is focused
	inputBuffer string

	// Setup mode: full-screen intent selection for dev environment config
	setupMode    bool
	setupStep    int // 1 = intent selection, 2 = unit exclusion
	setupEntries []config.Intent
	setupCursor  int
	setupOffset  int
	setupChecked map[string]bool
	setupIntents []string // intents selected in step 1
	setupError   string   // error message from applying changes
	configPath   string   // path to the running config file

	// Info mode: replaces the output viewport with process stats
	infoMode bool

	// Hedgehog mode: animated hedgehog walks across the output pane
	hedgehogMode  bool
	hedgehogX     int
	hedgehogY     int // vertical offset from ground (positive = up)
	hedgehogVelY  int // vertical velocity (positive = upward, decreases each tick)
	hedgehogDir   int // +1 right, -1 left
	hedgehogFrame int

	keys     keyMap
	help     help.Model
	spinner  spinner.Model
	showHelp bool

	width  int
	height int
	ready  bool
	isDark bool

	mouseScrollSpeed int
	hideHelp         bool // hide_keymap_window from config
	procListWidth    int  // proc_list_width from config (0 = use default)

	// Writes go to /tmp/phrocs-debug.log
	log *log.Logger
}

// Pass a non-nil logger to enable debug logging (key inputs, selection changes, etc.)
func New(mgr *process.Manager, cfg *config.Config, configPath string, logger *log.Logger) Model {
	keys := defaultKeyMap()

	h := help.New()
	h.Styles = helpStyles()

	return Model{
		mgr:              mgr,
		services:         mgr.Procs(),
		servicesCursor:   0,
		servicesOffset:   0,
		focusedPane:      focusServices,
		viewportAtBottom: true,
		isDark:           true,
		mouseScrollSpeed: cfg.MouseScrollSpeed,
		hideHelp:         cfg.HideKeymapWindow,
		procListWidth:    cfg.ProcListWidth,
		configPath:       configPath,
		keys:             keys,
		help:             h,
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
		wasReady := m.ready
		m = m.applySize()
		if !wasReady && m.ready {
			var loadCmds []tea.Cmd
			m, loadCmds = m.loadActiveProc()
			cmds = append(cmds, loadCmds...)
		}

	case tea.BackgroundColorMsg:
		m.isDark = msg.IsDark()

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)

	case process.MetricsMsg:
		if m.infoMode {
			m.refreshInfoContent()
		}

	case process.OutputMsg:
		// Rebuild viewport content only for the active process to keep rendering cheap
		if p := m.activeProc(); m.ready && p != nil && p.Name == msg.Name {
			// Clear the active process's unread flag
			p.MarkRead()
			// In docker mode the viewport shows the status table or container logs,
			// not the process's combined output
			if m.isDockerMode() || m.infoMode {
				break
			}
			m.reloadActiveLines()
			if m.filterMode {
				m.recomputeFilter()
			} else if m.searchQuery != "" {
				m.recomputeSearch()
			}
			// Don't auto-scroll while the user is selecting text in copy mode
			if m.viewportAtBottom && !m.copyMode && !m.searchMode && !m.filterMode {
				m.viewport.GotoBottom()
			}
		}

	case process.StatusMsg:
		m.dbg("status: proc=%s status=%s", msg.Name, msg.Status)
		// Capture the active name before re-fetching so sortServices
		// can restore the cursor to the same process.
		activeName := ""
		if p := m.activeProc(); p != nil {
			activeName = p.Name
		}
		// Re-fetch the process slice so status icons refresh on next render
		m.services = m.mgr.Procs()
		// Restore cursor to the same process in the new (unsorted) slice
		m.servicesCursor = 0
		for i, p := range m.services {
			if p.Name == activeName {
				m.servicesCursor = i
				break
			}
		}
		m.sortServices()
		m.updateProcKeys()

	case process.FocusMsg:
		m.dbg("focus: proc=%s (via IPC)", msg.Name)
		for i, p := range m.services {
			if p.Name == msg.Name {
				m.servicesCursor = i
				m.ensureSidebarCursorVisible()
				m.updateProcKeys()
				var loadCmds []tea.Cmd
				m, loadCmds = m.loadActiveProc()
				cmds = append(cmds, loadCmds...)
				break
			}
		}

	case listUnitsMsg:
		m.handleListUnitsMsg(msg)

	case devApplyMsg:
		m.handleDevApplyMsg(msg)

	// Container-related messages only relevant in docker mode
	case docker.ContainerListMsg:
		if m.isDockerMode() {
			m.containers = msg.Containers
			total := m.containerEntryCount()
			if m.containerCursor >= total {
				m.containerCursor = max(0, total-1)
			}
			m.ensureContainerCursorVisible()
			if m.containerCursor == 0 {
				m.viewport.SetContent(docker.RenderContainerStatusTable(m.containers, m.viewport.Width()))
			}
		}

	case docker.ContainerPollTickMsg:
		if m.isDockerMode() {
			cmds = append(cmds, docker.FetchContainerList(m.composeArgs), docker.PollContainersTick())
		}

	case docker.ContainerLogLineMsg:
		svc := m.selectedContainerService()
		if m.isDockerMode() && svc == msg.Service {
			evicted := len(m.containerLines) >= docker.MaxContainerLogLines
			if evicted {
				m.containerLines = m.containerLines[1:]
			}
			m.containerLines = append(m.containerLines, msg.Line)
			lineIndex := len(m.containerLines) - 1
			if m.filterMode {
				m.recomputeFilter()
			} else {
				m.viewport.SetContent(strings.Join(m.containerLines, "\n"))
			}
			if m.viewportAtBottom && !m.copyMode && !m.searchMode && !m.filterMode {
				m.viewport.GotoBottom()
			}
			if !m.filterMode && m.searchQuery != "" {
				m.updateSearchForLine(msg.Line, lineIndex, evicted)
			}
		}

	case hedgehogTickMsg:
		if m.hedgehogMode {
			m.advanceHedgehog()
			cmds = append(cmds, hedgehogTick())
		}

	case tea.KeyPressMsg:
		m.dbg("key: %q", msg.String())
		var handled bool
		if m.searchMode {
			m, cmds, handled = m.handleSearchKey(msg, cmds)
		} else if m.filterMode {
			m, cmds, handled = m.handleFilterKey(msg, cmds)
		} else if m.copyMode {
			m, cmds, handled = m.handleCopyKey(msg, cmds)
		} else if m.infoMode {
			m, cmds, handled = m.handleInfoKey(msg, cmds)
		} else if m.setupMode {
			m, cmds, handled = m.handleSetupKey(msg, cmds)
		} else if m.hedgehogMode {
			m, cmds, handled = m.handleHedgehogKey(msg, cmds)
		}
		if !handled {
			return m.handleNormalKey(msg, cmds)
		}

	case tea.MouseClickMsg:
		return m.handleMouseClick(msg, cmds)

	case tea.MouseWheelMsg:
		if msg.X < sidebarWidth {
			delta := 0
			switch msg.Button {
			case tea.MouseWheelDown:
				delta = 1
			case tea.MouseWheelUp:
				delta = -1
			}
			newCursor := max(0, min(m.servicesCursor+delta, len(m.services)-1))
			if newCursor != m.servicesCursor {
				m.servicesCursor = newCursor
				m.ensureSidebarCursorVisible()
				m.updateProcKeys()
				var loadCmds []tea.Cmd
				m, loadCmds = m.loadActiveProc()
				cmds = append(cmds, loadCmds...)
			}
		} else {
			var vpCmd tea.Cmd
			m.viewport, vpCmd = m.viewport.Update(msg)
			cmds = append(cmds, vpCmd)
			m.viewportAtBottom = m.viewport.AtBottom()
		}

	case tea.MouseMsg:
		var vpCmd tea.Cmd
		m.viewport, vpCmd = m.viewport.Update(msg)
		cmds = append(cmds, vpCmd)
		m.viewportAtBottom = m.viewport.AtBottom()
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
	if m.setupMode {
		middle = m.renderSetupView()
	} else if m.isFullScreen() {
		middle = m.renderOutput()
	} else if m.isDockerMode() {
		middle = lipgloss.JoinHorizontal(lipgloss.Top, m.renderSidebar(), m.renderOutput(), m.renderContainerSidebar())
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
	if m.isFullScreen() {
		v.MouseMode = tea.MouseModeNone
	} else {
		v.MouseMode = tea.MouseModeCellMotion
	}
	return v
}

// Returns true when sidebars should be hidden and the output pane
// fills the full width (copy mode or any search state).
func (m Model) isFullScreen() bool {
	return m.copyMode || m.searchMode || m.filterMode || m.setupMode
}

func (m Model) activeProc() *process.Process {
	if len(m.services) == 0 || m.servicesCursor >= len(m.services) {
		return nil
	}
	return m.services[m.servicesCursor]
}

// Returns the configured proc_list_width, or the default.
func (m Model) effectiveSidebarWidth() int {
	if m.procListWidth > 0 {
		return m.procListWidth
	}
	return sidebarWidth
}

func (m Model) footerHeight() int {
	if m.hideHelp {
		return 1
	}
	if m.showHelp {
		return footerHeightFull
	}
	return footerHeightShort
}

// Recalculates viewport/sidebar dimensions whenever the terminal resizes
// or the footer height changes
func (m Model) applySize() Model {
	fh := m.footerHeight()
	contentH := max(m.height-headerHeight-fh, 1)
	// In copy mode the sidebar is hidden, so the viewport fills the full width.
	// The PTY width is always the sidebar-adjusted value so processes don't
	// receive a spurious resize when the user enters or exits copy mode
	ptyW := m.width - m.effectiveSidebarWidth()
	if m.isDockerMode() && !m.isFullScreen() {
		ptyW -= containerSidebarWidth
	}
	ptyW = max(ptyW, 1)

	// Reduce the viewport width to account for borders
	vpW := ptyW - horizontalBorderCount
	if m.isFullScreen() {
		vpW = m.width
	}

	if !m.ready {
		m.viewport = viewport.New(viewport.WithWidth(vpW), viewport.WithHeight(contentH))
		m.viewport.MouseWheelDelta = m.mouseScrollSpeed
		m.ready = true
	} else {
		m.viewport.SetWidth(vpW)
		m.viewport.SetHeight(contentH)
	}

	m.updateProcKeys()
	m.ensureSidebarCursorVisible()

	// Keep every pty window size in sync with the sidebar-adjusted width so
	// programs that detect terminal width (webpack, Django dev-server) reflow
	// correctly, and are not affected by copy mode toggling
	for _, p := range m.services {
		p.Resize(uint16(vpW), uint16(contentH))
	}

	return m
}

// Reloads the viewport with the selected process's output.
// Switching processes always exits copy mode and search typing mode.
// The search query is preserved across non-docker processes, but entering
// docker mode resets the search query and matches.
func (m Model) loadActiveProc() (Model, []tea.Cmd) {
	if !m.ready {
		return m, nil
	}

	// Stop any active container log stream from the previous selection
	if m.containerLogStream != nil {
		m.containerLogStream.Stop()
		m.containerLogStream = nil
	}

	m.copyMode = false
	m.searchMode = false
	m.filterMode = false
	m.inputBuffer = ""
	m.viewport.StyleLineFunc = nil

	// Mark the newly active process as read
	if p := m.activeProc(); p != nil {
		p.MarkRead()
	}

	// Resize viewport to account for container sidebar appearing/disappearing
	m = m.applySize()

	var cmds []tea.Cmd

	m.containerCursor = 0
	m.containerOffset = 0
	m.containerLines = nil

	if m.isDockerMode() {
		m.composeArgs = docker.ParseComposeArgs(m.activeProc().Cfg.Shell)
		m.searchQuery = ""
		m.searchMatches = nil
		m.searchCursor = 0
		m.activeLines = nil
		m.infoMode = false
		m.disableAllMetrics()
		m.keys.LazyDocker.SetEnabled(true)
		m.keys.ProcViewer.SetEnabled(false)
		m.viewport.SetContent(docker.RenderContainerStatusTable(m.containers, m.viewport.Width()))
		cmds = append(cmds, docker.FetchContainerList(m.composeArgs), docker.PollContainersTick())
	} else {
		m.focusedPane = focusServices
		m.containers = nil
		m.keys.LazyDocker.SetEnabled(false)
		m.keys.ProcViewer.SetEnabled(true)
		m.disableAllMetrics()
		if m.infoMode {
			m.toggleMetricsOnSelectedProc()
			m.refreshInfoContent()
		} else {
			m.reloadActiveLines()
		}
	}

	// Scroll to bottom when switching processes if viewport was already at bottom
	if m.viewportAtBottom {
		m.viewport.GotoBottom()
	}
	// Recompute search matches for the newly selected process
	if m.searchQuery != "" {
		m.recomputeSearch()
	}
	return m, cmds
}

func (m *Model) disableAllMetrics() {
	for _, p := range m.services {
		p.SetMetricsEnabled(false)
	}
}

// Reloads activeLines from the process buffer and pushes to the viewport.
func (m *Model) reloadActiveLines() {
	p := m.activeProc()
	if p == nil {
		m.activeLines = nil
	} else {
		m.activeLines = p.Lines()
	}
	m.viewport.SetContent(strings.Join(m.activeLines, "\n"))
}

// statusSortOrder returns a numeric rank for sorting by status.
// Running/pending processes sort first, done last.
func statusSortOrder(s process.Status) int {
	switch s {
	case process.StatusRunning:
		return 0
	case process.StatusPending:
		return 1
	case process.StatusCrashed:
		return 2
	case process.StatusStopped:
		return 3
	case process.StatusDone:
		return 4
	default:
		return 5
	}
}

// sortServices re-sorts m.services by the current sortMode, preserving
// the cursor on the same process.
func (m *Model) sortServices() {
	if len(m.services) == 0 {
		return
	}
	activeName := ""
	if m.servicesCursor < len(m.services) {
		activeName = m.services[m.servicesCursor].Name
	}

	sort.SliceStable(m.services, func(i, j int) bool {
		a, b := m.services[i], m.services[j]

		switch m.sortMode {
		case SortCPU:
			return a.CPUPercent() > b.CPUPercent()
		case SortRAM:
			return a.MemRSSMB() > b.MemRSSMB()
		case SortStatus:
			sa, sb := statusSortOrder(a.Status()), statusSortOrder(b.Status())
			if sa != sb {
				return sa < sb
			}
			return a.Name < b.Name
		default:
			// Always place info at the top of the list
			if a.Name == "info" {
				return true
			}
			if b.Name == "info" {
				return false
			}
			return a.Name < b.Name
		}
	})

	// Restore cursor to the same process
	for i, p := range m.services {
		if p.Name == activeName {
			m.servicesCursor = i
			break
		}
	}
	m.ensureSidebarCursorVisible()
}

func (m Model) toggleMetricsOnSelectedProc() {
	if p := m.activeProc(); p != nil {
		p.SetMetricsEnabled(true)
	}
}
