package tui

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
)

type evalHarness struct {
	t         *testing.T
	m         EvalModel
	replies   []string
	clipboard []string
	quit      bool
}

func newEvalHarness(t *testing.T) *evalHarness {
	t.Helper()
	h := &evalHarness{t: t}
	h.m = NewEvalModel(func(reply string) { h.replies = append(h.replies, reply) })
	h.m.clipboard = func(text string) { h.clipboard = append(h.clipboard, text) }
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

func TestEvalTrialSelectionShowsItsSummaryFile(t *testing.T) {
	dir := t.TempDir()
	summary := filepath.Join(dir, "weekly_signups.summary.txt")
	if err := os.WriteFile(summary, []byte("Score: 0.5\nMissing breakdown"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := newEvalHarness(t)
	h.event(EvalEvent{Type: "experiment", Name: "sql-basics", Total: 2})
	h.event(EvalEvent{Type: "trial", ID: "t1", Experiment: "sql-basics", Name: "count events", Phase: "agent"})
	h.event(EvalEvent{Type: "trial", ID: "t2", Experiment: "sql-basics", Name: "weekly signups", Phase: "done", SummaryPath: summary})
	h.event(EvalEvent{Type: "trial", ID: "t1", Experiment: "sql-basics", Name: "count events", Phase: "error", Detail: "Traceback (most recent call last):\nRuntimeError: Agent server crashed"})

	h.keys(keypress('j'))
	got := h.m.viewport.GetContent()
	for _, want := range []string{"Phase: error", "Error", "RuntimeError: Agent server crashed", "No summary for this trial"} {
		if !strings.Contains(got, want) {
			t.Fatalf("failed trial view = %q, want %q", got, want)
		}
	}

	line := -1
	for i, text := range h.m.contentLines() {
		if strings.Contains(text, "RuntimeError: Agent server crashed") {
			line = i
		}
	}
	y := headerHeight + 1 + h.m.wrappedRow(line) - h.m.viewport.YOffset()
	left := h.m.sidebarWidth() + 1
	h.update(tea.MouseClickMsg{Button: tea.MouseLeft, X: left, Y: y})
	h.update(tea.MouseMotionMsg{Button: tea.MouseLeft, X: left + 10, Y: y})
	h.update(tea.MouseReleaseMsg{Button: tea.MouseLeft, X: left + len("RuntimeError") - 1, Y: y})
	if len(h.clipboard) != 1 || h.clipboard[0] != "RuntimeError" {
		t.Fatalf("clipboard = %q, want the dragged text", h.clipboard)
	}

	h.keys(keypress('c'), keypress('c'), keypress('j'), keypress('c'))
	if len(h.clipboard) != 2 || strings.Count(h.clipboard[1], "\n") != 1 || h.m.copyMode {
		t.Fatalf("copy mode clipboard = %q, copyMode = %v; want two lines and copy mode closed", h.clipboard, h.m.copyMode)
	}

	h.keys(tea.KeyPressMsg{Code: tea.KeyTab}, keypress('j'))
	cmd := h.m.pollFile()
	if cmd == nil {
		t.Fatal("selecting a trial with a summary path must start a file read")
	}
	h.update(cmd())
	if got := h.m.viewport.GetContent(); !strings.Contains(got, "Missing breakdown") {
		t.Fatalf("second trial view = %q, want the summary file contents", got)
	}

	h.keys(keypress('j'))
	if trial := h.m.selectedTrial(); trial == nil || trial.id != "t2" {
		t.Fatalf("cursor left the last trial: %+v", trial)
	}
}
