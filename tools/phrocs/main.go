// phrocs is a PostHog-branded dev process runner built with Bubble Tea.
//
// It is a drop-in replacement for mprocs: it reads the same YAML config
// that `hogli dev:generate` produces and renders a customisable TUI with a
// per-process sidebar, scrollable output panes, and hogli-aware keybindings.
//
// Usage:
//
//	phrocs [--debug] [--config <config.yaml>]
//	phrocs --version
//
// If --config is omitted, phrocs looks for an mprocs.yaml file in the
// current directory and uses it automatically.
//
// Flags:
//
//	--config  Path to the YAML config file (default to ./mprocs.yaml if it exists)
//	--debug   Write a debug log to /tmp/phrocs-debug.log (key inputs, proc
//	          selection changes, status transitions, etc.)
//	--version Print version information and exit
package main

import (
	"fmt"
	"log"
	"os"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/ipc"
	"github.com/posthog/posthog/phrocs/internal/process"
	"github.com/posthog/posthog/phrocs/internal/tui"
)

var (
	Version   = "dev"
	Commit    = "unknown"
	BuildDate = "unknown"
)

func main() {
	var configPath string
	var logger *log.Logger

	// Parse flags: --config <path>, --debug, --version
	for i := 1; i < len(os.Args); i++ {
		switch os.Args[i] {
		case "--version":
			fmt.Printf("phrocs %s (%s, %s)\n", Version, Commit, BuildDate)
			os.Exit(0)
		case "--config":
			// Next arg is the config file path
			if i+1 < len(os.Args) {
				configPath = os.Args[i+1]
				i++
			}
		case "--debug":
			f, err := os.OpenFile("/tmp/phrocs-debug.log", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
			if err != nil {
				fmt.Fprintf(os.Stderr, "phrocs: open debug log: %v\n", err)
				os.Exit(1)
			}
			logger = log.New(f, "", log.LstdFlags|log.Lmicroseconds)
			logger.Println("debug logging started")
		}
	}

	configPath, err := config.ResolveConfigPath(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		os.Exit(1)
	}

	cfg, err := config.Load(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: load config: %v\n", err)
		os.Exit(1)
	}

	mgr := process.NewManager(cfg)
	m := tui.New(mgr, cfg, logger)
	p := tea.NewProgram(m)

	// StartAll is launched in a goroutine so it doesn't block: p.Send() inside
	// Start() will block briefly on the Bubble Tea channel until p.Run() starts
	// its event loop, at which point everything unblocks naturally. Calling
	// StartAll synchronously before p.Run() deadlocks because the main goroutine
	// would be stuck in p.Send() and p.Run() would never be reached.
	mgr.SetSend(p.Send)
	go mgr.StartAll()

	wd, err := os.Getwd()
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: getwd: %v\n", err)
		os.Exit(1)
	}
	socketPath := ipc.SocketPathFor(wd)

	ln, err := ipc.Listen(socketPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: ipc: %v\n", err)
		os.Exit(1)
	}
	defer func() {
		_ = ln.Close()
		_ = os.Remove(socketPath)
	}()
	go func() {
		// Accept returns an error when the listener is closed on exit; ignore it.
		_ = ipc.Serve(ln, mgr)
	}()

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		os.Exit(1)
	}
}
