package app_test

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httptrace"
	"net/url"
	"os"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
)

func renewRelayCertificate(t *testing.T, ca, cert testCertificate, serial int64, expires time.Time) []byte {
	t.Helper()
	template := *cert.certificate
	template.SerialNumber = big.NewInt(serial)
	template.NotAfter = expires
	der, err := x509.CreateCertificate(rand.Reader, &template, ca.certificate, &cert.key.PublicKey, ca.key)
	if err != nil {
		t.Fatal(err)
	}
	return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func TestRelayReloadsTLSWhileServing(t *testing.T) {
	ca := issueTestCertificate(t, nil, false)
	serverCert := issueTestCertificate(t, &ca, true)
	clientCert := issueTestCertificate(t, &ca, false)
	serverTLS, err := tls.LoadX509KeyPair(serverCert.certFile, serverCert.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(ca.certificate)
	blocked, release := make(chan struct{}), make(chan struct{})
	unblock := sync.OnceFunc(func() { close(release) })
	defer unblock()
	closed := make(chan string, 8)
	upstream := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Test-Certificate", r.TLS.PeerCertificates[0].SerialNumber.String())
		w.Header().Set("Test-Connection", r.RemoteAddr)
		if r.URL.Path == "/blocked" {
			close(blocked)
			select {
			case <-release:
			case <-r.Context().Done():
			}
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	upstream.EnableHTTP2 = true
	upstream.TLS = &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{serverTLS}, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: roots}
	upstream.Config.ConnState = func(connection net.Conn, state http.ConnState) {
		if state == http.StateClosed {
			closed <- connection.RemoteAddr().String()
		}
	}
	upstream.StartTLS()
	t.Cleanup(upstream.Close)
	endpoint, err := url.Parse(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}
	config := app.RelayConfig{
		ServerConfig:    app.ServerConfig{ListenAddress: "127.0.0.1:0", AdminAddress: "127.0.0.1:0", RequestTimeoutSeconds: 10, ShutdownTimeoutSeconds: 5},
		Endpoint:        "https://localhost:" + endpoint.Port(),
		CertificateFile: clientCert.certFile, PrivateKeyFile: clientCert.keyFile, ServerCAFile: ca.certFile, ClientCAFile: ca.certFile,
	}
	t.Run("startup without enrollment CA", func(t *testing.T) {
		legacy := config
		legacy.ClientCAFile = ""
		relay, err := app.NewRelay(legacy, nil)
		if err != nil {
			t.Fatal(err)
		}
		defer relay.Close()
		if err := relay.Reload(); err == nil || !relay.Ready() {
			t.Fatal("reload without a client CA must fail and retain the active material")
		}
	})
	encoded, err := json.Marshal(config)
	if err != nil {
		t.Fatal(err)
	}
	path := writeTestFile(t, "relay.json", encoded)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	messages := make(chan runtimeMessage, 8)
	reload := make(chan os.Signal, 1)
	finished := make(chan struct{})
	var runErr error
	go func() {
		runErr = app.Run(ctx, "relay", path, reload, io.Discard, runtimeWriter{messages})
		close(finished)
	}()
	t.Cleanup(func() {
		unblock()
		cancel()
		select {
		case <-finished:
			if runErr != nil {
				t.Error(runErr)
			}
		case <-time.After(10 * time.Second):
			t.Error("relay did not stop")
		}
	})
	message := func(t *testing.T, expected string) runtimeMessage {
		t.Helper()
		select {
		case event := <-messages:
			if event.Message != expected {
				t.Fatalf("relay event = %+v, want %s", event, expected)
			}
			return event
		case <-finished:
			t.Fatalf("relay stopped: %v", runErr)
		case <-ctx.Done():
			t.Fatal("relay event timed out")
		}
		return runtimeMessage{}
	}
	address := message(t, "service started")
	transport := &http.Transport{}
	t.Cleanup(transport.CloseIdleConnections)
	guest := &http.Client{Transport: transport, Timeout: 5 * time.Second}
	request := func(t *testing.T, expectedSerial string, wantReused bool) *http.Response {
		t.Helper()
		reused := false
		requestContext := httptrace.WithClientTrace(ctx, &httptrace.ClientTrace{GotConn: func(info httptrace.GotConnInfo) { reused = info.Reused }})
		req, err := http.NewRequestWithContext(requestContext, http.MethodGet, "http://"+address.Listen+"/probe", nil)
		if err != nil {
			t.Fatal(err)
		}
		response, err := guest.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusNoContent || response.Header.Get("Test-Certificate") != expectedSerial || reused != wantReused {
			t.Fatalf("status=%d certificate=%s reused=%v; want 204, %s, %v", response.StatusCode, response.Header.Get("Test-Certificate"), reused, expectedSerial, wantReused)
		}
		return response
	}
	write := func(t *testing.T, path string, data []byte) {
		t.Helper()
		if err := os.WriteFile(path, data, 0600); err != nil {
			t.Fatal(err)
		}
	}
	first := request(t, clientCert.certificate.SerialNumber.String(), false)
	write(t, clientCert.certFile, renewRelayCertificate(t, ca, clientCert, 2, time.Now().Add(2*time.Hour)))
	reload <- syscall.SIGHUP
	message(t, "configuration reloaded")
	select {
	case connection := <-closed:
		if connection != first.Header.Get("Test-Connection") {
			t.Fatalf("closed connection = %s, want retired connection", connection)
		}
	case <-ctx.Done():
		t.Fatal("reload did not close the retired idle connection")
	}
	request(t, "2", true)
	blockedResult := make(chan error, 1)
	go func() {
		response, err := http.Get("http://" + address.Listen + "/blocked")
		if err == nil {
			response.Body.Close()
			if response.StatusCode != http.StatusNoContent || response.Header.Get("Test-Certificate") != "2" {
				err = context.Canceled
			}
		}
		blockedResult <- err
	}()
	select {
	case <-blocked:
	case <-ctx.Done():
		t.Fatal("upstream request did not start")
	}
	activePEM := renewRelayCertificate(t, ca, clientCert, 3, time.Now().Add(2*time.Hour))
	write(t, clientCert.certFile, activePEM)
	reload <- syscall.SIGHUP
	message(t, "configuration reloaded")
	request(t, "3", true)
	unblock()
	select {
	case err := <-blockedResult:
		if err != nil {
			t.Fatalf("reload interrupted the in-flight request: %v", err)
		}
	case <-ctx.Done():
		t.Fatal("in-flight request did not complete")
	}
	privatePEM, err := os.ReadFile(clientCert.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	caPEM, err := os.ReadFile(ca.certFile)
	if err != nil {
		t.Fatal(err)
	}
	foreign := issueTestCertificate(t, &ca, false)
	foreignCert, err := os.ReadFile(foreign.certFile)
	if err != nil {
		t.Fatal(err)
	}
	foreignKey, err := os.ReadFile(foreign.keyFile)
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name   string
		change func(*testing.T)
	}{
		{"malformed certificate", func(t *testing.T) { write(t, clientCert.certFile, []byte("invalid")) }},
		{"expired certificate", func(t *testing.T) {
			write(t, clientCert.certFile, renewRelayCertificate(t, ca, clientCert, 4, time.Now().Add(-time.Minute)))
		}},
		{"server-only certificate", func(t *testing.T) {
			leaf := *clientCert.certificate
			leaf.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
			serverOnly := clientCert
			serverOnly.certificate = &leaf
			write(t, clientCert.certFile, renewRelayCertificate(t, ca, serverOnly, 5, time.Now().Add(time.Hour)))
		}},
		{"wrong issuer", func(t *testing.T) {
			issuer := issueTestCertificate(t, nil, false)
			write(t, clientCert.certFile, renewRelayCertificate(t, issuer, clientCert, 6, time.Now().Add(time.Hour)))
		}},
		{"corrupt signature", func(t *testing.T) {
			block, _ := pem.Decode(activePEM)
			block.Bytes[len(block.Bytes)-1] ^= 1
			write(t, clientCert.certFile, pem.EncodeToMemory(block))
		}},
		{"changed key", func(t *testing.T) {
			write(t, clientCert.certFile, foreignCert)
			write(t, clientCert.keyFile, foreignKey)
		}},
		{"malformed server CA", func(t *testing.T) { write(t, ca.certFile, []byte("invalid")) }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			write(t, clientCert.certFile, activePEM)
			write(t, clientCert.keyFile, privatePEM)
			write(t, ca.certFile, caPEM)
			tc.change(t)
			reload <- syscall.SIGHUP
			message(t, "configuration reload failed; retaining active configuration")
			request(t, "3", true)
			requestStatus(t, http.DefaultClient, "http://"+address.Admin+"/readyz", "", http.StatusNoContent)
		})
	}
}
