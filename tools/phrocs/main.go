// phrocs is a PostHog-branded dev process runner built with Bubble Tea.
//
// It is a drop-in replacement for mprocs: it reads the same YAML config
// that `hogli dev:generate` produces and renders a customisable TUI with a
// per-process sidebar, scrollable output panes, and hogli-aware keybindings.
//
// Usage:
//
//	phrocs [--debug] [--config <config.yaml>]          # interactive TUI
//	phrocs -d | --detach [--config <config.yaml>]      # detached mode (no TUI)
//	phrocs wait [--timeout N] [--json]                 # block on readiness
//	phrocs stop [--timeout N]                          # stop detached process via IPC
//	phrocs attach                                      # polling TUI against a detached process
//	phrocs --version
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
	"os/signal"
	"syscall"

	tea "charm.land/bubbletea/v2"
	"github.com/charmbracelet/x/term"
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

// detachedChildEnv is set on the re-exec'd child so it knows to skip the fork
// and run the detached main loop instead.
const detachedChildEnv = "PHROCS_DETACHED_CHILD"

// parsedArgs captures flags common to every mode. `subcommand` is the first
// non-flag token if it matches a known name; empty means "interactive or detached
// based on flag presence".
type parsedArgs struct {
	subcommand string
	configPath string
	debug      bool
	detach     bool
	timeout    int
	asJSON     bool
}

func printUsage() {
	fmt.Println(`phrocs — PostHog dev process runner

Usage:
  phrocs [--config PATH] [--debug]          interactive TUI (default)
  phrocs -d | --detach [--config PATH]      detached mode (no TUI)
  phrocs wait [--timeout N] [--json]        block until ready, crashed, or timeout
  phrocs stop [--timeout N]                 stop the detached process gracefully
  phrocs attach                             polling status client against a detached process
  phrocs --version`)
}

func parseArgs(args []string) (parsedArgs, error) {
	pa := parsedArgs{timeout: 300}
	i := 0
	// First pass: if the first arg is a known subcommand, consume it.
	if len(args) > 0 {
		switch args[0] {
		case "wait", "stop", "attach", "detach":
			pa.subcommand = args[0]
			i = 1
		}
	}
	for ; i < len(args); i++ {
		switch args[i] {
		case "--version":
			fmt.Printf("phrocs %s (%s, %s)\n", Version, Commit, BuildDate)
			os.Exit(0)
		case "-h", "--help":
			printUsage()
			os.Exit(0)
		case "--config":
			if i+1 >= len(args) {
				return pa, fmt.Errorf("--config requires a value")
			}
			pa.configPath = args[i+1]
			i++
		case "--debug":
			pa.debug = true
		case "-d", "--detach":
			pa.detach = true
		case "--timeout":
			if i+1 >= len(args) {
				return pa, fmt.Errorf("--timeout requires a value")
			}
			var n int
			if _, err := fmt.Sscanf(args[i+1], "%d", &n); err != nil {
				return pa, fmt.Errorf("--timeout: %v", err)
			}
			pa.timeout = n
			i++
		case "--json":
			pa.asJSON = true
		default:
			return pa, fmt.Errorf("unknown flag: %s", args[i])
		}
	}
	return pa, nil
}

func main() {
	pa, err := parseArgs(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		os.Exit(2)
	}

	switch pa.subcommand {
	case "wait":
		os.Exit(runWait(pa.timeout, pa.asJSON))
	case "stop":
		os.Exit(runStop(pa.timeout))
	case "attach":
		os.Exit(runAttach())
	case "detach":
		// `phrocs detach` is an alias for `phrocs -d`
		pa.detach = true
	}

	// Detached mode: either the user passed -d explicitly, or the re-exec'd
	// child landed here with PHROCS_DETACHED_CHILD set.
	if pa.detach || os.Getenv(detachedChildEnv) == "1" {
		os.Exit(runDetached(pa.configPath))
	}

	os.Exit(runInteractive(pa.configPath, pa.debug))
}

// runInteractive is the original TUI entry point — kept byte-for-byte
// compatible with pre-subcommand phrocs.
func runInteractive(configPath string, debug bool) int {
	var logger *log.Logger
	if debug {
		f, err := os.OpenFile("/tmp/phrocs-debug.log", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "phrocs: open debug log: %v\n", err)
			return 1
		}
		logger = log.New(f, "", log.LstdFlags|log.Lmicroseconds)
		logger.Println("debug logging started")
	}

	resolved, err := config.ResolveConfigPath(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}

	cfg, err := config.Load(resolved)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: load config: %v\n", err)
		return 1
	}

	mgr := process.NewManager(cfg)
	m := tui.New(mgr, cfg, resolved, logger)

	// If stdout isn't a TTY (e.g. Zed task runner, wrapped launches), open
	// /dev/tty directly so Bubble Tea can query terminal size and render.
	var opts []tea.ProgramOption
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

	// Catch SIGTERM/SIGHUP so child processes are cleaned up even if phrocs
	// is killed externally (e.g. by the OS or another process manager).
	// Bubble Tea handles SIGINT (Ctrl+C) via the TUI's quit handler.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGHUP)
	go func() {
		<-sigCh
		mgr.StopAll()
		p.Kill()
	}()

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
		return 1
	}
	socketPath := ipc.SocketPathFor(wd)

	ln, err := ipc.Listen(socketPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: ipc: %v\n", err)
		return 1
	}
	ownerInode := ipc.SocketInode(socketPath)
	defer func() {
		_ = ln.Close()
		ipc.RemoveOwnedSocket(socketPath, ownerInode)
	}()
	go func() {
		// Accept returns an error when the listener is closed on exit; ignore it.
		_ = ipc.Serve(ln, mgr)
	}()

	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "phrocs: %v\n", err)
		return 1
	}
	return 0
}
