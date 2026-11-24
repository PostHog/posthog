package app

import (
	"crypto/x509"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestExpiredRelayClosesIncompleteRequest(t *testing.T) {
	relay := &Relay{
		config: RelayConfig{ServerConfig: ServerConfig{RequestTimeoutSeconds: 1}},
	}
	relay.state.Store(&relayState{cert: &x509.Certificate{NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(-time.Minute)}})
	if err := relay.Reload(); err == nil || relay.Ready() {
		t.Fatal("failed reload left an expired relay ready")
	}
	server := httptest.NewServer(relay)
	defer server.Close()
	response, err := server.Client().Get(server.URL + "/v1/probe")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("expired relay status = %d, want 503", response.StatusCode)
	}
	connection, err := net.Dial("tcp", strings.TrimPrefix(server.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	if err := connection.SetDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatal(err)
	}
	if _, err := io.WriteString(connection, "POST /v1/probe HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\nx"); err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(connection)
	if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
		t.Fatal("expired relay left the incomplete request open until the client timeout")
	}
	if len(data) > 0 && !strings.HasPrefix(string(data), "HTTP/1.1 503 ") {
		t.Fatalf("expired relay response = %q; want 503", data)
	}
}
