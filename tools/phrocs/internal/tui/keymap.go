package tui

import "charm.land/bubbles/v2/key"

type keyMap struct {
	PrevProc     key.Binding
	NextProc     key.Binding
	KeyUp        key.Binding
	KeyDown      key.Binding
	ScrollUp     key.Binding
	ScrollDown   key.Binding
	GotoTop      key.Binding
	GotoBottom   key.Binding
	NextPane     key.Binding
	PrevPane     key.Binding
	Start        key.Binding
	Stop         key.Binding
	Restart      key.Binding
	ClearLogs    key.Binding
	CopyMode     key.Binding
	InfoMode     key.Binding
	SearchMode   key.Binding
	SearchNext   key.Binding
	SearchPrev   key.Binding
	CommitFilter key.Binding
	ToggleFilter key.Binding
	Quit         key.Binding
	Help         key.Binding
	Backspace    key.Binding
	Hedgehog     key.Binding
	Sort         key.Binding
	Group        key.Binding
	LazyDocker   key.Binding
	ProcViewer   key.Binding
	SetupMode    key.Binding
	ShowAll      key.Binding
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
		ClearLogs: key.NewBinding(
			key.WithKeys("l"),
			key.WithHelp("l:", "clear"),
		),
		CopyMode: key.NewBinding(
			key.WithKeys("c"),
			key.WithHelp("c:", "copy"),
		),
		SearchMode: key.NewBinding(
			key.WithKeys("/"),
			key.WithHelp("/:", "search"),
		),
		SearchNext: key.NewBinding(
			key.WithKeys("down"),
			key.WithHelp("↓:", "next match"),
		),
		SearchPrev: key.NewBinding(
			key.WithKeys("up"),
			key.WithHelp("↑:", "prev match"),
		),
		CommitFilter: key.NewBinding(
			key.WithKeys("enter"),
			key.WithHelp("↵:", "filter"),
		),
		ToggleFilter: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("↹:", "back to search"),
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
		InfoMode: key.NewBinding(
			key.WithKeys("i"),
			key.WithHelp("i:", "info"),
		),
		Sort: key.NewBinding(
			key.WithKeys("o"),
			key.WithHelp("o:", "sort"),
		),
		Group: key.NewBinding(
			key.WithKeys("g"),
			key.WithHelp("g:", "group"),
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
		SetupMode: key.NewBinding(
			key.WithKeys("t"),
			key.WithHelp("t:", "setup"),
		),
		ShowAll: key.NewBinding(
			key.WithKeys("a"),
			key.WithHelp("a:", "show all"),
		),
	}
}

func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.Start, k.Stop, k.Restart, k.ClearLogs, k.SearchMode, k.CopyMode, k.InfoMode, k.SetupMode, k.Quit, k.Help}
}

func (k keyMap) SearchModeHelp() []key.Binding {
	return []key.Binding{k.SearchNext, k.SearchPrev, k.CommitFilter}
}

func (k keyMap) FilterModeHelp() []key.Binding {
	return []key.Binding{k.ToggleFilter}
}

func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.KeyDown, k.KeyUp, k.Sort},
		{k.ScrollUp, k.ScrollDown, k.Group},
		{k.GotoTop, k.GotoBottom, k.ClearLogs},
		{k.NextPane, k.PrevPane, k.LazyDocker, k.ProcViewer},
		{k.Start, k.Stop, k.Restart, k.InfoMode},
		{k.SearchMode, k.CopyMode, k.SetupMode},
		{k.Quit, k.Help, k.ShowAll},
	}
}
