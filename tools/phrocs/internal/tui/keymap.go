package tui

import "charm.land/bubbles/v2/key"

type keyMap struct {
	PrevProc   key.Binding
	NextProc   key.Binding
	KeyUp      key.Binding
	KeyDown    key.Binding
	ScrollUp   key.Binding
	ScrollDown key.Binding
	GotoTop    key.Binding
	GotoBottom key.Binding
	NextPane   key.Binding
	PrevPane   key.Binding
	Start      key.Binding
	Stop       key.Binding
	Restart    key.Binding
	CopyMode   key.Binding
	Search     key.Binding
	SearchNext key.Binding
	SearchPrev key.Binding
	Quit       key.Binding
	Help       key.Binding
	Backspace  key.Binding
	Hedgehog   key.Binding
	Info       key.Binding
	Sort       key.Binding
	LazyDocker key.Binding
	ProcViewer key.Binding
	Setup      key.Binding
}

func defaultKeyMap() keyMap {
	return keyMap{
		PrevProc: key.NewBinding(
			key.WithKeys("k"),
		),
		NextProc: key.NewBinding(
			key.WithKeys("j"),
		),
		KeyUp: key.NewBinding(
			key.WithKeys("up"),
			key.WithHelp("↑:", "prev"),
		),
		KeyDown: key.NewBinding(
			key.WithKeys("down"),
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
		NextPane: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("↹:", "next pane"),
		),
		PrevPane: key.NewBinding(
			key.WithKeys("shift+tab"),
			key.WithHelp("⇧↹:", "prev pane"),
		),
		Start: key.NewBinding(
			key.WithKeys("s"),
			key.WithHelp("s:", "start"),
		),
		Stop: key.NewBinding(
			key.WithKeys("x"),
			key.WithHelp("x:", "stop"),
		),
		Restart: key.NewBinding(
			key.WithKeys("r"),
			key.WithHelp("r:", "restart"),
		),
		CopyMode: key.NewBinding(
			key.WithKeys("c"),
			key.WithHelp("c:", "copy"),
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
		Backspace: key.NewBinding(
			key.WithKeys("backspace"),
			key.WithHelp("⌫:", "del char"),
		),
		Hedgehog: key.NewBinding(
			key.WithKeys("h"),
			key.WithHelp("h:", "hedgehog"),
		),
		Info: key.NewBinding(
			key.WithKeys("i"),
			key.WithHelp("i:", "info"),
		),
		Sort: key.NewBinding(
			key.WithKeys("o"),
			key.WithHelp("o:", "sort"),
		),
		LazyDocker: key.NewBinding(
			key.WithKeys("d"),
			key.WithHelp("d:", "lazydocker"),
			key.WithDisabled(),
		),
		ProcViewer: key.NewBinding(
			key.WithKeys("p"),
			key.WithHelp("p:", "htop"),
			key.WithDisabled(),
		),
		Setup: key.NewBinding(
			key.WithKeys("t"),
			key.WithHelp("t:", "setup"),
		),
	}
}

func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.KeyDown, k.NextPane, k.Start, k.Stop, k.Restart, k.Search, k.CopyMode, k.Setup, k.Sort, k.Info, k.Quit, k.Help}
}

func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.KeyDown, k.KeyUp, k.Sort},
		{k.ScrollUp, k.ScrollDown, k.Setup},
		{k.GotoTop, k.GotoBottom, k.Info},
		{k.NextPane, k.PrevPane, k.LazyDocker, k.ProcViewer},
		{k.Start, k.Stop, k.Restart},
		{k.Search, k.SearchNext, k.SearchPrev},
		{k.CopyMode, k.Quit, k.Help},
	}
}
