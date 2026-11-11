package tui

import (
	"fmt"
	"image/color"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"

	"charm.land/bubbles/v2/help"
	"charm.land/bubbles/v2/key"
	"charm.land/bubbles/v2/spinner"
	"charm.land/bubbles/v2/viewport"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

// EvalEvent is one progress update that the eval harness streams to `phrocs evals`.
type EvalEvent struct {
	Type        string  `json:"type"`
	Description string  `json:"description,omitempty"`
	Transcript  string  `json:"transcript,omitempty"`
	Phase       string  `json:"phase,omitempty"`
	Stage       string  `json:"stage,omitempty"`
	Name        string  `json:"name,omitempty"`
	Total       int     `json:"total,omitempty"`
	ID          string  `json:"id,omitempty"`
	Experiment  string  `json:"experiment,omitempty"`
	Index       int     `json:"index,omitempty"`
	Started     float64 `json:"started,omitempty"`
	Ended       float64 `json:"ended,omitempty"`
	Detail      string  `json:"detail,omitempty"`
	SummaryPath string  `json:"summary_path,omitempty"`
	LogPath     string  `json:"log_path,omitempty"`
	Text        string  `json:"text,omitempty"`
	ExitCode    *int    `json:"exit_code,omitempty"`
}

type EvalEventMsg EvalEvent

// EvalStreamClosedMsg reports that the harness closed its end of the event stream.
type EvalStreamClosedMsg struct{}

type evalTickMsg struct{}

type evalFileMsg struct {
	path    string
	text    string
	size    int64
	modTime time.Time
	changed bool
}

const (
	evalTailBytes      = 256 * 1024
	evalMaxDiagnostics = 500
	evalPollInterval   = 250 * time.Millisecond
)

var evalDiagnosticPrefixes = []string{"WARNING:", "ERROR:", "error:", "CASE RETRY", "CASE ERROR", "CASE TIMEOUT", "SUITE CRASH"}

type evalTrial struct {
	id          string
	experiment  string
	name        string
	index       int
	phase       string
	started     time.Time
	ended       time.Time
	detail      string
	retries     int
	summaryPath string
	logPath     string
}

func (t *evalTrial) finished() bool {
	switch t.phase {
	case "done", "error", "timeout", "canceled":
		return true
	}
	return false
}

// evalPoint is a cell in the soft-wrapped output: row counts wrapped rows from
// the top of the content, and col counts cells from the left edge of the pane.
type evalPoint struct{ row, col int }

func (p evalPoint) before(o evalPoint) bool {
	return p.row < o.row || (p.row == o.row && p.col < o.col)
}

type wrappedRow struct {
	text string
	// continued is true when the row is a soft-wrapped part of the row above.
	continued bool
}

type evalRow struct {
	header string
	trial  *evalTrial
}

func (r evalRow) selectable() bool { return r.header == "" }

type evalKeyMap struct {
	Up         key.Binding
	Down       key.Binding
	NextPane   key.Binding
	ScrollUp   key.Binding
	ScrollDown key.Binding
	GotoTop    key.Binding
	GotoBottom key.Binding
	Logs       key.Binding
	Search     key.Binding
	CopyMode   key.Binding
	Quit       key.Binding
	Interrupt  key.Binding
	Help       key.Binding
}

func newEvalKeyMap() evalKeyMap {
	return evalKeyMap{
		Up:         key.NewBinding(key.WithKeys("up", "k"), key.WithHelp("↑/k:", "prev")),
		Down:       key.NewBinding(key.WithKeys("down", "j"), key.WithHelp("↓/j:", "next")),
		NextPane:   key.NewBinding(key.WithKeys("tab", "shift+tab"), key.WithHelp("↹:", "focus")),
		ScrollUp:   key.NewBinding(key.WithKeys("pgup"), key.WithHelp("pgup:", "↥")),
		ScrollDown: key.NewBinding(key.WithKeys("pgdown"), key.WithHelp("pgdn:", "↧")),
		GotoTop:    key.NewBinding(key.WithKeys("home", "g"), key.WithHelp("home:", "⤒")),
		GotoBottom: key.NewBinding(key.WithKeys("end", "G"), key.WithHelp("end:", "⤓ follow")),
		Logs:       key.NewBinding(key.WithKeys("l"), key.WithHelp("l:", "logs")),
		Search:     key.NewBinding(key.WithKeys("/"), key.WithHelp("/:", "search")),
		CopyMode:   key.NewBinding(key.WithKeys("c"), key.WithHelp("c:", "select lines")),
		Quit:       key.NewBinding(key.WithKeys("q"), key.WithHelp("q:", "cancel run")),
		Interrupt:  key.NewBinding(key.WithKeys("ctrl+c")),
		Help:       key.NewBinding(key.WithKeys("?"), key.WithHelp("?:", "help")),
	}
}

func (k evalKeyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.Up, k.Down, k.NextPane, k.Logs, k.Search, k.CopyMode, k.Quit, k.Help}
}

func (k evalKeyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.Up, k.Down, k.NextPane},
		{k.ScrollUp, k.ScrollDown, k.GotoTop, k.GotoBottom},
		{k.Logs, k.Search, k.CopyMode},
		{k.Quit, k.Help},
	}
}

// EvalModel renders a live eval run in the same layout as the phrocs process view:
// the sidebar lists the run overview and every trial, and the output pane shows the
// selected item's summary or logs.
type EvalModel struct {
	notify    func(string)
	clipboard func(string)

	description string
	transcript  string
	stage       string
	setup       []string
	setupDone   bool
	experiments []string
	totals      map[string]int
	trials      map[string]*evalTrial
	order       map[string][]*evalTrial
	diagnostics []string
	summary     string
	started     time.Time
	stopped     time.Time
	exitCode    *int

	streamClosed    bool
	confirmCancel   bool
	cancelRequested bool
	showLogs        bool

	rows   []evalRow
	cursor int
	offset int
	focus  focusPane

	viewport viewport.Model
	atBottom bool
	shownKey string
	// content is the pane text before wrapping. continued marks the rows that
	// wrapping split off the row above, so copies can rejoin them.
	content   string
	continued []bool
	wrapWidth int

	filePath    string
	fileText    string
	fileSize    int64
	fileModTime time.Time
	fileLoading bool

	dragging  bool
	selected  bool
	selAnchor evalPoint
	selCursor evalPoint

	copyMode   bool
	copyAnchor int
	copyCursor int
	flash      string

	searchMode  bool
	query       string
	matches     []int
	matchCursor int

	keys     evalKeyMap
	help     help.Model
	spinner  spinner.Model
	showHelp bool

	width  int
	height int
	ready  bool
	isDark bool
	now    func() time.Time
}

// NewEvalModel builds the eval view. notify receives "ready" after the first
// layout and "cancel" when the user confirms that the run should stop.
func NewEvalModel(notify func(string)) EvalModel {
	h := help.New()
	h.Styles = helpStyles()
	m := EvalModel{
		notify:    notify,
		clipboard: pbcopy,
		stage:     "Starting",
		totals:    map[string]int{},
		trials:    map[string]*evalTrial{},
		order:     map[string][]*evalTrial{},
		started:   time.Now(),
		focus:     focusServices,
		atBottom:  true,
		isDark:    true,
		keys:      newEvalKeyMap(),
		help:      h,
		spinner:   spinner.New(spinner.WithSpinner(spinner.MiniDot)),
		now:       time.Now,
	}
	m.rebuildRows()
	return m
}

func (m EvalModel) Init() tea.Cmd {
	return tea.Batch(tea.RequestBackgroundColor, m.spinner.Tick, evalTick())
}

func evalTick() tea.Cmd {
	return tea.Tick(evalPollInterval, func(time.Time) tea.Msg { return evalTickMsg{} })
}

func (m EvalModel) send(command string) tea.Cmd {
	notify := m.notify
	return func() tea.Msg {
		if notify != nil {
			notify(command)
		}
		return nil
	}
}

func (m EvalModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		if !m.ready {
			m.viewport = viewport.New()
			m.viewport.FillHeight = true
			m.viewport.HighlightStyle = searchMatchStyle
			m.viewport.SelectedHighlightStyle = searchCurrentMatchStyle
			m.ready = true
			cmds = append(cmds, m.send("ready"))
		}
		m.applySize()
		m.refreshContent()

	case tea.BackgroundColorMsg:
		m.isDark = msg.IsDark()

	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)

	case evalTickMsg:
		cmds = append(cmds, evalTick())
		if cmd := m.pollFile(); cmd != nil {
			cmds = append(cmds, cmd)
		}

	case evalFileMsg:
		if msg.path == m.filePath {
			m.fileLoading = false
			if msg.changed {
				m.fileText, m.fileSize, m.fileModTime = msg.text, msg.size, msg.modTime
				m.refreshContent()
			}
		}

	case EvalEventMsg:
		m.applyEvent(EvalEvent(msg))

	case EvalStreamClosedMsg:
		m.streamClosed = true
		m.confirmCancel = false
		if m.stopped.IsZero() {
			m.stopped = m.now()
		}
		// Without a finish event the harness process is gone and the shell has
		// the terminal again, so the view must give it back now.
		if m.exitCode == nil {
			return m, tea.Quit
		}
		m.refreshContent()

	case tea.KeyPressMsg:
		return m.handleKey(msg, cmds)

	case tea.MouseClickMsg:
		m.handleClick(msg)

	case tea.MouseMotionMsg:
		if m.dragging {
			top := headerHeight + 1
			if msg.Y < top {
				m.viewport.ScrollUp(1)
			} else if msg.Y >= top+m.viewport.Height() {
				m.viewport.ScrollDown(1)
			}
			m.selCursor = m.outputPoint(msg.X, msg.Y)
		}

	case tea.MouseReleaseMsg:
		if m.dragging {
			m.dragging = false
			m.selCursor = m.outputPoint(msg.X, msg.Y)
			m.selected = m.selCursor != m.selAnchor
			if m.selected {
				cmds = append(cmds, m.copySelection())
			}
		}

	case tea.MouseWheelMsg:
		if msg.X < m.sidebarWidth() {
			switch msg.Button {
			case tea.MouseWheelDown:
				m.moveCursor(1)
			case tea.MouseWheelUp:
				m.moveCursor(-1)
			}
		} else {
			var cmd tea.Cmd
			m.viewport, cmd = m.viewport.Update(msg)
			m.atBottom = m.viewport.AtBottom()
			cmds = append(cmds, cmd)
		}
	}
	return m, tea.Batch(cmds...)
}

func (m *EvalModel) applyEvent(ev EvalEvent) {
	switch ev.Type {
	case "run":
		m.description = ev.Description
		if ev.Transcript != "" {
			m.transcript = ev.Transcript
		}
	case "setup":
		m.setup = append(m.setup, ev.Phase)
		m.stage = ev.Phase
	case "setup_done":
		m.setupDone = true
		m.stage = "Running trials"
	case "stage":
		m.stage = ev.Stage
	case "experiment":
		if _, ok := m.totals[ev.Name]; !ok {
			m.experiments = append(m.experiments, ev.Name)
		}
		m.totals[ev.Name] = ev.Total
		m.rebuildRows()
	case "trial":
		t, ok := m.trials[ev.ID]
		if !ok {
			t = &evalTrial{id: ev.ID}
			m.trials[ev.ID] = t
			if _, known := m.totals[ev.Experiment]; !known {
				m.experiments = append(m.experiments, ev.Experiment)
				m.totals[ev.Experiment] = 0
			}
			m.order[ev.Experiment] = append(m.order[ev.Experiment], t)
			defer m.rebuildRows()
		}
		t.experiment, t.name, t.index, t.phase, t.detail = ev.Experiment, ev.Name, ev.Index, ev.Phase, ev.Detail
		t.summaryPath, t.logPath = ev.SummaryPath, ev.LogPath
		t.started = unixTime(ev.Started)
		t.ended = unixTime(ev.Ended)
	case "retry":
		if t, ok := m.trials[ev.ID]; ok {
			t.retries++
			t.detail = ev.Detail
		}
	case "message":
		added := false
		for _, line := range strings.Split(ev.Text, "\n") {
			if hasAnyPrefix(line, evalDiagnosticPrefixes) {
				m.diagnostics = append(m.diagnostics, line)
				added = true
			}
		}
		if over := len(m.diagnostics) - evalMaxDiagnostics; over > 0 {
			m.diagnostics = m.diagnostics[over:]
		}
		// Other messages change nothing on screen, so skip the rebuild.
		if !added || m.selectedTrial() != nil || m.showLogs {
			return
		}
	case "finish":
		code := 1
		if ev.ExitCode != nil {
			code = *ev.ExitCode
		}
		m.exitCode = &code
		m.stopped = m.now()
		m.summary = ev.Text
		m.confirmCancel = false
		if code == 0 {
			m.stage = "Results ready. Press q to close."
		} else {
			m.stage = "Run stopped. Select Run for details. Press q to close."
		}
	}
	m.refreshContent()
}

func unixTime(seconds float64) time.Time {
	if seconds <= 0 {
		return time.Time{}
	}
	return time.UnixMilli(int64(seconds * 1000))
}

func hasAnyPrefix(s string, prefixes []string) bool {
	for _, p := range prefixes {
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}

func (m *EvalModel) rebuildRows() {
	var selected *evalTrial
	if m.cursor < len(m.rows) {
		selected = m.rows[m.cursor].trial
	}
	rows := []evalRow{{}}
	for _, name := range m.experiments {
		trials := m.order[name]
		if len(trials) == 0 {
			continue
		}
		rows = append(rows, evalRow{header: name})
		for _, t := range trials {
			rows = append(rows, evalRow{trial: t})
		}
	}
	m.rows = rows
	m.cursor = 0
	for i, r := range rows {
		if r.trial != nil && r.trial == selected {
			m.cursor = i
		}
	}
	m.ensureCursorVisible()
}

func (m EvalModel) selectedTrial() *evalTrial {
	if m.cursor < len(m.rows) {
		return m.rows[m.cursor].trial
	}
	return nil
}

func (m EvalModel) finished() bool { return m.exitCode != nil || m.streamClosed }

// HarnessLost reports that the harness closed the stream without a final result.
func (m EvalModel) HarnessLost() bool { return m.streamClosed && m.exitCode == nil }

func (m EvalModel) handleKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (tea.Model, tea.Cmd) {
	m.flash = ""
	m.selected = false
	// Ctrl-C must cancel from every mode, because the view ignores SIGINT and
	// leaves cancellation to this key.
	if key.Matches(msg, m.keys.Interrupt) {
		if m.finished() {
			return m, tea.Quit
		}
		m.confirmCancel = false
		if !m.cancelRequested {
			m.cancelRequested = true
			cmds = append(cmds, m.send("cancel"))
		}
		return m, tea.Batch(cmds...)
	}
	if m.copyMode {
		cmds = append(cmds, m.handleCopyKey(msg))
		return m, tea.Batch(cmds...)
	}
	if m.searchMode {
		m.handleSearchKey(msg)
		return m, tea.Batch(cmds...)
	}
	if m.confirmCancel {
		switch msg.String() {
		case "y", "Y":
			m.confirmCancel = false
			m.cancelRequested = true
			cmds = append(cmds, m.send("cancel"))
		case "n", "N", "esc", "q":
			m.confirmCancel = false
		}
		return m, tea.Batch(cmds...)
	}

	switch {
	case key.Matches(msg, m.keys.Quit):
		if m.finished() {
			return m, tea.Quit
		}
		if !m.cancelRequested {
			m.confirmCancel = true
		}
	case msg.String() == "esc":
		if m.query != "" {
			m.clearSearch()
		}
	case key.Matches(msg, m.keys.Up):
		if m.focus == focusOutput {
			m.viewport.ScrollUp(1)
			m.atBottom = m.viewport.AtBottom()
		} else {
			m.moveCursor(-1)
		}
	case key.Matches(msg, m.keys.Down):
		if m.focus == focusOutput {
			m.viewport.ScrollDown(1)
			m.atBottom = m.viewport.AtBottom()
		} else {
			m.moveCursor(1)
		}
	case msg.String() == "enter":
		if m.focus == focusServices {
			m.focus = focusOutput
		} else if len(m.matches) > 0 {
			m.matchCursor = (m.matchCursor + 1) % len(m.matches)
			m.applySearch(true)
		}
	case key.Matches(msg, m.keys.NextPane):
		if m.focus == focusServices {
			m.focus = focusOutput
		} else {
			m.focus = focusServices
		}
	case key.Matches(msg, m.keys.ScrollUp):
		m.viewport.PageUp()
		m.atBottom = m.viewport.AtBottom()
	case key.Matches(msg, m.keys.ScrollDown):
		m.viewport.PageDown()
		m.atBottom = m.viewport.AtBottom()
	case key.Matches(msg, m.keys.GotoTop):
		m.viewport.GotoTop()
		m.atBottom = false
	case key.Matches(msg, m.keys.GotoBottom):
		m.viewport.GotoBottom()
		m.atBottom = true
	case key.Matches(msg, m.keys.Logs):
		m.showLogs = !m.showLogs
		m.refreshContent()
	case key.Matches(msg, m.keys.CopyMode):
		m.copyMode = true
		m.copyAnchor = -1
		m.copyCursor = m.firstVisibleLine()
		m.applySize()
		m.applyCopyStyle()
	case key.Matches(msg, m.keys.Search):
		m.searchMode = true
		m.query = ""
		m.applySearch(false)
	case key.Matches(msg, m.keys.Help):
		m.showHelp = !m.showHelp
		m.applySize()
	}
	return m, tea.Batch(cmds...)
}

func (m *EvalModel) handleSearchKey(msg tea.KeyPressMsg) {
	switch s := msg.String(); s {
	case "esc":
		m.searchMode = false
		m.clearSearch()
	case "enter":
		m.searchMode = false
	case "down":
		if len(m.matches) > 0 {
			m.matchCursor = (m.matchCursor + 1) % len(m.matches)
			m.applySearch(true)
		}
	case "up":
		if len(m.matches) > 0 {
			m.matchCursor = (m.matchCursor - 1 + len(m.matches)) % len(m.matches)
			m.applySearch(true)
		}
	case "backspace":
		if runes := []rune(m.query); len(runes) > 0 {
			m.query = string(runes[:len(runes)-1])
			m.matchCursor = 0
			m.applySearch(true)
		}
	default:
		ch := msg.Text
		if s == "space" {
			ch = " "
		}
		if ch != "" {
			m.query += ch
			m.matchCursor = 0
			m.applySearch(true)
		}
	}
	m.applySize()
}

func (m *EvalModel) handleCopyKey(msg tea.KeyPressMsg) tea.Cmd {
	last := len(m.contentLines()) - 1
	switch {
	case msg.String() == "esc", key.Matches(msg, m.keys.Quit):
		m.exitCopyMode()
	case key.Matches(msg, m.keys.CopyMode), msg.String() == "enter":
		if m.copyAnchor < 0 {
			m.copyAnchor = m.copyCursor
		} else {
			lo, hi := min(m.copyAnchor, m.copyCursor), max(m.copyAnchor, m.copyCursor)
			m.exitCopyMode()
			return m.copyLines(lo, hi)
		}
	case key.Matches(msg, m.keys.Down):
		m.copyCursor = min(m.copyCursor+1, last)
	case key.Matches(msg, m.keys.Up):
		m.copyCursor = max(m.copyCursor-1, 0)
	case key.Matches(msg, m.keys.ScrollDown):
		m.copyCursor = min(m.copyCursor+m.viewport.Height(), last)
	case key.Matches(msg, m.keys.ScrollUp):
		m.copyCursor = max(m.copyCursor-m.viewport.Height(), 0)
	case key.Matches(msg, m.keys.GotoTop):
		m.copyCursor = 0
	case key.Matches(msg, m.keys.GotoBottom):
		m.copyCursor = last
	default:
		return nil
	}
	if m.copyMode {
		m.applyCopyStyle()
		m.ensureLineVisible(m.copyCursor)
	}
	return nil
}

func (m *EvalModel) exitCopyMode() {
	m.copyMode = false
	m.viewport.StyleLineFunc = nil
	m.applySize()
	m.refreshContent()
}

func (m *EvalModel) applyCopyStyle() {
	cursor, anchor := m.copyCursor, m.copyAnchor
	lo, hi := min(anchor, cursor), max(anchor, cursor)
	selected := lipgloss.NewStyle().Background(selectionBg(m.isDark))
	m.viewport.StyleLineFunc = func(i int) lipgloss.Style {
		switch {
		case i == cursor:
			return copyModeStyle
		case anchor >= 0 && i >= lo && i <= hi:
			return selected
		}
		return lipgloss.NewStyle()
	}
}

func (m EvalModel) contentLines() []string {
	return strings.Split(m.viewport.GetContent(), "\n")
}

// copyLines puts plain text on the clipboard through OSC 52 and, on macOS,
// through pbcopy, because Terminal.app ignores OSC 52.
func (m *EvalModel) copyLines(lo, hi int) tea.Cmd {
	lines := m.contentLines()
	hi = min(hi, len(lines)-1)
	if lo > hi {
		return nil
	}
	var plain []string
	for i, line := range lines[lo : hi+1] {
		text := ansi.Strip(line)
		if i > 0 && lo+i < len(m.continued) && m.continued[lo+i] {
			plain[len(plain)-1] += text
			continue
		}
		plain = append(plain, text)
	}
	return m.copyText(strings.Join(plain, "\n"), len(plain))
}

func (m *EvalModel) copyText(text string, lines int) tea.Cmd {
	if strings.TrimSpace(text) == "" {
		return nil
	}
	if lines == 1 {
		m.flash = "Copied the selection to the clipboard"
	} else {
		m.flash = fmt.Sprintf("Copied %d lines to the clipboard", lines)
	}
	clipboard := m.clipboard
	return tea.Batch(tea.SetClipboard(text), func() tea.Msg {
		if clipboard != nil {
			clipboard(text)
		}
		return nil
	})
}

func pbcopy(text string) {
	if path, err := exec.LookPath("pbcopy"); err == nil {
		cmd := exec.Command(path)
		cmd.Stdin = strings.NewReader(text)
		_ = cmd.Run()
	}
}

// setContent wraps the pane text once per change. The viewport's own soft wrap
// rescans a line for every row it cuts, so one large log line made every frame
// slow enough to block keys.
func (m *EvalModel) setContent(content string) {
	m.content = content
	m.wrapWidth = max(m.viewport.Width(), 1)
	var rows []string
	m.continued = m.continued[:0]
	for _, line := range strings.Split(content, "\n") {
		for i, row := range strings.Split(ansi.Hardwrap(line, m.wrapWidth, true), "\n") {
			rows = append(rows, row)
			m.continued = append(m.continued, i > 0)
		}
	}
	m.viewport.SetContentLines(rows)
}

func (m EvalModel) firstVisibleLine() int {
	return m.viewport.YOffset()
}

func (m *EvalModel) ensureLineVisible(row int) {
	if offset := m.viewport.YOffset(); row < offset {
		m.viewport.SetYOffset(row)
	} else if row >= offset+m.viewport.Height() {
		m.viewport.SetYOffset(row - m.viewport.Height() + 1)
	}
	m.atBottom = m.viewport.AtBottom()
}

func (m EvalModel) outputPoint(x, y int) evalPoint {
	row := min(max(y-headerHeight-1, 0), max(m.viewport.Height()-1, 0))
	col := min(max(x-m.sidebarWidth()-1, 0), max(m.viewport.Width()-1, 0))
	return evalPoint{row: m.viewport.YOffset() + row, col: col}
}

func (m EvalModel) wrappedRows() []wrappedRow {
	lines := m.contentLines()
	rows := make([]wrappedRow, len(lines))
	for i, line := range lines {
		rows[i] = wrappedRow{text: ansi.Strip(line), continued: i < len(m.continued) && m.continued[i]}
	}
	return rows
}

func (m EvalModel) selectionBounds() (evalPoint, evalPoint) {
	if m.selCursor.before(m.selAnchor) {
		return m.selCursor, m.selAnchor
	}
	return m.selAnchor, m.selCursor
}

func (m *EvalModel) copySelection() tea.Cmd {
	lo, hi := m.selectionBounds()
	rows := m.wrappedRows()
	var b strings.Builder
	for r := lo.row; r <= hi.row && r < len(rows); r++ {
		start, end := 0, ansi.StringWidth(rows[r].text)
		if r == lo.row {
			start = lo.col
		}
		if r == hi.row {
			end = min(end, hi.col+1)
		}
		if r > lo.row && !rows[r].continued {
			b.WriteByte('\n')
		}
		if start < end {
			b.WriteString(ansi.Cut(rows[r].text, start, end))
		}
	}
	lines := strings.Split(b.String(), "\n")
	for i := range lines {
		lines[i] = strings.TrimRight(lines[i], " ")
	}
	return m.copyText(strings.Join(lines, "\n"), len(lines))
}

func (m *EvalModel) clearSearch() {
	m.query = ""
	m.matches = nil
	m.matchCursor = 0
	m.viewport.StyleLineFunc = nil
}

func (m *EvalModel) moveCursor(dir int) {
	for i := m.cursor + dir; i >= 0 && i < len(m.rows); i += dir {
		if m.rows[i].selectable() {
			m.cursor = i
			m.ensureCursorVisible()
			m.refreshContent()
			return
		}
	}
}

func (m *EvalModel) handleClick(msg tea.MouseClickMsg) {
	if msg.Button != tea.MouseLeft {
		return
	}
	m.selected = false
	if msg.X >= m.sidebarWidth() {
		m.focus = focusOutput
		// Stop following so new output cannot scroll the text under the pointer.
		m.atBottom = false
		m.dragging = true
		m.selAnchor = m.outputPoint(msg.X, msg.Y)
		m.selCursor = m.selAnchor
		return
	}
	m.focus = focusServices
	row := m.offset + msg.Y - headerHeight - 1
	if m.offset > 0 {
		row--
	}
	if row >= 0 && row < len(m.rows) && m.rows[row].selectable() {
		m.cursor = row
		m.refreshContent()
	}
}

func (m EvalModel) sidebarWidth() int {
	return min(max(m.width*35/100, 28), 56)
}

func (m EvalModel) bodyHeight() int {
	borders := 2
	if m.copyMode {
		borders = 0
	}
	return max(m.height-headerHeight-lipgloss.Height(m.renderFooter())-borders, 1)
}

func (m *EvalModel) applySize() {
	if !m.ready {
		return
	}
	if m.copyMode {
		m.viewport.SetWidth(max(m.width, 1))
	} else {
		m.viewport.SetWidth(max(m.width-m.sidebarWidth()-2, 1))
	}
	m.viewport.SetHeight(m.bodyHeight())
	if m.viewport.Width() != m.wrapWidth && m.content != "" {
		m.setContent(m.content)
	}
	m.ensureCursorVisible()
}

func (m *EvalModel) ensureCursorVisible() {
	h := m.bodyHeight()
	if len(m.rows) <= h {
		m.offset = 0
		return
	}
	visible := max(h-2, 1)
	if m.cursor < m.offset {
		m.offset = m.cursor
	}
	if m.cursor >= m.offset+visible {
		m.offset = m.cursor - visible + 1
	}
	m.offset = min(max(m.offset, 0), len(m.rows)-visible)
}

func (m EvalModel) currentFile() string {
	if t := m.selectedTrial(); t != nil {
		if m.showLogs {
			return t.logPath
		}
		return t.summaryPath
	}
	if m.showLogs {
		return m.transcript
	}
	return ""
}

func (m *EvalModel) pollFile() tea.Cmd {
	path := m.currentFile()
	if path == "" || m.fileLoading {
		return nil
	}
	if path != m.filePath {
		m.filePath, m.fileText, m.fileSize, m.fileModTime = path, "", -1, time.Time{}
	}
	m.fileLoading = true
	size, modTime := m.fileSize, m.fileModTime
	return func() tea.Msg { return readEvalFile(path, size, modTime) }
}

func readEvalFile(path string, lastSize int64, lastMod time.Time) evalFileMsg {
	missing := evalFileMsg{path: path, size: -1, changed: lastSize != -1}
	info, err := os.Stat(path)
	if err != nil {
		return missing
	}
	if info.Size() == lastSize && info.ModTime().Equal(lastMod) {
		return evalFileMsg{path: path}
	}
	f, err := os.Open(path)
	if err != nil {
		return missing
	}
	defer func() { _ = f.Close() }()
	start := max(info.Size()-evalTailBytes, 0)
	if _, err := f.Seek(start, io.SeekStart); err != nil {
		return missing
	}
	data, err := io.ReadAll(f)
	if err != nil {
		return missing
	}
	text := strings.ToValidUTF8(string(data), "�")
	if start > 0 {
		if i := strings.IndexByte(text, '\n'); i >= 0 {
			text = text[i+1:]
		}
		text = "Showing recent output. Open the file for earlier lines.\n\n" + text
	}
	return evalFileMsg{path: path, text: strings.TrimRight(text, "\n"), size: info.Size(), modTime: info.ModTime(), changed: true}
}

// refreshContent rebuilds the output pane from the current state. It runs only
// when an event, a file read, or a key changes what the pane shows.
func (m *EvalModel) refreshContent() {
	// Copy mode keeps the pane still, so new output cannot move the selection.
	if !m.ready || m.copyMode {
		return
	}
	selectedID := ""
	if t := m.selectedTrial(); t != nil {
		selectedID = t.id
	}
	shownKey := fmt.Sprintf("%s|%v", selectedID, m.showLogs)
	switched := shownKey != m.shownKey
	m.shownKey = shownKey
	path := m.currentFile()
	if path != m.filePath {
		m.filePath, m.fileText, m.fileSize, m.fileModTime, m.fileLoading = path, "", -1, time.Time{}, false
	}

	var content string
	if t := m.selectedTrial(); t != nil {
		content = m.renderTrial(t)
	} else if m.showLogs {
		content = m.renderFile(m.transcript, "The run transcript is not available yet.")
	} else {
		content = m.renderOverview()
	}
	m.setContent(content)
	if m.query != "" {
		m.applySearch(false)
	}
	if switched {
		m.selected = false
		m.atBottom = m.showLogs
		if m.atBottom {
			m.viewport.GotoBottom()
		} else {
			m.viewport.GotoTop()
		}
	} else if m.atBottom {
		m.viewport.GotoBottom()
	}
}

func (m EvalModel) renderFile(path, missing string) string {
	if path == "" {
		return missing
	}
	text := m.fileText
	if path != m.filePath || m.fileSize < 0 {
		text = missing
	}
	return lipgloss.NewStyle().Foreground(colorBrightBlack).Render(path) + "\n\n" + text
}

var evalTitleStyle = lipgloss.NewStyle().Bold(true).Foreground(colorYellow)

func (m EvalModel) renderOverview() string {
	var b strings.Builder
	if m.description != "" {
		b.WriteString(m.description + "\n")
	}
	b.WriteString(m.stage + "\n\n")

	b.WriteString(evalTitleStyle.Render("Setup") + "\n")
	for i, phase := range m.setup {
		done := m.setupDone || i < len(m.setup)-1
		icon, c := iconCharRunning, colorGreen
		if done {
			icon, c = iconCharDone, nil
		} else if m.finished() {
			icon, c = iconCharCrashed, colorRed
		}
		b.WriteString("  " + lipgloss.NewStyle().Foreground(c).Render(icon) + " " + phase + "\n")
	}

	b.WriteString("\n" + evalTitleStyle.Render("Trials") + "\n")
	counts := map[string]int{}
	for _, t := range m.trials {
		counts[t.phase]++
	}
	var parts []string
	for _, phase := range []string{"queued", "setup", "agent", "cleanup", "logs", "scoring", "done", "error", "timeout", "canceled"} {
		if counts[phase] > 0 {
			parts = append(parts, fmt.Sprintf("%s %d", phase, counts[phase]))
		}
	}
	if len(parts) == 0 {
		parts = append(parts, "No trials have started yet.")
	}
	b.WriteString("  " + strings.Join(parts, " · ") + "\n")
	for _, name := range m.experiments {
		finished := 0
		for _, t := range m.order[name] {
			if t.finished() {
				finished++
			}
		}
		fmt.Fprintf(&b, "  %s  %d/%d\n", name, finished, m.totals[name])
	}

	if len(m.diagnostics) > 0 {
		b.WriteString("\n" + evalTitleStyle.Render("Warnings and errors") + "\n")
		b.WriteString(strings.Join(m.diagnostics, "\n") + "\n")
	}
	if m.summary != "" {
		b.WriteString("\n" + strings.TrimRight(m.summary, "\n") + "\n")
	}
	if m.transcript != "" {
		b.WriteString("\n" + lipgloss.NewStyle().Foreground(colorBrightBlack).Render("Transcript: "+m.transcript) + "\n")
	}
	return strings.TrimRight(b.String(), "\n")
}

func (m EvalModel) renderTrial(t *evalTrial) string {
	var b strings.Builder
	b.WriteString(evalTitleStyle.Render(fmt.Sprintf("%s :: %s [trial %d]", t.experiment, t.name, t.index+1)) + "\n")
	fmt.Fprintf(&b, "Phase: %s | Setup retries: %d\n", t.phase, t.retries)
	failed := t.phase == "error" || t.phase == "timeout"
	if t.detail != "" && failed {
		b.WriteString("\n" + lipgloss.NewStyle().Bold(true).Foreground(colorRed).Render("Error") + "\n")
		b.WriteString(t.detail + "\n")
	} else if t.detail != "" {
		b.WriteString(t.detail + "\n")
	}
	b.WriteString("\n")
	missing := "The summary appears when the trial finishes. Press l for the agent log."
	if failed {
		missing = "No summary for this trial. Select Run and press l for the full transcript."
	}
	if m.showLogs {
		missing = "The agent log appears when the trial finishes. Select Run and press l for live logs."
	}
	path := t.summaryPath
	if m.showLogs {
		path = t.logPath
	}
	b.WriteString(m.renderFile(path, missing))
	return b.String()
}

func (m *EvalModel) applySearch(jump bool) {
	if m.query == "" {
		m.matches = nil
		m.viewport.StyleLineFunc = nil
		return
	}
	tokens := parseMatchTokens(m.query)
	lines := strings.Split(m.viewport.GetContent(), "\n")
	m.matches = m.matches[:0]
	for i, line := range lines {
		if lineMatchesTokens(line, tokens) {
			m.matches = append(m.matches, i)
		}
	}
	if len(m.matches) == 0 {
		m.matchCursor = 0
		m.viewport.StyleLineFunc = nil
		return
	}
	m.matchCursor = min(m.matchCursor, len(m.matches)-1)
	matchSet := make(map[int]bool, len(m.matches))
	for _, i := range m.matches {
		matchSet[i] = true
	}
	current := m.matches[m.matchCursor]
	m.viewport.StyleLineFunc = func(i int) lipgloss.Style {
		if i == current {
			return searchCurrentMatchStyle
		}
		if matchSet[i] {
			return searchMatchStyle
		}
		return lipgloss.NewStyle()
	}
	if jump {
		m.viewport.SetYOffset(max(current-m.viewport.Height()/2, 0))
		m.atBottom = m.viewport.AtBottom()
	}
}

func (m EvalModel) View() tea.View {
	if !m.ready {
		v := tea.NewView("\n  Initialising...\n")
		v.AltScreen = true
		return v
	}
	v := tea.NewView("")
	v.AltScreen = true
	if m.copyMode {
		// Without mouse capture, the terminal's own drag selection works too.
		v.SetContent(lipgloss.JoinVertical(lipgloss.Left, m.renderHeader(), m.viewport.View(), m.renderFooter()))
		v.MouseMode = tea.MouseModeNone
		return v
	}
	body := lipgloss.JoinHorizontal(lipgloss.Top, m.renderSidebar(), m.renderOutput())
	v.SetContent(lipgloss.JoinVertical(lipgloss.Left, m.renderHeader(), body, m.renderFooter()))
	v.MouseMode = tea.MouseModeCellMotion
	return v
}

func (m EvalModel) counts() (finished, running, failed, total int) {
	for _, t := range m.trials {
		switch {
		case t.phase == "error" || t.phase == "timeout":
			failed++
			finished++
		case t.finished():
			finished++
		case t.phase != "queued":
			running++
		}
	}
	for _, n := range m.totals {
		total += n
	}
	return
}

func (m EvalModel) runStatus() string {
	switch {
	case m.exitCode == nil && m.streamClosed:
		return "stopped"
	case m.exitCode == nil && m.cancelRequested:
		return "canceling"
	case m.exitCode == nil:
		return "running"
	case *m.exitCode == 0:
		return "PASS"
	case *m.exitCode == 130:
		return "interrupted"
	default:
		return "FAIL"
	}
}

// clock stops at the end of the run, so unfinished trials stop counting too.
func (m EvalModel) clock() time.Time {
	if !m.stopped.IsZero() {
		return m.stopped
	}
	return m.now()
}

func (m EvalModel) runElapsed() time.Duration {
	return m.clock().Sub(m.started)
}

func (m EvalModel) renderHeader() string {
	brand := headerBrandStyle.Render("evals")
	finished, running, failed, total := m.counts()
	meta := []string{m.runStatus(), fmt.Sprintf("%d/%d finished", finished, total)}
	if running > 0 {
		meta = append(meta, fmt.Sprintf("%d running", running))
	}
	if failed > 0 {
		meta = append(meta, fmt.Sprintf("%d failed", failed))
	}
	meta = append(meta, formatDuration(m.runElapsed()))
	right := headerMetaStyle.Render(strings.Join(meta, " • "))
	spacerW := max(m.width-lipgloss.Width(stripesStyle)-lipgloss.Width(brand)-lipgloss.Width(right), 0)
	return lipgloss.JoinHorizontal(lipgloss.Top, stripesStyle, brand, strings.Repeat(" ", spacerW), right)
}

func (m EvalModel) trialIcon(t *evalTrial) (string, color.Color) {
	switch t.phase {
	case "queued":
		return ansi.Strip(m.spinner.View()), colorYellow
	case "done":
		return iconCharDone, nil
	case "error", "timeout":
		return iconCharCrashed, colorRed
	case "canceled":
		return iconCharStopped, nil
	default:
		return iconCharRunning, colorGreen
	}
}

func (m EvalModel) renderSidebar() string {
	h := m.bodyHeight()
	innerW := m.sidebarWidth() - 2
	now := m.clock()

	canUp := m.offset > 0
	visible := h
	if len(m.rows) > h {
		visible = max(h-2, 1)
	}
	end := min(len(m.rows), m.offset+visible)
	canDown := end < len(m.rows)

	var rows []string
	if len(m.rows) > h {
		arrow := ""
		if canUp {
			arrow = "▲"
		}
		rows = append(rows, scrollArrowStyle.Width(innerW).Render(arrow))
	}
	for i := m.offset; i < end; i++ {
		r := m.rows[i]
		if r.header != "" {
			rows = append(rows, groupHeaderStyle.Width(innerW).Render(truncate(r.header, innerW-1)))
			continue
		}
		var icon, label, suffix string
		var iconColor color.Color
		if r.trial == nil {
			icon, iconColor, label = m.runIcon(), m.runIconColor(), "Run"
			suffix = formatDuration(m.runElapsed())
		} else {
			t := r.trial
			icon, iconColor = m.trialIcon(t)
			label = t.name
			if m.multiTrial(t.experiment) {
				label = fmt.Sprintf("%s #%d", t.name, t.index+1)
			}
			end := t.ended
			if end.IsZero() {
				end = now
			}
			if !t.started.IsZero() {
				suffix = formatDuration(end.Sub(t.started))
			}
		}
		nameW := max(innerW-3, 0)
		label = truncate(label, max(nameW-len(suffix)-1, 1))
		gap := max(nameW-lipgloss.Width(label)-len(suffix), 1)
		row := sidebarRow{
			icon:      icon,
			name:      label + strings.Repeat(" ", gap) + suffix,
			iconColor: iconColor,
			selected:  i == m.cursor,
			innerW:    innerW,
			isDark:    m.isDark,
		}
		rows = append(rows, renderSidebarRow(row))
	}
	if len(m.rows) > h {
		arrow := ""
		if canDown {
			arrow = "▼"
		}
		rows = append(rows, scrollArrowStyle.Width(innerW).Render(arrow))
	}
	for len(rows) < h {
		rows = append(rows, procInactiveStyle.Width(innerW).Render(""))
	}
	return borderFor(m.isDark, m.focus == focusServices).Render(strings.Join(rows, "\n"))
}

func (m EvalModel) multiTrial(experiment string) bool {
	for _, t := range m.order[experiment] {
		if t.index > 0 {
			return true
		}
	}
	return false
}

func (m EvalModel) runIcon() string {
	switch m.runStatus() {
	case "running", "canceling":
		return iconCharRunning
	case "PASS":
		return iconCharDone
	case "interrupted":
		return iconCharStopped
	default:
		return iconCharCrashed
	}
}

func (m EvalModel) runIconColor() color.Color {
	switch m.runStatus() {
	case "running":
		return colorGreen
	case "canceling":
		return colorYellow
	case "PASS", "interrupted":
		return nil
	default:
		return colorRed
	}
}

func (m EvalModel) renderOutput() string {
	lines := strings.Split(m.viewport.View(), "\n")
	if m.dragging || m.selected {
		lo, hi := m.selectionBounds()
		for i, line := range lines {
			row := m.viewport.YOffset() + i
			if row < lo.row || row > hi.row {
				continue
			}
			start, end := 0, m.viewport.Width()
			if row == lo.row {
				start = lo.col
			}
			if row == hi.row {
				end = hi.col + 1
			}
			w := ansi.StringWidth(line)
			lines[i] = ansi.Cut(line, 0, start) + copyModeStyle.Render(ansi.Strip(ansi.Cut(line, start, end))) + ansi.Cut(line, end, w)
		}
	}
	if !m.viewport.AtBottom() && len(lines) > 0 {
		indicator := scrollIndicatorStyle.Render("end: follow")
		if w, iw := lipgloss.Width(lines[0]), lipgloss.Width(indicator); w >= iw {
			lines[0] = ansi.Truncate(lines[0], w-iw, "") + indicator
		}
	}
	return borderFor(m.isDark, m.focus == focusOutput).Render(strings.Join(lines, "\n"))
}

func (m EvalModel) renderFooter() string {
	w := max(m.width-2, 1)
	prompt := func(c color.Color, text string) string {
		return footerStyle.Width(w).Render(lipgloss.NewStyle().Foreground(c).Render(text))
	}
	switch {
	case m.copyMode && m.copyAnchor < 0:
		return prompt(colorBlue, fmt.Sprintf("-- COPY MODE --  line %d  ↑/↓: move  c: mark start  esc: cancel  (mouse drag also selects)", m.copyCursor+1))
	case m.copyMode:
		lo, hi := min(m.copyAnchor, m.copyCursor)+1, max(m.copyAnchor, m.copyCursor)+1
		return prompt(colorBlue, fmt.Sprintf("-- COPY MODE --  lines %d–%d  ↑/↓: extend  c: copy  esc: cancel", lo, hi))
	case m.flash != "":
		return prompt(colorGreen, m.flash)
	case m.searchMode:
		info := ""
		if m.query != "" {
			if len(m.matches) == 0 {
				info = "  [no matches]"
			} else {
				info = fmt.Sprintf("  [%d/%d]", m.matchCursor+1, len(m.matches))
			}
		}
		return prompt(colorYellow, fmt.Sprintf("/ %s▌%s  ↑/↓: prev/next  ↵: done  esc: clear", m.query, info))
	case m.confirmCancel:
		return prompt(colorYellow, "Cancel this run and clean up?  y: yes  n: continue")
	case m.cancelRequested && !m.finished():
		return prompt(colorYellow, "Cancel requested. Waiting for cleanup.")
	}
	keys := m.keys
	if m.finished() {
		keys.Quit.SetHelp("q:", "close")
	}
	if m.showLogs {
		keys.Logs.SetHelp("l:", "summary")
	}
	var content string
	if m.showHelp {
		content = m.help.FullHelpView(keys.FullHelp())
	} else {
		content = m.help.ShortHelpView(keys.ShortHelp())
	}
	if m.query != "" {
		content = lipgloss.NewStyle().Foreground(colorYellow).Render(
			fmt.Sprintf("search: %q  [%d matches]  ↵: next  esc: clear", m.query, len(m.matches)),
		) + "\n" + content
	}
	return footerStyle.Width(w).Render(content)
}
