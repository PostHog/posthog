// Package expand defines the generic sidebar expansion interface.
// Both the TUI and provider packages (docker, etc.) import this
// package to avoid circular dependencies.
package expand

import (
	"image/color"

	tea "charm.land/bubbletea/v2"
)

// Result is returned by Expander.HandleMsg to tell the TUI what changed
type Result struct {
	// Sidebar structure changed (children added/removed/status changed)
	RebuildRows bool
	// A child's output buffer was updated (new log line)
	RefreshOutput bool
	// Follow-up command (e.g. schedule next poll)
	Cmd tea.Cmd
}

// Child represents a single child entry contributed by an expander
type Child struct {
	Name      string
	IconChar  string
	IconColor color.Color
	// Output returns the child's log lines for display. Nil means no selectable output.
	Output func() []string
}

// Expander provides child rows underneath a parent process in the sidebar.
// The TUI calls Init() once at startup, forwards every message through
// HandleMsg(), and queries ChildrenFor() when rebuilding the sidebar row list.
type Expander interface {
	// Init returns the initial command(s) to kick off the expander (e.g. first poll)
	Init() tea.Cmd
	// HandleMsg processes a Bubble Tea message. Implementations should type-switch
	// on their own message types and return a zero Result for everything else.
	HandleMsg(msg tea.Msg) Result
	// ChildrenFor returns child entries for the named process, or nil
	ChildrenFor(procName string) []Child
	// SetSend provides the program's Send function so background goroutines
	// can push messages into the Bubble Tea event loop
	SetSend(send func(tea.Msg))
	// StopAll tears down background goroutines (log streams, etc.)
	StopAll()
}
