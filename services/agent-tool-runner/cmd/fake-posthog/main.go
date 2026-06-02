// fake-posthog is a developer-only stand-in for the (not-yet-built)
// PostHog ingress side of the self-hosted-tool-runners wire protocol.
//
//	fake-posthog serve [--addr :8080]
//	    Run the fake ingress. Accepts heartbeats, queues invocations,
//	    serves polls, records results. Logs every event so you can watch
//	    the runner work in real time.
//
//	fake-posthog invoke --tool <qualified> [--args '<json>'] [--server localhost:8080]
//	    Enqueue a single tool call against any registered runner and
//	    print the result to stdout. Blocks up to 30 s waiting.
//
//	fake-posthog state [--server localhost:8080]
//	    Print a JSON snapshot of registered runners + queue depth.
//
// **Not for production use.** Skips token validation, persistence, auth.
package main

import (
	"flag"
	"fmt"
	"os"
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "serve":
		serveCmd(args)
	case "invoke":
		invokeCmd(args)
	case "state":
		stateCmd(args)
	case "-h", "--help", "help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n\n", cmd)
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `fake-posthog — dev-only stand-in for the PostHog ingress wire protocol

Usage:
  fake-posthog serve [--addr :18080]
  fake-posthog invoke --tool <qualified> [--args '<json>'] [--server <host:port>]
  fake-posthog state  [--server <host:port>]

Run with --help on each subcommand for details.
`)
}

// parseFlags is a tiny helper that lets each subcommand build a FlagSet
// without re-implementing the help-on-error glue.
func parseFlags(name string, args []string, configure func(fs *flag.FlagSet)) {
	fs := flag.NewFlagSet(name, flag.ExitOnError)
	configure(fs)
	if err := fs.Parse(args); err != nil {
		os.Exit(2)
	}
}
