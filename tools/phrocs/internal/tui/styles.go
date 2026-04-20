package tui

import (
	"image/color"

	"charm.land/bubbles/v2/help"
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
	colorYellow       = sharedpalette.ColorYellow
	colorBlue         = sharedpalette.ColorBlue
	colorGreen        = sharedpalette.ColorGreen
	colorRed          = sharedpalette.ColorRed
	colorBlack        = sharedpalette.ColorBlack
	colorWhite        = sharedpalette.ColorWhite
	colorBrightWhite  = sharedpalette.ColorBrightWhite
	colorBrightBlack  = sharedpalette.ColorBrightBlack
	colorBrightYellow = sharedpalette.ColorBrightYellow
	brandYellow       = sharedpalette.BrandYellow
	brandBlue         = sharedpalette.BrandBlue
	brandRed          = sharedpalette.BrandRed
	brandBlack        = sharedpalette.BrandBlack
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
				Bold(true).
				Padding(0, 1)

	headerMetaStyle = lipgloss.NewStyle().
			Foreground(colorBrightBlack).
			Padding(0, 1)

	stripesStyle = lipgloss.NewStyle().
			PaddingLeft(1).
			Render(
			lipgloss.NewStyle().Background(brandBlue).Render(" ") +
				lipgloss.NewStyle().Background(brandRed).Render(" ") +
				lipgloss.NewStyle().Background(brandYellow).Render(" ") +
				lipgloss.NewStyle().Background(brandBlack).Render(" "),
		)

	labelStyle = lipgloss.NewStyle().
			Bold(true)

	// Borders — foreground is set dynamically via borderFor()
	baseBorderStyle = lipgloss.NewStyle().
			BorderRight(true).
			BorderTop(true).
			BorderBottom(true).
			BorderLeft(true).
			BorderStyle(lipgloss.NormalBorder())

	// Sidebar
	procInactiveStyle = lipgloss.NewStyle().
				PaddingLeft(1)

	scrollArrowStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Foreground(colorBrightBlack).
				Align(lipgloss.Center)

	// Footer
	footerStyle = lipgloss.NewStyle().
			PaddingLeft(1)

	// Scroll position indicator (floating top-right of output pane)
	scrollIndicatorStyle = lipgloss.NewStyle().
				Foreground(colorBlack).
				Background(colorYellow).
				Padding(0, 1)

	// Copy mode
	copyModeStyle = lipgloss.NewStyle().
			Background(colorBlue).
			Foreground(colorBlack)

	// Search mode
	searchMatchStyle = lipgloss.NewStyle().
				Background(colorBrightBlack)

	searchCurrentMatchStyle = lipgloss.NewStyle().
				Background(colorYellow).
				Foreground(colorBlack)

	// Info mode
	warnStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(colorYellow).
			Background(colorBrightBlack)

	hintStyle = lipgloss.NewStyle().
			Foreground(colorBrightYellow)

	// Group header in grouped sidebar mode
	groupHeaderStyle = lipgloss.NewStyle().
				PaddingLeft(1).
				Bold(true).
				Foreground(colorBrightBlack)
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
		return nil
	case process.StatusCrashed:
		return colorRed
	default:
		return colorYellow
	}
}

// Renders a single sidebar row with icon and name
func subtleBg(isDark bool) color.Color {
	if isDark {
		return colorBrightBlack
	}
	return colorBrightWhite
}

// borderFor returns the border style with a foreground appropriate for the
// current terminal background.
func borderFor(isDark, focused bool) lipgloss.Style {
	s := baseBorderStyle.BorderForeground(subtleBg(isDark))
	if focused {
		s = s.BorderStyle(lipgloss.ThickBorder())
	}
	return s
}

type sidebarRow struct {
	icon      string
	name      string
	iconColor color.Color
	selected  bool
	unread    bool
	innerW    int
	isDark    bool
}

func renderSidebarRow(r sidebarRow) string {
	nameW := max(r.innerW-2, 0) // 1 padding + 1 icon
	selBg := subtleBg(r.isDark)

	iconStyle := lipgloss.NewStyle().PaddingLeft(1).Foreground(r.iconColor)
	if r.selected {
		iconStyle = iconStyle.Background(selBg)
	}

	nameStyle := lipgloss.NewStyle().Width(nameW)
	if r.selected {
		nameStyle = nameStyle.Background(selBg)
	} else if r.unread {
		nameStyle = nameStyle.Bold(true)
	}

	return iconStyle.Render(r.icon) + nameStyle.Render(" "+r.name)
}

func helpStyles() help.Styles {
	keyStyle := lipgloss.NewStyle()
	descStyle := lipgloss.NewStyle().Foreground(colorBrightBlack)
	sepStyle := lipgloss.NewStyle().Foreground(colorBrightBlack)

	return help.Styles{
		ShortKey:       keyStyle,
		ShortDesc:      descStyle,
		ShortSeparator: sepStyle,
		Ellipsis:       sepStyle,
		FullKey:        keyStyle,
		FullDesc:       descStyle,
		FullSeparator:  sepStyle,
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
