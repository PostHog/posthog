package app

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

func Main(mode string) {
	signal.Ignore(syscall.SIGPIPE)
	path := flag.String("config", "", "JSON configuration file")
	healthcheck := flag.String("healthcheck", "", "check live or ready status and exit")
	flag.Parse()
	if *path == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "provide -config with a JSON configuration file")
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if *healthcheck != "" {
		if err := CheckHealth(ctx, mode, *path, *healthcheck); err != nil {
			fmt.Fprintln(os.Stderr, "egress health check failed:", err)
			os.Exit(1)
		}
		return
	}
	reload := make(chan os.Signal, 1)
	signal.Notify(reload, syscall.SIGHUP)
	defer signal.Stop(reload)
	if err := Run(ctx, mode, *path, reload, os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "egress service failed:", err)
		os.Exit(1)
	}
}
