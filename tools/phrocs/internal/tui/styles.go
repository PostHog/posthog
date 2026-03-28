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
	colorMidGrey  = sharedpalette.ColorMidGrey
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
				BorderStyle(lipgloss.ThickBorder()).
				BorderForeground(colorMidGrey)

	// Sidebar
	procInactiveStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorGrey)

	scrollArrowStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorGrey).
				Align(lipgloss.Center)

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

	// Info mode
	warnStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(colorYellow).
			Background(sharedpalette.ColorBarMid)
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

// cpuBarColor returns a background tint based on CPU usage percentage.
func cpuBarColor(cpuPct float64) color.Color {
	switch {
	case cpuPct >= 150:
		return sharedpalette.ColorBarHigh
	case cpuPct >= 50:
		return sharedpalette.ColorBarMid
	default:
		return sharedpalette.ColorBarLow
	}
}

// Renders a single sidebar row with icon, name, and an htop-style CPU usage
// bar as a background fill. cpuPct is the total CPU% for the process tree;
// the filled portion scales to innerW (100% = full width).
// Used by both the process sidebar and the container sidebar.
func renderSidebarRow(icon, name string, iconColor color.Color, selected bool, cpuPct float64, innerW int) string {
	// How many columns the bar fills (cap at innerW)
	barW := 0
	if cpuPct > 0 {
		barW = int(cpuPct / 100.0 * float64(innerW))
		barW = max(min(barW, innerW), 1)
	}

	barBg := cpuBarColor(cpuPct)
	nameW := max(innerW-2, 0) // 1 padding + 1 icon

	// Pick background for each segment based on whether it falls within the bar
	bgFor := func(col int) color.Color {
		if selected {
			if barW > 0 && col < barW {
				return barBg
			}
			return colorDarkGrey
		}
		if barW > 0 && col < barW {
			return barBg
		}
		return nil
	}

	textColor := colorGrey
	if selected {
		textColor = colorWhite
	}

	// Icon occupies columns 0 (padding) and 1 (icon char)
	iconBg := bgFor(0)
	iconStyle := lipgloss.NewStyle().PaddingLeft(1).Foreground(iconColor)
	if selected {
		iconStyle = iconStyle.Bold(true)
	}
	if iconBg != nil {
		iconStyle = iconStyle.Background(iconBg)
	}
	iconSeg := iconStyle.Render(icon)

	// Name starts at column 2 and spans nameW columns
	// Split into filled and unfilled portions based on barW
	nameContent := " " + name
	nameRunes := []rune(nameContent)
	for len(nameRunes) < nameW {
		nameRunes = append(nameRunes, ' ')
	}
	if len(nameRunes) > nameW {
		nameRunes = nameRunes[:nameW]
	}

	// The name starts at column 2, so the bar covers columns 2..barW-1
	nameFillW := max(min(barW-2, nameW), 0)

	filledPart := ""
	if nameFillW > 0 {
		s := lipgloss.NewStyle().Foreground(textColor).Background(barBg)
		if selected {
			s = s.Bold(true)
		}
		filledPart = s.Render(string(nameRunes[:nameFillW]))
	}

	unfilledRunes := nameRunes[nameFillW:]
	unfilledStyle := lipgloss.NewStyle().Foreground(textColor)
	if selected {
		unfilledStyle = unfilledStyle.Bold(true).Background(colorDarkGrey)
	}
	// Pad remaining width so the background extends to the edge
	unfilledStyle = unfilledStyle.Width(nameW - nameFillW)
	unfilledPart := unfilledStyle.Render(string(unfilledRunes))

	return iconSeg + filledPart + unfilledPart
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
