package tui

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"

	"charm.land/bubbles/v2/key"
	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
)

type setupEntry struct {
	Name        string
	Description string
}

func (m Model) enterSetupMode() Model {
	// Find intent-map.yaml relative to the config file's repo root.
	// Walk up from the config path to find the repo root (has .git).
	intentMapPath := "devenv/intent-map.yaml"
	if m.configPath != "" {
		dir := filepath.Dir(m.configPath)
		for {
			if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
				intentMapPath = filepath.Join(dir, "devenv", "intent-map.yaml")
				break
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}

	intentMap, err := config.LoadIntentMap(intentMapPath)
	if err != nil {
		m.setupError = fmt.Sprintf("load intent-map: %v", err)
		m.setupMode = true
		return m
	}

	// Build sorted entry list
	var entries []setupEntry
	for name, intent := range intentMap.Intents {
		entries = append(entries, setupEntry{
			Name:        name,
			Description: intent.Description,
		})
	}
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name < entries[j].Name
	})

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
	m.setupEntries = entries
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
		m = m.applySize()
		m.dbg("setup mode: cancel")

	case msg.Code == tea.KeyEnter:
		m.dbg("setup mode: apply")
		m.applySetupChanges()

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

func (m *Model) applySetupChanges() {
	var selected []string
	for _, entry := range m.setupEntries {
		if m.setupChecked[entry.Name] {
			selected = append(selected, entry.Name)
		}
	}
	if len(selected) == 0 {
		m.setupError = "select at least one product"
		return
	}

	// Find hogli binary
	hogliPath, err := exec.LookPath("hogli")
	if err != nil {
		m.setupError = "hogli not found in PATH"
		return
	}

	// Snapshot current process names before applying changes
	oldNames := make(map[string]bool)
	for _, p := range m.mgr.Procs() {
		oldNames[p.Name] = true
	}

	// Run hogli dev:apply synchronously to regenerate the config
	args := append([]string{"hogli", "dev:apply"}, selected...)
	cmd := exec.Command(hogliPath, args[1:]...)
	cmd.Stderr = os.Stderr
	output, err := cmd.Output()
	if err != nil {
		m.setupError = fmt.Sprintf("hogli dev:apply failed: %v", err)
		return
	}

	newConfigPath := strings.TrimSpace(string(output))
	m.dbg("setup: hogli dev:apply output: %s", newConfigPath)

	// Load the new config
	newCfg, err := config.Load(newConfigPath)
	if err != nil {
		m.setupError = fmt.Sprintf("load new config: %v", err)
		return
	}

	newNames := make(map[string]bool)
	for name := range newCfg.Procs {
		newNames[name] = true
	}

	// Remove processes that are no longer in the config
	for name := range oldNames {
		if !newNames[name] {
			m.dbg("setup: removing process %s", name)
			m.mgr.Remove(name)
		}
	}

	// Add and start processes that are new in the config
	send := m.mgr.Send()
	for name := range newNames {
		if !oldNames[name] {
			m.dbg("setup: adding process %s", name)
			p := m.mgr.Add(name, newCfg.Procs[name], newCfg.Scrollback)
			if p.Cfg.ShouldAutostart() {
				_ = p.Start(send)
			}
		}
	}

	// Update config path and refresh TUI state
	m.configPath = newConfigPath
	m.services = m.mgr.Procs()
	m.sortServices()
	m.setupMode = false
	m.setupError = ""
	updated := m.applySize()
	*m = updated
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
	// Account for header, footer, and 2 lines of padding/title
	fh := m.footerHeight()
	h := m.height - headerHeight - fh - 3
	return max(h, 1)
}

func (m Model) renderSetupView() string {
	h := m.height - headerHeight - m.footerHeight()
	w := m.width - horizontalBorderCount

	titleStyle := lipgloss.NewStyle().Bold(true).Foreground(colorYellow)
	dimStyle := lipgloss.NewStyle().Foreground(colorBrightBlack)

	var rows []string
	rows = append(rows, "")
	rows = append(rows, titleStyle.Render("  Select products to run"))
	rows = append(rows, "")

	visH := m.setupVisibleHeight()
	start := m.setupOffset
	end := min(start+visH, len(m.setupEntries))

	canScrollUp := start > 0
	canScrollDown := end < len(m.setupEntries)

	if canScrollUp {
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

		// Truncate to fit
		maxNameW := 25
		maxDescW := w - maxNameW - 8 // 2 padding + 4 checkbox + 2 gap
		if maxDescW < 0 {
			maxDescW = 0
		}

		name = truncate(name, maxNameW)
		desc = truncate(desc, maxDescW)

		line := fmt.Sprintf("  %s %s", check, name)
		if desc != "" {
			// Pad name to fixed width for alignment
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

	if canScrollDown {
		rows = append(rows, scrollArrowStyle.Width(w).Render("▼"))
	}

	// Pad to fill height
	for len(rows) < h {
		rows = append(rows, "")
	}

	style := baseBorderStyle.Height(h)
	return style.Render(strings.Join(rows, "\n"))
}
