package tui

import (
	"image/color"

	"charm.land/lipgloss/v2"
	sharedpalette "github.com/posthog/posthog/phrocs/internal/palette"
	"github.com/posthog/posthog/phrocs/internal/process"
)

// Plain Unicode, no embedded ANSI so they can be safely composed
// without resetting the enclosing background or foreground colour
const (
	iconCharRunning = sharedpalette.IconRunning
	iconCharPending = sharedpalette.IconPending
	iconCharStopped = sharedpalette.IconStopped
	iconCharDone    = sharedpalette.IconDone
	iconCharCrashed = sharedpalette.IconCrashed
)

var (
	colorYellow   = sharedpalette.ColorYellow
	colorBlue     = sharedpalette.ColorBlue
	colorGrey     = sharedpalette.ColorGrey
	colorDarkGrey = sharedpalette.ColorDarkGrey
	colorGreen    = sharedpalette.ColorGreen
	colorRed      = sharedpalette.ColorRed
	colorWhite    = sharedpalette.ColorWhite
	colorBlack    = sharedpalette.ColorBlack
)

// Outer width of the process list column (including border)
const sidebarWidth = 24

// Outer width of the container sidebar (including border)
const containerSidebarWidth = 24

const headerHeight = 1
const footerHeightShort = 3
const footerHeightFull = 5
const horizontalBorderCount = 4

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

	// Scroll position indicator (floating top-right of output pane)
	scrollIndicatorStyle = lipgloss.NewStyle().
				Foreground(colorBlack).
				Background(colorYellow).
				Padding(0, 1)

	// Copy mode
	copyModeStyle = lipgloss.NewStyle().
			Background(colorBlue).
			Foreground(colorWhite)

	// Search mode
	searchMatchStyle = lipgloss.NewStyle().
				Background(colorDarkGrey)

	searchCurrentMatchStyle = lipgloss.NewStyle().
				Background(colorYellow).
				Foreground(colorBlack)
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

// Renders a single sidebar row with icon, name, and selected/unselected styling.
// Used by both the process sidebar and the container sidebar.
func renderSidebarRow(icon, name string, iconColor color.Color, selected bool, innerW int) string {
	if selected {
		base := lipgloss.NewStyle().Background(colorDarkGrey).Bold(true)
		iconSeg := base.PaddingLeft(1).Foreground(iconColor).Render(icon)
		nameSeg := base.Foreground(colorWhite).Width(innerW - 2).Render(" " + name)
		return iconSeg + nameSeg
	}
	iconSeg := lipgloss.NewStyle().PaddingLeft(1).Foreground(iconColor).Render(icon)
	nameSeg := lipgloss.NewStyle().Foreground(colorGrey).Width(innerW - 2).Render(" " + name)
	return iconSeg + nameSeg
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
