package tui

import (
	"image/color"

	"charm.land/lipgloss/v2"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// Plain Unicode, no embedded ANSI so they can be safely composed
// without resetting the enclosing background or foreground colour
const (
	iconCharRunning = "●"
	iconCharPending = "◌"
	iconCharStopped = "○"
	iconCharDone    = "✓"
	iconCharCrashed = "✗"
)

var (
	colorYellow   = lipgloss.Color("#F7A501")
	colorBlue     = lipgloss.Color("#1D4AFF")
	colorGrey     = lipgloss.Color("#9BA1B2")
	colorDarkGrey = lipgloss.Color("#3D3F43")
	colorGreen    = lipgloss.Color("#2DCC5D")
	colorRed      = lipgloss.Color("#F04438")
	colorWhite    = lipgloss.Color("#FFFFFF")
	colorBlack    = lipgloss.Color("#151515")
)

// Outer width of the process list column (including border)
const sidebarWidth = 24

const headerHeight = 1
const footerHeightShort = 3
const footerHeightFull = 5

var (
	// Header
	headerBrandStyle = lipgloss.NewStyle().
				Foreground(colorWhite).
				Bold(true).
				Padding(0, 1)

	headerMetaStyle = lipgloss.NewStyle().
			Foreground(colorGrey).
			Padding(0, 1)

	stripesStyle = lipgloss.NewStyle().
			PaddingLeft(1).
			Render(
			lipgloss.NewStyle().Background(colorBlue).Render(" ") +
				lipgloss.NewStyle().Background(colorYellow).Render(" ") +
				lipgloss.NewStyle().Background(colorRed).Render(" ") +
				lipgloss.NewStyle().Background(colorBlack).Render(" "),
		)

	labelStyle = lipgloss.NewStyle().
			Foreground(colorWhite).
			Bold(true)

	// Borders
	borderStyle = lipgloss.NewStyle().
			BorderRight(true).
			BorderTop(true).
			BorderBottom(true).
			BorderLeft(true).
			BorderStyle(lipgloss.NormalBorder()).
			BorderForeground(colorDarkGrey)

	borderFocusedStyle = borderStyle.
				BorderStyle(lipgloss.ThickBorder())

	// Sidebar
	procInactiveStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorGrey)

	// Footer
	footerStyle = lipgloss.NewStyle().
			Foreground(colorGrey).
			PaddingLeft(1)

	// Copy mode
	copyModeStyle = lipgloss.NewStyle().
			Background(colorBlue).
			Foreground(colorWhite)
)

func statusIconChar(s process.Status) string {
	switch s {
	case process.StatusRunning:
		return iconCharRunning
	case process.StatusPending:
		return iconCharPending
	case process.StatusStopped:
		return iconCharStopped
	case process.StatusDone:
		return iconCharDone
	case process.StatusCrashed:
		return iconCharCrashed
	default:
		return iconCharStopped
	}
}

func statusIconColor(s process.Status) color.Color {
	switch s {
	case process.StatusRunning:
		return colorGreen
	case process.StatusPending:
		return colorYellow
	case process.StatusStopped, process.StatusDone:
		return colorGrey
	case process.StatusCrashed:
		return colorRed
	default:
		return colorYellow
	}
}

func truncate(s string, maxLen int) string {
	if maxLen <= 0 {
		return ""
	}
	runes := []rune(s)
	if len(runes) <= maxLen {
		return s
	}
	return string(runes[:maxLen-1]) + "…"
}
