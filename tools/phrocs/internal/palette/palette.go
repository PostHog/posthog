package palette

import (
	"image/color"

	"charm.land/lipgloss/v2"
)

// ANSI 4-bit colors — these adapt automatically to the terminal's theme,
// so the UI looks correct on both light and dark backgrounds without
// needing explicit light/dark branching.
var (
	BrandYellow = lipgloss.Color("#F7A501")
	BrandBlue   = lipgloss.Color("#1D4AFF")
	BrandRed    = lipgloss.Color("#F04438")
	BrandBlack  = lipgloss.Color("#151515")

	ColorBlack         color.Color = lipgloss.Black         // ANSI 0: contrast text on bright bg
	ColorRed           color.Color = lipgloss.Red           // ANSI 1: error/crashed
	ColorGreen         color.Color = lipgloss.Green         // ANSI 2: running status
	ColorYellow        color.Color = lipgloss.Yellow        // ANSI 3: warnings, pending
	ColorBlue          color.Color = lipgloss.Blue          // ANSI 4: copy mode
	ColorMagenta       color.Color = lipgloss.Magenta       // ANSI 5: (unused)
	ColorCyan          color.Color = lipgloss.Cyan          // ANSI 6: (unused)
	ColorWhite         color.Color = lipgloss.White         // ANSI 7: secondary text, inactive items
	ColorBrightBlack   color.Color = lipgloss.BrightBlack   // ANSI 8: borders, selection bg
	ColorBrightRed     color.Color = lipgloss.BrightRed     // ANSI 9: (unused)
	ColorBrightGreen   color.Color = lipgloss.BrightGreen   // ANSI 10: (unused)
	ColorBrightYellow  color.Color = lipgloss.BrightYellow  // ANSI 11: (unused)
	ColorBrightBlue    color.Color = lipgloss.BrightBlue    // ANSI 12: (unused)
	ColorBrightMagenta color.Color = lipgloss.BrightMagenta // ANSI 13: (unused)
	ColorBrightCyan    color.Color = lipgloss.BrightCyan    // ANSI 14: (unused)
	ColorBrightWhite   color.Color = lipgloss.BrightWhite   // ANSI 15: primary text
)

const (
	IconRunning = "●"
	IconPending = "◌"
	IconStopped = "○"
	IconDone    = "✓"
	IconCrashed = "✗"
	IconWarning = "⚠"
)
