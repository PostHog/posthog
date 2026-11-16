package app_test

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"syscall"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
)

type runtimeMessage struct {
	Message string `json:"msg"`
	Listen  string `json:"listen_address"`
	Admin   string `json:"admin_address"`
	Error   string `json:"error"`
}

type runtimeWriter struct {
	messages chan runtimeMessage
}

func (w runtimeWriter) Write(data []byte) (int, error) {
	var message runtimeMessage
	if json.Unmarshal(data, &message) == nil {
		switch message.Message {
		case "service started", "configuration reloaded", "configuration reload failed; retaining active configuration":
			w.messages <- message
		}
	}
	return len(data), nil
}

func TestRunSeparatesAdministrationAndStopsListeners(t *testing.T) {
	f := newProxyFixture(t)
	config, err := json.Marshal(f.config)
	if err != nil {
		t.Fatal(err)
	}
	path := writeTestFile(t, "proxy.json", config)
	ctx, cancel := context.WithCancel(t.Context())
	messages := make(chan runtimeMessage, 2)
	finished := make(chan struct{})
	var runErr error
	reload := make(chan os.Signal, 1)
	go func() {
		runErr = app.Run(ctx, "proxy", path, reload, io.Discard, runtimeWriter{messages})
		close(finished)
	}()
	t.Cleanup(func() {
		cancel()
		select {
		case <-finished:
		case <-time.After(30 * time.Second):
			t.Error("service did not stop during cleanup")
		}
	})
	var address runtimeMessage
	select {
	case address = <-messages:
	case <-finished:
		t.Fatalf("startup failed: %v", runErr)
	case <-time.After(30 * time.Second):
		t.Fatal("service did not start")
	}
	endpoint, err := url.Parse("https://" + address.Listen)
	if err != nil {
		t.Fatal(err)
	}
	f.registration.Authority = "localhost:" + endpoint.Port()
	public := "https://" + f.registration.Authority
	token := f.capability(t, f.signer, "initial")
	client := f.client(t, &f.relayCert)
	for _, route := range []string{"/livez", "/readyz"} {
		requestStatus(t, http.DefaultClient, "http://"+address.Admin+route, "", http.StatusNoContent)
		requestStatus(t, client, public+route, token, http.StatusNotFound)
	}
	requestStatus(t, client, public+"/v1/probe", token, http.StatusNoContent)
	requestStatus(t, http.DefaultClient, "http://"+address.Admin+"/metrics", "", http.StatusOK)
	requestStatus(t, client, public+"/metrics", token, http.StatusNotFound)
	nextSigner, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	writeKeyBundle(t, f.config.VerificationKeysFile, map[string]*rsa.PrivateKey{"next": nextSigner})
	reload <- syscall.SIGHUP
	select {
	case message := <-messages:
		if message.Message != "configuration reloaded" {
			t.Fatalf("reload failed: %s", message.Message)
		}
	case <-finished:
		t.Fatalf("service stopped during reload: %v", runErr)
	case <-time.After(30 * time.Second):
		t.Fatal("service did not acknowledge reload")
	}
	requestStatus(t, client, public+"/v1/probe", token, http.StatusUnauthorized)
	requestStatus(t, client, public+"/v1/probe", f.capability(t, nextSigner, "next"), http.StatusNoContent)
	if err := os.WriteFile(f.config.VerificationKeysFile, []byte(`{"next":"synthetic-secret-material"}`), 0600); err != nil {
		t.Fatal(err)
	}
	reload <- syscall.SIGHUP
	select {
	case message := <-messages:
		if message.Message != "configuration reload failed; retaining active configuration" || message.Error != "invalid verification key bundle" {
			t.Fatalf("expected a sanitized reload failure reason, got %+v", message)
		}
	case <-finished:
		t.Fatalf("service stopped during failed reload: %v", runErr)
	case <-time.After(30 * time.Second):
		t.Fatal("service did not report reload failure")
	}
	requestStatus(t, client, public+"/v1/probe", f.capability(t, nextSigner, "next"), http.StatusNoContent)
	cancel()
	select {
	case <-finished:
		if runErr != nil {
			t.Fatal(runErr)
		}
	case <-time.After(30 * time.Second):
		t.Fatal("service did not stop")
	}
	if response, err := http.Get("http://" + address.Admin + "/livez"); err == nil {
		response.Body.Close()
		t.Fatal("administration listener remained open after shutdown")
	}
	if response, err := client.Get(public + "/v1/probe"); err == nil {
		response.Body.Close()
		t.Fatal("request listener remained open after shutdown")
	}
}

func TestProxyMainHandlesBrokenAuditPipe(t *testing.T) {
	if path := os.Getenv("EGRESS_PROXY_TEST_CONFIG"); path != "" {
		flag.CommandLine = flag.NewFlagSet("egress-proxy", flag.ExitOnError)
		os.Args = []string{"egress-proxy", "-config", path}
		app.Main("proxy")
		return
	}
	f := newProxyFixture(t)
	config, err := json.Marshal(f.config)
	if err != nil {
		t.Fatal(err)
	}
	path := writeTestFile(t, "proxy.json", config)
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	reader.Close()
	defer writer.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, executable, "-test.run=^TestProxyMainHandlesBrokenAuditPipe$")
	command.Env = append(os.Environ(), "EGRESS_PROXY_TEST_CONFIG="+path)
	messages := make(chan runtimeMessage, 2)
	command.Stderr, command.Stdout = runtimeWriter{messages}, writer
	if err := command.Start(); err != nil {
		t.Fatal(err)
	}
	writer.Close()
	finished := make(chan struct{})
	var runErr error
	go func() {
		runErr = command.Wait()
		close(finished)
	}()
	t.Cleanup(func() {
		cancel()
		<-finished
	})
	var address runtimeMessage
	select {
	case address = <-messages:
	case <-finished:
		t.Fatalf("startup failed: %v", runErr)
	case <-ctx.Done():
		t.Fatal("service did not start")
	}
	endpoint, err := url.Parse("https://" + address.Listen)
	if err != nil {
		t.Fatal(err)
	}
	public := "https://localhost:" + endpoint.Port()
	client := f.client(t, &f.relayCert)
	requestStatus(t, client, public+"/v1/probe", "", http.StatusUnauthorized)
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-finished:
			t.Fatalf("closed audit pipe terminated the service: %v", runErr)
		case <-ctx.Done():
			t.Fatal("audit failure did not fail readiness")
		case <-ticker.C:
			response, err := http.Get("http://" + address.Admin + "/readyz")
			if err != nil {
				continue
			}
			response.Body.Close()
			if response.StatusCode != http.StatusServiceUnavailable {
				continue
			}
		}
		break
	}
	requestStatus(t, client, public+"/v1/probe", "", http.StatusServiceUnavailable)
	requestStatus(t, http.DefaultClient, "http://"+address.Admin+"/livez", "", http.StatusServiceUnavailable)
	if err := command.Process.Signal(syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	select {
	case <-finished:
		var exit *exec.ExitError
		if !errors.As(runErr, &exit) || exit.ExitCode() != 1 {
			t.Fatalf("exit error = %v; want exit 1 for failed audit drain", runErr)
		}
	case <-ctx.Done():
		t.Fatal("service did not stop")
	}
}
