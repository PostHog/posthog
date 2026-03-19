package tui

import (
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

var hedgehogFramesRight = [][]string{
	{
		`  .::::::::..   `,
		` :::::::::::::  `,
		`:::::::::::' .\ `,
		`':::;::::::_,__o`,
	},
	{
		`  .::::::::..   `,
		` :::::::::::::  `,
		`:::::::::::' .\ `,
		`'::;:::::::,___o`,
	},
}

var hedgehogFramesLeft = [][]string{
	{
		`   ..::::::::.  `,
		`  ::::::::::::: `,
		` /. ':::::::::::`,
		`o__,_::::::;:::'`,
	},
	{
		`   ..::::::::.  `,
		`  ::::::::::::: `,
		` /. ':::::::::::`,
		`o___,:::::::;::'`,
	},
}

const hedgehogTickInterval = 150 * time.Millisecond

type hedgehogTickMsg struct{}

func hedgehogTick() tea.Cmd {
	return tea.Tick(hedgehogTickInterval, func(time.Time) tea.Msg {
		return hedgehogTickMsg{}
	})
}

func (m *Model) advanceHedgehog() {
	m.hedgehogX += m.hedgehogDir
	m.hedgehogFrame = (m.hedgehogFrame + 1) % 2

	// Apply gravity to vertical movement
	if m.hedgehogY > 0 || m.hedgehogVelY > 0 {
		m.hedgehogY += m.hedgehogVelY
		m.hedgehogVelY--
		if m.hedgehogY <= 0 {
			m.hedgehogY = 0
			m.hedgehogVelY = 0
		}
	}

	maxX := max(m.viewport.Width()-len(hedgehogFramesLeft[0][0]), 0)
	if m.hedgehogX >= maxX {
		m.hedgehogX = maxX
		m.hedgehogDir = -1
	} else if m.hedgehogX <= 0 {
		m.hedgehogX = 0
		m.hedgehogDir = 1
	}
}

// Overlays the hedgehog sprite onto the viewport content string
func (m Model) overlayHedgehog(view string) string {
	lines := strings.Split(view, "\n")
	vpH := m.viewport.Height()

	// Place hedgehog at the bottom of the visible viewport, offset by jump height
	spriteH := len(hedgehogFramesLeft[0])
	startLine := max(vpH-spriteH-m.hedgehogY, 0)

	// Pad lines if needed
	for len(lines) < vpH {
		lines = append(lines, "")
	}

	frames := hedgehogFramesRight
	if m.hedgehogDir < 0 {
		frames = hedgehogFramesLeft
	}
	sprite := frames[m.hedgehogFrame]

	spikeStyle := lipgloss.NewStyle().
		Foreground(colorYellow).
		Bold(true)

	for i, spriteLine := range sprite {
		lineIdx := startLine + i
		if lineIdx >= len(lines) {
			break
		}

		// Strip leading/trailing whitespace from the sprite line so the
		// hedgehog doesn't overwrite surrounding content with blanks.
		trimmed := strings.TrimRight(spriteLine, " ")
		leading := len(spriteLine) - len(strings.TrimLeft(spriteLine, " "))
		trimmed = trimmed[leading:]

		rendered := spikeStyle.Render(trimmed)
		lines[lineIdx] = overwriteAt(lines[lineIdx], rendered, m.hedgehogX+leading, m.viewport.Width())
	}

	return strings.Join(lines[:vpH], "\n")
}

// Overwrites a portion of a styled line at a given column position
func overwriteAt(line, overlay string, col, maxW int) string {
	lineW := lipgloss.Width(line)
	overlayW := lipgloss.Width(overlay)

	// Ensure line is wide enough
	if lineW < col+overlayW {
		line += strings.Repeat(" ", col+overlayW-lineW)
	}

	// Truncate the line at col, insert overlay, then append remainder
	before := ansi.Truncate(line, col, "")
	afterStart := col + overlayW
	var after string
	if afterStart < maxW && afterStart < lipgloss.Width(line) {
		// Cut the first afterStart columns and keep the rest
		after = ansi.TruncateLeft(line, afterStart, "")
	}

	return before + overlay + after
}
