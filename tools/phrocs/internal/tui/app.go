package tui

import (
	"log"
	"strings"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/docker"
	"github.com/posthog/posthog/phrocs/internal/process"
)

type focusPane int

const (
	focusServices focusPane = iota
	focusOutput
	focusContainers
)

type Model struct {
	mgr *process.Manager

	focusedPane focusPane

	// Center viewport with output of the active process
	viewport         viewport.Model
	viewportAtBottom bool

	// Copy mode: keyboard-driven line selection within the output pane
	copyMode   bool
	copyAnchor int
	copyCursor int

	// Search mode: output line filtering
	searchMode    bool
	searchQuery   string
	searchMatches []int // line indices that contain the match
	searchCursor  int   // index into searchMatches (current highlighted match)

	// Sidebar with list of processes, always visible (when not in copy mode)
	services       []*process.Process
	servicesCursor int
	servicesOffset int

	// Docker container sidebar (visible when docker-compose proc is selected)
	containers         []docker.DockerContainer
	containerCursor    int // 0 = status overview, 1+ = container index
	containerOffset    int
	containerLines     []string
	containerLogStream *docker.ContainerLogStream
	composeArgs        docker.ComposeArgs

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

	mouseScrollSpeed int

	// Writes go to /tmp/phrocs-debug.log
	log *log.Logger
}

// Pass a non-nil logger to enable debug logging (key inputs, selection changes, etc.)
func New(mgr *process.Manager, mouseScrollSpeed int, logger *log.Logger) Model {
	keys := defaultKeyMap()

	return Model{
		mgr:              mgr,
		services:         mgr.Procs(),
		servicesCursor:   0,
		servicesOffset:   0,
		focusedPane:      focusServices,
		viewportAtBottom: true,
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
		wasReady := m.ready
		m = m.applySize()
		if !wasReady && m.ready {
			var loadCmds []tea.Cmd
			m, loadCmds = m.loadActiveProc()
			cmds = append(cmds, loadCmds...)
		}

	case tea.BackgroundColorMsg:
		isDark := msg.IsDark()
		m.help.Styles = help.DefaultStyles(isDark)

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)
		// Refresh info panel on each spinner tick to keep uptime current
		if m.infoMode {
			m.refreshInfoContent()
		}

	case process.OutputMsg:
		// Rebuild viewport content only for the active process to keep rendering cheap
		if m.ready && m.activeProc() != nil && m.activeProc().Name == msg.Name {
			// In docker mode the viewport shows the status table or container logs,
			// not the process's combined output
			if m.isDockerMode() || m.infoMode {
				break
			}
			m.viewport.SetContent(m.buildContent())
			// Don't auto-scroll while the user is selecting text in copy mode
			if m.viewportAtBottom && !m.copyMode && !m.searchMode {
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
		m.services = m.mgr.Procs()
		if m.servicesCursor >= len(m.services) {
			m.servicesCursor = max(0, len(m.services)-1)
		}
		m.ensureSidebarCursorVisible()

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
			m.viewport.SetContent(strings.Join(m.containerLines, "\n"))
			if m.viewportAtBottom && !m.copyMode && !m.searchMode {
				m.viewport.GotoBottom()
			}
			if m.searchQuery != "" {
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
		} else if m.copyMode {
			m, cmds, handled = m.handleCopyKey(msg, cmds)
		} else if m.infoMode {
			m, cmds, handled = m.handleInfoKey(msg, cmds)
		} else if m.hedgehogMode {
			m, cmds, handled = m.handleHedgehogKey(msg, cmds)
		}
		if !handled {
			return m.handleNormalKey(msg, cmds)
		}

	case tea.MouseClickMsg:
		return m.handleMouseClick(msg, cmds)

	case tea.MouseMsg:
		// Forward other mouse events (wheel, motion, etc.) to viewport
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
	if m.isFullScreen() {
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
	return m.copyMode || m.searchMode
}

func (m Model) activeProc() *process.Process {
	if len(m.services) == 0 || m.servicesCursor >= len(m.services) {
		return nil
	}
	return m.services[m.servicesCursor]
}

// Recalculates viewport/sidebar dimensions whenever the terminal resizes
// or the footer height changes
func (m Model) applySize() Model {
	fh := footerHeightShort
	if m.showHelp {
		fh = footerHeightFull
	}
	contentH := max(m.height-headerHeight-fh, 1)
	// In copy mode the sidebar is hidden, so the viewport fills the full width.
	// The PTY width is always the sidebar-adjusted value so processes don't
	// receive a spurious resize when the user enters or exits copy mode
	ptyW := m.width - sidebarWidth
	if m.isDockerMode() && !m.isFullScreen() {
		ptyW -= containerSidebarWidth
	}
	ptyW = max(ptyW, 1)

	// Reduce the viewport width to account for borders
	vpW := ptyW - horizontalBorderCount
	if m.isFullScreen() {
		vpW = m.width - horizontalBorderCount
	}

	if !m.ready {
		m.viewport = viewport.New(viewport.WithWidth(vpW), viewport.WithHeight(contentH))
		m.viewport.MouseWheelDelta = m.mouseScrollSpeed
		m.ready = true
	} else {
		m.viewport.SetWidth(vpW)
		m.viewport.SetHeight(contentH)
	}

	m.ensureSidebarCursorVisible()

	// Keep every pty window size in sync with the sidebar-adjusted width so
	// programs that detect terminal width (webpack, Django dev-server) reflow
	// correctly, and are not affected by copy mode toggling
	for _, p := range m.services {
		p.Resize(uint16(ptyW), uint16(contentH))
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
	m.viewport.StyleLineFunc = nil

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
		m.viewport.SetContent(docker.RenderContainerStatusTable(m.containers, m.viewport.Width()))
		cmds = append(cmds, docker.FetchContainerList(m.composeArgs), docker.PollContainersTick())
	} else {
		m.focusedPane = focusServices
		m.containers = nil
		m.viewport.SetContent(m.buildContent())
	}

	if m.viewportAtBottom {
		m.viewport.GotoBottom()
	}
	// Recompute search matches for the newly selected process
	if m.searchQuery != "" {
		m.recomputeSearch()
	}
	return m, cmds
}

// Joins the active process's output lines into a viewport content string
func (m Model) buildContent() string {
	p := m.activeProc()
	if p == nil {
		return ""
	}
	return strings.Join(p.Lines(), "\n")
}
