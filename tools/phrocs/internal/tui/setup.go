package tui

import (
	"bytes"
	"fmt"
	"os/exec"
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
)

// Result of async hogli dev:list-units call.
type listUnitsMsg struct {
	units    []string
	intents  []string
	excluded map[string]bool
	err      error
}

// Result of async hogli dev:apply call.
type devApplyMsg struct {
	configPath string
	cfg        *config.Config
	err        error
}

func (m Model) enterSetupMode() Model {
	intentMap, err := config.LoadIntentMap()
	if err != nil {
		m.setupError = fmt.Sprintf("load intent-map: %v", err)
		m.setupMode = true
		return m
	}

	// Pre-check intents from the current config's _posthog section
	checked := make(map[string]bool)
	if m.configPath != "" {
		if phCfg, err := config.LoadPosthogConfig(m.configPath); err == nil && phCfg != nil {
			for _, intent := range phCfg.Intents {
				checked[intent] = true
			}
		}
	}

	m.setupMode = true
	m.setupStep = 1
	m.setupEntries = intentMap.Intents
	m.setupCursor = 0
	m.setupOffset = 0
	m.setupChecked = checked
	m.setupError = ""

	return m
}

func (m Model) handleSetupKey(msg tea.KeyPressMsg, cmds []tea.Cmd) (Model, []tea.Cmd, bool) {
	switch {
	case msg.Code == tea.KeyEscape, key.Matches(msg, m.keys.Quit):
		m.setupMode = false
		m.setupError = ""
		m.focusedPane = focusServices
		m = m.applySize()
		m.dbg("setup mode: cancel")

	case msg.Code == tea.KeyEnter:
		if m.setupStep == 1 {
			m.dbg("setup mode: advance to step 2")
			cmd := m.startListUnits()
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
		} else {
			m.dbg("setup mode: apply")
			cmd := m.startDevApply()
			if cmd != nil {
				cmds = append(cmds, cmd)
			}
		}

	case key.Matches(msg, m.keys.NextProc), key.Matches(msg, m.keys.KeyDown):
		if m.setupCursor < len(m.setupEntries)-1 {
			m.setupCursor++
			m.ensureSetupCursorVisible()
		}

	case key.Matches(msg, m.keys.PrevProc), key.Matches(msg, m.keys.KeyUp):
		if m.setupCursor > 0 {
			m.setupCursor--
			m.ensureSetupCursorVisible()
		}

	case msg.Code == tea.KeySpace:
		if m.setupCursor < len(m.setupEntries) {
			name := m.setupEntries[m.setupCursor].Name
			m.setupChecked[name] = !m.setupChecked[name]
			m.dbg("setup: toggle %s = %v", name, m.setupChecked[name])
		}

	case key.Matches(msg, m.keys.GotoTop):
		m.setupCursor = 0
		m.ensureSetupCursorVisible()

	case key.Matches(msg, m.keys.GotoBottom):
		if len(m.setupEntries) > 0 {
			m.setupCursor = len(m.setupEntries) - 1
		}
		m.ensureSetupCursorVisible()

	default:
		return m, cmds, false
	}
	return m, cmds, true
}

// startListUnits kicks off an async hogli dev:list-units call.
// Returns nil if validation fails (error set on m.setupError).
func (m *Model) startListUnits() tea.Cmd {
	var selected []string
	for _, entry := range m.setupEntries {
		if m.setupChecked[entry.Name] {
			selected = append(selected, entry.Name)
		}
	}
	if len(selected) == 0 {
		m.setupError = "error: select at least one product"
		return nil
	}

	// Read previously excluded units before the async call
	excluded := make(map[string]bool)
	if m.configPath != "" {
		if phCfg, err := config.LoadPosthogConfig(m.configPath); err == nil && phCfg != nil {
			for _, name := range phCfg.ExcludeUnits {
				excluded[name] = true
			}
		}
	}

	m.setupError = "resolving intents…"
	return func() tea.Msg {
		units, err := runHogliListUnits(selected)
		return listUnitsMsg{units: units, intents: selected, excluded: excluded, err: err}
	}
}

// handleListUnitsMsg processes the result of an async dev:list-units call.
func (m *Model) handleListUnitsMsg(msg listUnitsMsg) {
	if msg.err != nil {
		m.setupError = "error: " + msg.err.Error()
		return
	}

	entries := make([]config.Intent, 0, len(msg.units))
	checked := make(map[string]bool)
	for _, name := range msg.units {
		entries = append(entries, config.Intent{Name: name})
		checked[name] = !msg.excluded[name]
	}

	m.setupIntents = msg.intents
	m.setupStep = 2
	m.setupEntries = entries
	m.setupCursor = 0
	m.setupOffset = 0
	m.setupChecked = checked
	m.setupError = ""
}

// startDevApply kicks off an async hogli dev:apply call.
// Returns nil if there's nothing to do.
func (m *Model) startDevApply() tea.Cmd {
	var excludeUnits []string
	for _, entry := range m.setupEntries {
		if !m.setupChecked[entry.Name] {
			m.dbg("setup: excluding process %s", entry.Name)
			excludeUnits = append(excludeUnits, entry.Name)
		}
	}

	intents := m.setupIntents
	m.setupError = "applying config…"
	return func() tea.Msg {
		configPath, err := runHogliDevApply(intents, excludeUnits)
		if err != nil {
			return devApplyMsg{err: err}
		}
		cfg, err := config.Load(configPath)
		return devApplyMsg{configPath: configPath, cfg: cfg, err: err}
	}
}

// handleDevApplyMsg processes the result of an async dev:apply call.
func (m *Model) handleDevApplyMsg(msg devApplyMsg) {
	if msg.err != nil {
		m.setupError = "error: " + msg.err.Error()
		return
	}

	newCfg := msg.cfg

	// Snapshot current process names before applying changes
	oldNames := make(map[string]bool)
	for _, p := range m.mgr.Procs() {
		oldNames[p.Name] = true
	}

	newNames := make(map[string]bool)
	for name := range newCfg.Procs {
		newNames[name] = true
	}

	for name := range oldNames {
		if !newNames[name] {
			m.dbg("setup: removing process %s", name)
			m.mgr.Remove(name)
		}
	}

	// Add new processes and start them asynchronously.
	// p.Start calls send() synchronously, which writes to bubbletea's
	// unbuffered msgs channel — doing this from inside Update deadlocks.
	send := m.mgr.Send()
	for name := range newNames {
		if !oldNames[name] {
			m.dbg("setup: adding process %s", name)
			p := m.mgr.Add(name, newCfg.Procs[name], newCfg.Scrollback, newCfg.Shell)
			go func() { _ = p.Start(send) }()
		}
	}

	m.mgr.UpdateDefaults(newCfg)
	m.configPath = msg.configPath
	m.services = m.mgr.Procs()
	m.sortServices()
	m.setupMode = false
	m.setupStep = 1
	m.setupError = ""
	m.focusedPane = focusServices

	updated := m.applySize()
	*m = updated
}

// runHogliListUnits resolves intents into autostart unit names via
// `hogli dev:list-units`.
func runHogliListUnits(intents []string) ([]string, error) {
	hogliPath, err := exec.LookPath("hogli")
	if err != nil {
		return nil, fmt.Errorf("hogli not found in PATH")
	}
	args := append([]string{"dev:list-units"}, intents...)
	cmd := exec.Command(hogliPath, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("hogli dev:list-units: %s", strings.TrimSpace(stderr.String()))
	}
	var units []string
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		if line != "" {
			units = append(units, line)
		}
	}
	return units, nil
}

// runHogliDevApply invokes `hogli dev:apply` with the given intents and
// optional exclusions, returning the path to the generated config.
func runHogliDevApply(intents []string, excludes []string) (string, error) {
	hogliPath, err := exec.LookPath("hogli")
	if err != nil {
		return "", fmt.Errorf("hogli not found in PATH")
	}
	args := []string{"dev:apply"}
	for _, u := range excludes {
		args = append(args, "--exclude", u)
	}
	args = append(args, intents...)
	cmd := exec.Command(hogliPath, args...)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("hogli dev:apply: %s", strings.TrimSpace(stderr.String()))
	}
	return strings.TrimSpace(string(output)), nil
}

func (m *Model) ensureSetupCursorVisible() {
	h := m.setupVisibleHeight()
	if len(m.setupEntries) <= h {
		m.setupOffset = 0
		return
	}
	if m.setupCursor < m.setupOffset {
		m.setupOffset = m.setupCursor
	}
	if m.setupCursor >= m.setupOffset+h {
		m.setupOffset = m.setupCursor - h + 1
	}
}

func (m Model) setupVisibleHeight() int {
	fh := m.footerHeight()
	h := m.height - headerHeight - fh - 3
	return max(h, 1)
}

func (m Model) renderSetupView() string {
	h := m.height - headerHeight - m.footerHeight()
	w := m.width - horizontalBorderCount

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(colorBrightYellow)
	dimStyle := lipgloss.NewStyle().Foreground(colorBrightBlack)

	var rows []string
	rows = append(rows, "")

	if m.setupStep == 1 {
		rows = append(rows, titleStyle.Render("  Configure which services to start based on the products you're working on"))
	} else {
		rows = append(rows, titleStyle.Render("  Uncheck processes you want to exclude"))
	}
	rows = append(rows, "")

	visH := m.setupVisibleHeight()
	start := m.setupOffset
	end := min(start+visH, len(m.setupEntries))

	if start > 0 {
		rows = append(rows, scrollArrowStyle.Width(w).Render("▲"))
	}

	for i := start; i < end; i++ {
		entry := m.setupEntries[i]
		check := "[ ]"
		if m.setupChecked[entry.Name] {
			check = "[x]"
		}

		name := entry.Name
		desc := entry.Description

		maxNameW := 25
		maxDescW := w - maxNameW - 8
		if maxDescW < 0 {
			maxDescW = 0
		}

		name = truncate(name, maxNameW)
		desc = truncate(desc, maxDescW)

		line := fmt.Sprintf("  %s %s", check, name)
		if desc != "" {
			padded := fmt.Sprintf("%-*s", maxNameW, name)
			line = fmt.Sprintf("  %s %s  %s", check, padded, dimStyle.Render(desc))
		}

		if i == m.setupCursor {
			row := lipgloss.NewStyle().
				Bold(true).
				Foreground(colorWhite).
				Background(colorBlack).
				Width(w).
				Render(line)
			rows = append(rows, row)
		} else {
			rows = append(rows, lipgloss.NewStyle().Width(w).Render(line))
		}
	}

	if end < len(m.setupEntries) {
		rows = append(rows, scrollArrowStyle.Width(w).Render("▼"))
	}

	rows = append(rows, "")
	if m.setupStep == 1 {
		rows = append(rows, hintStyle.Render("  Enter to continue..."))
	} else {
		rows = append(rows, hintStyle.Render("  Enter to save and apply"))
	}

	for len(rows) < h {
		rows = append(rows, "")
	}

	style := baseBorderStyle.Height(h)
	return style.Render(strings.Join(rows, "\n"))
}
