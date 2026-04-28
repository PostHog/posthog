package palette

import (
	"image/color"
	"os"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

var isCursor = os.Getenv("CURSOR_TRACE_ID") != ""

// Fallback to regular variant in Cursor's terminal to avoid SGR 100-107 bug
func brightOr(bright ansi.BasicColor, regular ansi.BasicColor) ansi.BasicColor {
	if isCursor {
		return regular
	}
	return bright
}

// ANSI 4-bit colors — these adapt automatically to the terminal's theme,
// so the UI looks correct on both light and dark backgrounds without
// needing explicit light/dark branching.
var (
	BrandYellow = lipgloss.Color("#F7A501")
	BrandBlue   = lipgloss.Color("#1D4AFF")
	BrandRed    = lipgloss.Color("#F04438")
	BrandBlack  = lipgloss.Color("#151515")

	ColorBlack         color.Color = lipgloss.Black                                     // ANSI 0: contrast text on bright bg
	ColorRed           color.Color = lipgloss.Red                                       // ANSI 1: error/crashed
	ColorGreen         color.Color = lipgloss.Green                                     // ANSI 2: running status
	ColorYellow        color.Color = lipgloss.Yellow                                    // ANSI 3: warnings, pending
	ColorBlue          color.Color = lipgloss.Blue                                      // ANSI 4: copy mode
	ColorMagenta       color.Color = lipgloss.Magenta                                   // ANSI 5: (unused)
	ColorCyan          color.Color = lipgloss.Cyan                                      // ANSI 6: (unused)
	ColorWhite         color.Color = lipgloss.White                                     // ANSI 7: secondary text, inactive items
	ColorBrightBlack   color.Color = brightOr(lipgloss.BrightBlack, lipgloss.Black)     // ANSI 8: selection background (dark)
	ColorBrightRed     color.Color = brightOr(lipgloss.BrightRed, lipgloss.Red)         // ANSI 9: (unused)
	ColorBrightGreen   color.Color = brightOr(lipgloss.BrightGreen, lipgloss.Green)     // ANSI 10: (unused)
	ColorBrightYellow  color.Color = brightOr(lipgloss.BrightYellow, lipgloss.Yellow)   // ANSI 11: (unused)
	ColorBrightBlue    color.Color = brightOr(lipgloss.BrightBlue, lipgloss.Blue)       // ANSI 12: (unused)
	ColorBrightMagenta color.Color = brightOr(lipgloss.BrightMagenta, lipgloss.Magenta) // ANSI 13: (unused)
	ColorBrightCyan    color.Color = brightOr(lipgloss.BrightCyan, lipgloss.Cyan)       // ANSI 14: (unused)
	ColorBrightWhite   color.Color = brightOr(lipgloss.BrightWhite, lipgloss.White)     // ANSI 15: selection background (light)
)

const (
	IconRunning = "●"
	IconPending = "◌"
	IconStopped = "○"
	IconDone    = "✓"
	IconCrashed = "✗"
	IconStandby = "·"
	IconWarning = "⚠"
)
