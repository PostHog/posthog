package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/term"
	"github.com/posthog/posthog/phrocs/internal/tui"
)

// runEvals renders an eval harness run. The harness passes one end of a socket
// pair as streamFD: it writes JSON events, and this view writes back "ready"
// and "cancel" lines.
func runEvals(streamFD int) int {
	stream := os.NewFile(uintptr(streamFD), "eval-events")
	if stream == nil {
		fmt.Fprintf(os.Stderr, "phrocs: evals: file descriptor %d is not open\n", streamFD)
		return 2
	}
	defer stream.Close()

	// The harness owns cancellation. A stray SIGINT must not close the view
	// while the harness still cleans up sandboxes.
	signal.Ignore(syscall.SIGINT)

	m := tui.NewEvalModel(func(command string) {
		_, _ = fmt.Fprintln(stream, command)
	})
	opts := []tea.ProgramOption{tea.WithoutSignalHandler()}
	if !term.IsTerminal(os.Stdout.Fd()) {
		ttyIn, ttyOut, err := tea.OpenTTY()
		if err == nil {
			opts = append(opts, tea.WithInput(ttyIn), tea.WithOutput(ttyOut))
			defer func() {
				_ = ttyIn.Close()
				_ = ttyOut.Close()
			}()
		}
	}
	p := tea.NewProgram(m, opts...)

	go func() {
		scanner := bufio.NewScanner(stream)
		scanner.Buffer(make([]byte, 64*1024), 16*1024*1024)
		for scanner.Scan() {
			var event tui.EvalEvent
			if err := json.Unmarshal(scanner.Bytes(), &event); err == nil {
				p.Send(tui.EvalEventMsg(event))
			}
		}
		p.Send(tui.EvalStreamClosedMsg{})
	}()

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}
	return 0
}

func parseFD(value string) (int, error) {
	fd, err := strconv.Atoi(value)
	if err != nil || fd < 3 {
		return 0, fmt.Errorf("--fd must be a file descriptor number of 3 or more, got %q", value)
	}
	return fd, nil
}
