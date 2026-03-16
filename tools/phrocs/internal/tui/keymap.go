package tui

import "charm.land/bubbles/v2/key"

type keyMap struct {
	PrevProc   key.Binding
	NextProc   key.Binding
	ScrollUp   key.Binding
	ScrollDown key.Binding
	GotoTop    key.Binding
	GotoBottom key.Binding
	SwapFocus  key.Binding
	Restart    key.Binding
	Stop       key.Binding
	Docker     key.Binding
	CopyMode   key.Binding
	CopyEsc    key.Binding
	Search     key.Binding
	SearchNext key.Binding
	SearchPrev key.Binding
	Quit       key.Binding
	Help       key.Binding
}

func defaultKeyMap() keyMap {
	return keyMap{
		PrevProc: key.NewBinding(
			key.WithKeys("j", "up"),
			key.WithHelp("↑:", "prev"),
		),
		NextProc: key.NewBinding(
			key.WithKeys("k", "down"),
			key.WithHelp("↓:", "next"),
		),
		ScrollUp: key.NewBinding(
			key.WithKeys("pgup"),
			key.WithHelp("pgup:", "↥"),
		),
		ScrollDown: key.NewBinding(
			key.WithKeys("pgdn"),
			key.WithHelp("pgdn:", "↧"),
		),
		GotoTop: key.NewBinding(
			key.WithKeys("home"),
			key.WithHelp("home:", "⤒"),
		),
		GotoBottom: key.NewBinding(
			key.WithKeys("end"),
			key.WithHelp("end:", "⤓"),
		),
		SwapFocus: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("↹:", "swap pane"),
		),
		Restart: key.NewBinding(
			key.WithKeys("r"),
			key.WithHelp("r:", "restart"),
		),
		Stop: key.NewBinding(
			key.WithKeys("s"),
			key.WithHelp("s:", "stop"),
		),
		Docker: key.NewBinding(
			key.WithKeys("d"),
			key.WithHelp("d:", "lazydocker"),
			key.WithDisabled(),
		),
		CopyMode: key.NewBinding(
			key.WithKeys("c"),
			key.WithHelp("c:", "copy"),
		),
		CopyEsc: key.NewBinding(
			key.WithKeys("esc"),
			key.WithHelp("esc:", "esc copy"),
		),
		Search: key.NewBinding(
			key.WithKeys("/"),
			key.WithHelp("/:", "search"),
		),
		SearchNext: key.NewBinding(
			key.WithKeys("enter"),
			key.WithHelp("↵:", "next match"),
		),
		SearchPrev: key.NewBinding(
			key.WithKeys("shift+enter"),
			key.WithHelp("⇧↵:", "prev match"),
		),
		Quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q:", "quit"),
		),
		Help: key.NewBinding(
			key.WithKeys("?"),
			key.WithHelp("?:", "help"),
		),
	}
}

func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.NextProc, k.PrevProc, k.SwapFocus, k.Search, k.CopyMode, k.Restart, k.Stop, k.Quit, k.Help}
}

func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.NextProc, k.PrevProc},
		{k.ScrollUp, k.ScrollDown},
		{k.GotoTop, k.GotoBottom},
		{k.Restart, k.Stop, k.SwapFocus},
		{k.Search, k.SearchNext, k.SearchPrev},
		{k.CopyMode, k.Docker},
		{k.Quit, k.Help},
	}
}
