package app_test

import (
	"bufio"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"testing"
	"time"
)

func TestGitRejectsUnreadHTTP1Bodies(t *testing.T) {
	for _, tc := range []struct {
		name, method, path, extra, payload string
		grantStatus, status                int
	}{
		{"invalid discovery", "GET", "/v1/git/example/repo.git/info/refs?service=git-upload-pack", "", "", 0, 400},
		{"denied upload", "POST", "/v1/git/example/repo.git/git-upload-pack", "", "", 404, 403},
		{"invalid compressed upload", "POST", "/v1/git/example/repo.git/git-upload-pack", "Content-Encoding: gzip\r\n", "not-gzip!!", 0, 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newGitFixture(t)
			f.grantStatus.Store(int32(tc.grantStatus))
			client := f.client(t, &f.relayCert)
			connection, err := tls.DialWithDialer(&net.Dialer{Timeout: 10 * time.Second}, "tcp", f.registration.Authority, client.Transport.(*http.Transport).TLSClientConfig)
			if err != nil {
				t.Fatal(err)
			}
			defer connection.Close()
			if err := connection.SetDeadline(time.Now().Add(10 * time.Second)); err != nil {
				t.Fatal(err)
			}
			_, err = fmt.Fprintf(connection, "%s %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\nContent-Type: application/x-git-upload-pack-request\r\nContent-Length: 100\r\n%s\r\n%s", tc.method, tc.path, f.registration.Authority, f.capability(t, f.signer, "initial"), tc.extra, tc.payload)
			if err != nil {
				t.Fatal(err)
			}
			response, err := http.ReadResponse(bufio.NewReader(connection), nil)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			if _, err := io.ReadAll(response.Body); err != nil || response.StatusCode != tc.status || !response.Close {
				t.Fatalf("status=%d close=%v body_error=%v", response.StatusCode, response.Close, err)
			}
			if f.upstreams.Load() != 0 {
				t.Fatal("rejected upload reached upstream")
			}
		})
	}
}
