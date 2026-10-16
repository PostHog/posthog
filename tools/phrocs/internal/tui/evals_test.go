package tui

import (
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
)

type evalHarness struct {
	t       *testing.T
	m       EvalModel
	replies []string
	quit    bool
}

func newEvalHarness(t *testing.T) *evalHarness {
	t.Helper()
	h := &evalHarness{t: t}
	h.m = NewEvalModel(func(reply string) { h.replies = append(h.replies, reply) })
	h.update(tea.WindowSizeMsg{Width: 120, Height: 30})
	h.replies = nil
	return h
}

// run executes the commands a key or event produced. Key and event handlers
// only return reply and quit commands, so no timer command blocks here.
func (h *evalHarness) run(cmd tea.Cmd) {
	if cmd == nil {
		return
	}
	switch msg := cmd().(type) {
	case tea.BatchMsg:
		for _, c := range msg {
			h.run(c)
		}
	case tea.QuitMsg:
		h.quit = true
	}
}

func (h *evalHarness) update(msg tea.Msg) {
	next, cmd := h.m.Update(msg)
	h.m = next.(EvalModel)
	h.run(cmd)
}

func (h *evalHarness) keys(keys ...tea.KeyPressMsg) {
	for _, k := range keys {
		h.update(k)
	}
}

func (h *evalHarness) event(ev EvalEvent) { h.update(EvalEventMsg(ev)) }

var ctrlC = tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl}

func TestEvalCancelAndClose(t *testing.T) {
	exitCode := 0
	tests := []struct {
		name        string
		finished    bool
		keys        []tea.KeyPressMsg
		wantReplies []string
		wantQuit    bool
	}{
		{name: "q asks before it cancels", keys: []tea.KeyPressMsg{keypress('q')}},
		{name: "q then n keeps the run", keys: []tea.KeyPressMsg{keypress('q'), keypress('n'), keypress('y')}},
		{name: "q then y cancels", keys: []tea.KeyPressMsg{keypress('q'), keypress('y')}, wantReplies: []string{"cancel"}},
		{name: "ctrl+c cancels once", keys: []tea.KeyPressMsg{ctrlC, ctrlC, keypress('q'), keypress('y')}, wantReplies: []string{"cancel"}},
		{name: "ctrl+c cancels while searching", keys: []tea.KeyPressMsg{keypress('/'), ctrlC}, wantReplies: []string{"cancel"}},
		{name: "ctrl+c cancels at the confirmation", keys: []tea.KeyPressMsg{keypress('q'), ctrlC}, wantReplies: []string{"cancel"}},
		{name: "q closes a finished run", finished: true, keys: []tea.KeyPressMsg{keypress('q')}, wantQuit: true},
		{name: "ctrl+c closes a finished run", finished: true, keys: []tea.KeyPressMsg{ctrlC}, wantQuit: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			h := newEvalHarness(t)
			if tt.finished {
				h.event(EvalEvent{Type: "finish", ExitCode: &exitCode})
			}
			h.keys(tt.keys...)
			if strings.Join(h.replies, ",") != strings.Join(tt.wantReplies, ",") {
				t.Fatalf("replies = %v, want %v", h.replies, tt.wantReplies)
			}
			if h.quit != tt.wantQuit {
				t.Fatalf("quit = %v, want %v", h.quit, tt.wantQuit)
			}
		})
	}
}

func TestEvalStreamCloseWithoutResultReleasesTheTerminal(t *testing.T) {
	h := newEvalHarness(t)
	h.keys(keypress('q'))
	h.update(EvalStreamClosedMsg{})
	if !h.quit || len(h.replies) != 0 || !h.m.HarnessLost() {
		t.Fatalf("quit = %v, replies = %v, lost = %v; want an immediate quit without cancel", h.quit, h.replies, h.m.HarnessLost())
	}
}
