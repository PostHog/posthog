package app_test

import (
	"bytes"
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
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
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

type stalledAuditOutput struct {
	bytes.Buffer
	resume chan struct{}
}

func (w *stalledAuditOutput) Write(data []byte) (int, error) {
	<-w.resume
	return w.Buffer.Write(data)
}

func TestRunRecoversAfterAuditSaturation(t *testing.T) {
	f := newProxyFixture(t)
	f.config.AuditCapacity = 2
	config, err := json.Marshal(f.config)
	if err != nil {
		t.Fatal(err)
	}
	path := writeTestFile(t, "proxy.json", config)
	output := &stalledAuditOutput{resume: make(chan struct{})}
	resume := sync.OnceFunc(func() { close(output.resume) })
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	messages := make(chan runtimeMessage, 2)
	finished := make(chan struct{})
	var runErr error
	go func() {
		runErr = app.Run(ctx, "proxy", path, nil, output, runtimeWriter{messages})
		close(finished)
	}()
	t.Cleanup(func() {
		resume()
		cancel()
		select {
		case <-finished:
			if runErr != nil {
				t.Error(runErr)
			}
		case <-time.After(10 * time.Second):
			t.Error("service did not stop")
		}
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
	f.registration.Authority = "localhost:" + endpoint.Port()
	public := "https://" + f.registration.Authority + "/v1/probe"
	admin := "http://" + address.Admin
	adminClient := &http.Client{Timeout: time.Second}
	client := f.client(t, &f.relayCert)
	token := f.capability(t, f.signer, "initial")
	requestStatus(t, client, public, token, http.StatusNoContent)
	requestStatus(t, client, public, token, http.StatusServiceUnavailable)
	for _, route := range []string{"/livez", "/readyz"} {
		requestStatus(t, adminClient, admin+route, "", http.StatusNoContent)
	}
	metrics := func() string {
		t.Helper()
		response, err := adminClient.Get(admin + "/metrics")
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		data, err := io.ReadAll(response.Body)
		if err != nil || response.StatusCode != http.StatusOK {
			t.Fatalf("metrics response: status=%d error=%v", response.StatusCode, err)
		}
		return string(data)
	}
	before := metrics()
	for _, metric := range []string{
		"egress_audit_pending_events 2\n", "egress_audit_rejected_total 1\n", "egress_audit_export_failed 0\n",
		"egress_requests_total{outcome=\"allowed\"} 1\n", "egress_requests_total{outcome=\"audit_unavailable\"} 1\n",
	} {
		if !strings.Contains(before, metric) {
			t.Fatalf("missing metric %q in %s", metric, before)
		}
	}
	resume()
	ticker := time.NewTicker(10 * time.Millisecond)
	defer ticker.Stop()
	for !strings.Contains(metrics(), "egress_audit_pending_events 0\n") {
		select {
		case <-ctx.Done():
			t.Fatal("audit output did not drain")
		case <-ticker.C:
		}
	}
	requestStatus(t, client, public, token, http.StatusNoContent)
	cancel()
	select {
	case <-finished:
		if runErr != nil {
			t.Fatal(runErr)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("service did not drain")
	}
	decoder := json.NewDecoder(&output.Buffer)
	pairs := make(map[string][]string)
	for {
		var event telemetry.Event
		if err := decoder.Decode(&event); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			t.Fatal(err)
		}
		if event.Status != http.StatusNoContent || event.RunID != f.registration.RunID || event.ExecutionID != f.registration.ExecutionID {
			t.Fatalf("unexpected audit event: %+v", event)
		}
		pairs[event.RequestID] = append(pairs[event.RequestID], event.Phase)
	}
	if len(pairs) != 2 {
		t.Fatalf("audit contains %d requests, want 2", len(pairs))
	}
	for id, phases := range pairs {
		if strings.Join(phases, ",") != "admission,completion" {
			t.Fatalf("request %s phases = %v", id, phases)
		}
	}
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
	f.registration.Authority = "localhost:" + endpoint.Port()
	client := f.client(t, &f.relayCert)
	token := f.capability(t, f.signer, "initial")
	requestStatus(t, client, public+"/v1/probe", token, http.StatusNoContent)
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
	requestStatus(t, client, public+"/v1/probe", token, http.StatusServiceUnavailable)
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
