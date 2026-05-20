package palette

import (
	"image/color"
	"os"

	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/ansi"
)

var isCursor = os.Getenv("CURSOR_TRACE_ID") != ""
var isZed = os.Getenv("TERM_PROGRAM") == "zed" || os.Getenv("ZED_TERM") == "true"

// Fallback to regular variant in Cursor/Zed terminals to avoid SGR 100-107 bug
func sgrFallback(color ansi.Color, fallback ansi.Color) ansi.Color {
	if isCursor || isZed {
		return fallback
	}
	return color
}

// ANSI 4-bit colors.
// These adapt automatically to the terminal's theme,
// so the UI looks correct on both light and dark backgrounds without
// needing explicit light/dark branching.
var (
	BrandYellow = lipgloss.Color("#F7A501")
	BrandBlue   = lipgloss.Color("#1D4AFF")
	BrandRed    = lipgloss.Color("#F04438")
	BrandBlack  = lipgloss.Color("#151515")

	ColorBlack         color.Color = lipgloss.Black                                        // ANSI 0: contrast text on bright bg
	ColorRed           color.Color = lipgloss.Red                                          // ANSI 1: error/crashed
	ColorGreen         color.Color = lipgloss.Green                                        // ANSI 2: running status
	ColorYellow        color.Color = lipgloss.Yellow                                       // ANSI 3: warnings, pending
	ColorBlue          color.Color = lipgloss.Blue                                         // ANSI 4: copy mode
	ColorMagenta       color.Color = lipgloss.Magenta                                      // ANSI 5: (unused)
	ColorCyan          color.Color = lipgloss.Cyan                                         // ANSI 6: (unused)
	ColorWhite         color.Color = lipgloss.White                                        // ANSI 7: secondary text, inactive items
	ColorBrightBlack   color.Color = sgrFallback(lipgloss.BrightBlack, lipgloss.Black)     // ANSI 8: subtle text/borders (dark)
	ColorBrightRed     color.Color = sgrFallback(lipgloss.BrightRed, lipgloss.Red)         // ANSI 9: (unused)
	ColorBrightGreen   color.Color = sgrFallback(lipgloss.BrightGreen, lipgloss.Green)     // ANSI 10: (unused)
	ColorBrightYellow  color.Color = sgrFallback(lipgloss.BrightYellow, lipgloss.Yellow)   // ANSI 11: (unused)
	ColorBrightBlue    color.Color = sgrFallback(lipgloss.BrightBlue, lipgloss.Blue)       // ANSI 12: (unused)
	ColorBrightMagenta color.Color = sgrFallback(lipgloss.BrightMagenta, lipgloss.Magenta) // ANSI 13: (unused)
	ColorBrightCyan    color.Color = sgrFallback(lipgloss.BrightCyan, lipgloss.Cyan)       // ANSI 14: (unused)
	ColorBrightWhite   color.Color = sgrFallback(lipgloss.BrightWhite, lipgloss.White)     // ANSI 15: subtle text/borders (light)

	// Selection backgrounds: ANSI 0/7 in normal terminals (theme-aware so
	// the highlight blends with the user's color scheme), with an explicit
	// RGB fallback in Cursor/Zed where ANSI 0/7 maps to the default
	// terminal background and the selection paints invisibly. TrueColor
	// (SGR 48;2;r;g;b) is unaffected by the SGR 100-107 bug.
	SelectionDark  color.Color = sgrFallback(lipgloss.Black, lipgloss.Color("#3a3a3a"))
	SelectionLight color.Color = sgrFallback(lipgloss.White, lipgloss.Color("#d4d4d4"))
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
