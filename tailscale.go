package main

import (
	"log"
	"net"
	"strings"

	"github.com/spf13/viper"
	"tailscale.com/client/tailscale"
	"tailscale.com/tsnet"
)

var localClient *tailscale.LocalClient

func initTailNetServer() (*net.Listener, error) {
	hostname := viper.GetString("tailscale.hostname")
	srv := &tsnet.Server{
		Dir:        ".tsnet-state",
		ControlURL: viper.GetString("tailscale.controlUrl"),
		Hostname:   hostname,
		Logf: func(format string, args ...any) {
			// Show the log line with the interactive tailscale login link even when verbose is off
			if strings.Contains(format, "To start this tsnet server") {
				log.Printf(format, args...)
			}
		},
	}
	srv.Logf = log.Printf
	if err := srv.Start(); err != nil {
		return nil, err
	}
	localClient, _ = srv.LocalClient()

	l, err := srv.Listen("tcp", ":8080")
	if err != nil {
		return nil, err
	}

	log.Printf("tailnet server established at http://%s/ ...", hostname)
	return &l, nil
}
