package palette

import "charm.land/lipgloss/v2"

var (
	ColorYellow   = lipgloss.Color("#F7A501")
	ColorBlue     = lipgloss.Color("#1D4AFF")
	ColorGrey     = lipgloss.Color("#9BA1B2")
	ColorDarkGrey = lipgloss.Color("#3D3F43")
	ColorGreen    = lipgloss.Color("#2DCC5D")
	ColorRed      = lipgloss.Color("#F04438")
	ColorWhite    = lipgloss.Color("#FFFFFF")
	ColorBlack    = lipgloss.Color("#151515")
	ColorMidGrey  = lipgloss.Color("#555860") // focused-border accent

	// Subtle background tint for CPU usage bars (htop-style)
	ColorBarLow  = lipgloss.Color("#1A3A1A") // green tint, low CPU
	ColorBarMid  = lipgloss.Color("#3A3A1A") // yellow tint, moderate CPU
	ColorBarHigh = lipgloss.Color("#3A1A1A") // red tint, high CPU
)

const (
	IconRunning = "●"
	IconPending = "◌"
	IconStopped = "○"
	IconDone    = "✓"
	IconCrashed = "✗"
	IconWarning = "⚠"
)
