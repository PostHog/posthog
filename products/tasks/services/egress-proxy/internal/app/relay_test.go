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
		cert:    &x509.Certificate{NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(-time.Minute)},
		timeout: 20 * time.Millisecond,
		handler: http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
			t.Error("expired relay reached the upstream handler")
		}),
	}
	server := httptest.NewServer(relay)
	defer server.Close()
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
	response, err := io.ReadAll(connection)
	if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
		t.Fatal("expired relay left the incomplete request open until the client timeout")
	}
	if len(response) > 0 && !strings.HasPrefix(string(response), "HTTP/1.1 503 ") {
		t.Fatalf("expired relay response = %q; want 503", response)
	}
}
