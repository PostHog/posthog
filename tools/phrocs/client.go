package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/posthog/posthog/phrocs/internal/ipc"
)

// detachedSocketPath returns the IPC socket path for the current working
// directory — same computation the detached process uses when binding.
func detachedSocketPath() (string, error) {
	wd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("getwd: %w", err)
	}
	return ipc.SocketPathFor(wd), nil
}

// query sends a single JSON command to the running detached process and returns
// the decoded response. Returns an error distinguishable from a protocol error
// if the socket is simply not reachable (no detached phrocs running).
func query(cmd map[string]any, timeout time.Duration) (map[string]any, error) {
	sock, err := detachedSocketPath()
	if err != nil {
		return nil, err
	}
	conn, err := net.DialTimeout("unix", sock, timeout)
	if err != nil {
		return nil, fmt.Errorf("not reachable: %w", err)
	}
	defer func() { _ = conn.Close() }()

	if err := conn.SetDeadline(time.Now().Add(timeout)); err != nil {
		return nil, err
	}
	data, err := json.Marshal(cmd)
	if err != nil {
		return nil, err
	}
	if _, err := conn.Write(append(data, '\n')); err != nil {
		return nil, err
	}
	line, err := bufio.NewReader(conn).ReadString('\n')
	if err != nil {
		return nil, err
	}
	var resp map[string]any
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		return nil, err
	}
	return resp, nil
}
