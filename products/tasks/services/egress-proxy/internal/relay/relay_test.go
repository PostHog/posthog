package relay_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/relay"
)

type deadlineRecorder struct {
	*httptest.ResponseRecorder
	readError  error
	writeError error
}

func (r *deadlineRecorder) SetReadDeadline(time.Time) error {
	return r.readError
}

func (r *deadlineRecorder) SetWriteDeadline(time.Time) error {
	return r.writeError
}

func newDeadlineRecorder() *deadlineRecorder {
	return &deadlineRecorder{ResponseRecorder: httptest.NewRecorder()}
}

func clientTLS(t *testing.T) *tls.Config {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		NotBefore:             now.Add(-time.Hour),
		NotAfter:              now.Add(time.Hour),
		DNSNames:              []string{"localhost"},
		IPAddresses:           []net.IP{net.ParseIP("127.0.0.1")},
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign,
		ExtKeyUsage:           []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth, x509.ExtKeyUsageClientAuth},
		IsCA:                  true,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, key.Public(), key)
	if err != nil {
		t.Fatal(err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(cert)
	return &tls.Config{RootCAs: roots, Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}}
}

func newRelay(t *testing.T, upstream http.Handler, configure ...func(*relay.Config)) (http.Handler, *url.URL) {
	t.Helper()
	client := clientTLS(t)
	server := httptest.NewUnstartedServer(upstream)
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.TLS = &tls.Config{
		MinVersion:   tls.VersionTLS13,
		Certificates: client.Certificates,
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    client.RootCAs,
	}
	server.StartTLS()
	t.Cleanup(server.Close)
	endpoint, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	config := relay.Config{Endpoint: endpoint, TLSConfig: client, RequestTimeout: time.Minute}
	for _, change := range configure {
		change(&config)
	}
	handler, err := relay.New(config)
	if err != nil {
		t.Fatal(err)
	}
	return handler, endpoint
}

func TestRelayPinsOriginAndRemovesUntrustedIdentity(t *testing.T) {
	t.Setenv("HTTPS_PROXY", "https://unused.example.com")
	spoofed := []string{
		"Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Forwarded-Client-Cert",
		"X-Real-Ip", "X-Client-Cert", "X-Envoy-Peer-Metadata", "X-Ssl-Client-Verify",
		"X-Posthog-Identity", "X-Run-Id", "X-Team-Id", "X-Actor-Id", "X-Execution-Id", "X-Relay-Key",
		"Proxy-Authorization",
	}
	observed := make(chan *http.Request, 1)
	handler, endpoint := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Error(err)
		}
		if string(body) != "test payload" {
			t.Errorf("body = %q", body)
		}
		observed <- r
		w.WriteHeader(http.StatusCreated)
		_, _ = io.WriteString(w, "test result")
	}))
	expectedHost := endpoint.Host
	endpoint.Host = "unused.example.com"
	request := httptest.NewRequest(http.MethodPost, "/v1/run?field=value", strings.NewReader("test payload"))
	request.Host = "caller-selected.example.com"
	request.Header.Set("Authorization", "Bearer synthetic-capability")
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Api-Version", "test-version")
	for _, name := range spoofed {
		request.Header.Set(name, "untrusted")
	}
	response := newDeadlineRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusCreated || response.Body.String() != "test result" {
		t.Fatalf("response = %d %q", response.Code, response.Body.String())
	}
	received := <-observed
	if received.Host != expectedHost || received.URL.RequestURI() != "/v1/run?field=value" {
		t.Fatalf("destination = %q %q", received.Host, received.URL.RequestURI())
	}
	if received.Header.Get("Authorization") != "Bearer synthetic-capability" || received.Header.Get("X-Api-Version") != "test-version" {
		t.Fatal("application headers were not preserved")
	}
	if received.TLS.Version != tls.VersionTLS13 || len(received.TLS.VerifiedChains) == 0 {
		t.Fatal("request did not use verified mutual TLS")
	}
	for _, name := range spoofed {
		if received.Header.Get(name) != "" {
			t.Errorf("untrusted header %s reached the upstream", name)
		}
	}
}

func TestRelayRejectsForwardProxyAndUpgradeRequests(t *testing.T) {
	handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t.Error("rejected request reached upstream")
	}))
	cases := []struct {
		name   string
		method string
		target string
		header http.Header
		status int
	}{
		{"absolute target", http.MethodGet, "https://outside.example.com/path", nil, http.StatusBadRequest},
		{"network path", http.MethodGet, "//outside.example.com/path", nil, http.StatusBadRequest},
		{"asterisk target", http.MethodOptions, "*", nil, http.StatusBadRequest},
		{"connect", http.MethodConnect, "outside.example.com:443", nil, http.StatusMethodNotAllowed},
		{"upgrade", http.MethodGet, "/path", http.Header{"Upgrade": {"websocket"}}, http.StatusBadRequest},
		{"connection upgrade", http.MethodGet, "/path", http.Header{"Connection": {"keep-alive, UpGrAdE"}}, http.StatusBadRequest},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			request := httptest.NewRequest(tc.method, tc.target, nil)
			request.Header = tc.header
			response := newDeadlineRecorder()
			handler.ServeHTTP(response, request)
			if response.Code != tc.status {
				t.Fatalf("status = %d, want %d", response.Code, tc.status)
			}
		})
	}
}

func TestRelayReturnsRedirectWithoutFollowingIt(t *testing.T) {
	handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Location", "https://unused.example.com/redirect")
		w.WriteHeader(http.StatusFound)
	}))
	response := newDeadlineRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/redirect", nil))
	if response.Code != http.StatusFound || response.Header().Get("Location") != "https://unused.example.com/redirect" {
		t.Fatalf("response = %d, location = %q", response.Code, response.Header().Get("Location"))
	}
}

func TestRelayDoesNotReplayWriteAfterLostResponse(t *testing.T) {
	var writes atomic.Int32
	handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		writes.Add(1)
		if _, err := io.Copy(io.Discard, r.Body); err != nil {
			t.Error(err)
		}
		connection, _, err := w.(http.Hijacker).Hijack()
		if err != nil {
			t.Error(err)
			return
		}
		_ = connection.Close()
	}))
	warm := newDeadlineRecorder()
	handler.ServeHTTP(warm, httptest.NewRequest(http.MethodGet, "/warm", nil))
	if warm.Code != http.StatusNoContent {
		t.Fatalf("warmup = %d", warm.Code)
	}
	request := httptest.NewRequest(http.MethodPost, "/write", nil)
	request.Header.Set("Idempotency-Key", "synthetic-id")
	response := newDeadlineRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadGateway || response.Body.String() != "relay upstream unavailable\n" {
		t.Fatalf("response = %d %q", response.Code, response.Body.String())
	}
	if writes.Load() != 1 {
		t.Fatalf("write reached upstream %d times", writes.Load())
	}
}

func TestRelayReportsUpstreamFailure(t *testing.T) {
	var failures []relay.FailureKind
	handler, _ := newRelay(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("unverified request reached upstream")
	}), func(config *relay.Config) {
		config.TLSConfig.RootCAs = x509.NewCertPool()
		config.OnError = func(kind relay.FailureKind) { failures = append(failures, kind) }
	})
	request := httptest.NewRequest(http.MethodGet, "/probe?value=synthetic-private-data", nil)
	request.Header.Set("Authorization", "Bearer synthetic-capability")
	response := newDeadlineRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadGateway || response.Body.String() != "relay upstream unavailable\n" {
		t.Fatalf("response = %d %q", response.Code, response.Body.String())
	}
	if len(failures) != 1 || failures[0] != relay.FailureTLS {
		t.Fatalf("reported failures = %v, want one TLS verification failure", failures)
	}
}

type uploadBody struct {
	read atomic.Int64
}

func (b *uploadBody) Read(p []byte) (int, error) {
	clear(p)
	b.read.Add(int64(len(p)))
	return len(p), nil
}

func TestRelayBoundsStalledUpload(t *testing.T) {
	for _, tc := range []struct {
		name          string
		requestBudget time.Duration
		callerBudget  time.Duration
	}{
		{"relay deadline", 2 * time.Second, 0},
		{"earlier caller deadline", time.Minute, 2 * time.Second},
	} {
		t.Run(tc.name, func(t *testing.T) {
			entered, release := make(chan struct{}), make(chan struct{})
			defer close(release)
			var writes atomic.Int32
			var failures []relay.FailureKind
			handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodGet {
					w.WriteHeader(http.StatusNoContent)
					return
				}
				if writes.Add(1) == 1 {
					close(entered)
				}
				<-release
			}), func(config *relay.Config) {
				config.RequestTimeout = tc.requestBudget
				config.OnError = func(kind relay.FailureKind) { failures = append(failures, kind) }
			})
			warm := newDeadlineRecorder()
			handler.ServeHTTP(warm, httptest.NewRequest(http.MethodGet, "/warm", nil))
			if warm.Code != http.StatusNoContent {
				t.Fatalf("warmup = %d", warm.Code)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if tc.callerBudget > 0 {
				var cancelDeadline context.CancelFunc
				ctx, cancelDeadline = context.WithTimeout(ctx, tc.callerBudget)
				defer cancelDeadline()
			}
			const size = 1 << 30
			body := &uploadBody{}
			request := httptest.NewRequestWithContext(ctx, http.MethodPost, "/write", io.LimitReader(body, size))
			request.Header.Set("Idempotency-Key", "synthetic-id")
			response := newDeadlineRecorder()
			done := make(chan struct{})
			go func() {
				handler.ServeHTTP(response, request)
				close(done)
			}()
			watchdog := time.NewTimer(10 * time.Second)
			defer watchdog.Stop()
			select {
			case <-entered:
			case <-done:
				t.Fatal("request ended before upstream accepted the upload")
			case <-watchdog.C:
				t.Fatal("upstream did not receive the upload")
			}
			select {
			case <-done:
			case <-watchdog.C:
				t.Fatal("stalled upload did not end at its deadline")
			}
			if response.Code != http.StatusBadGateway || response.Body.String() != "relay upstream unavailable\n" {
				t.Fatalf("response = %d %q", response.Code, response.Body.String())
			}
			if len(failures) != 1 || failures[0] != relay.FailureTimeout {
				t.Fatalf("reported failures = %v, want one timeout", failures)
			}
			if writes.Load() != 1 || body.read.Load() >= size {
				t.Fatalf("upload attempts = %d, bytes read = %d; want one incomplete upload", writes.Load(), body.read.Load())
			}
		})
	}
}

func TestRelayBoundsStalledResponse(t *testing.T) {
	for _, tc := range []struct {
		name          string
		requestBudget time.Duration
		callerBudget  time.Duration
	}{
		{"relay deadline", 2 * time.Second, 0},
		{"earlier caller deadline", time.Minute, 2 * time.Second},
	} {
		t.Run(tc.name, func(t *testing.T) {
			const size = 1 << 30
			entered, done := make(chan struct{}), make(chan struct{})
			upstreamCanceled := make(chan error, 1)
			var sent atomic.Int64
			handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				close(entered)
				n, _ := io.CopyN(w, &uploadBody{}, size)
				sent.Store(n)
				<-r.Context().Done()
				upstreamCanceled <- r.Context().Err()
			}), func(config *relay.Config) {
				config.RequestTimeout = tc.requestBudget
			})
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				defer close(done)
				if tc.callerBudget > 0 {
					ctx, cancel := context.WithTimeout(r.Context(), tc.callerBudget)
					defer cancel()
					r = r.WithContext(ctx)
				}
				handler.ServeHTTP(w, r)
			}))
			server.Config.ErrorLog = log.New(io.Discard, "", 0)
			server.Start()
			t.Cleanup(server.Close)
			connection, err := net.DialTimeout("tcp", server.Listener.Addr().String(), 5*time.Second)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = connection.Close() })
			if _, err := io.WriteString(connection, "GET /stream HTTP/1.1\r\nHost: relay.example.com\r\n\r\n"); err != nil {
				t.Fatal(err)
			}
			watchdog := time.NewTimer(10 * time.Second)
			defer watchdog.Stop()
			select {
			case <-entered:
			case <-watchdog.C:
				t.Fatal("upstream did not start the response")
			}
			select {
			case <-done:
			case <-watchdog.C:
				t.Fatal("stalled response did not end at its deadline")
			}
			select {
			case err := <-upstreamCanceled:
				if !errors.Is(err, context.Canceled) {
					t.Fatalf("upstream context error = %v, want cancellation", err)
				}
			case <-watchdog.C:
				t.Fatal("stalled response did not cancel upstream")
			}
			if sent.Load() == 0 || sent.Load() >= size {
				t.Fatalf("upstream sent %d bytes; want an incomplete response", sent.Load())
			}
		})
	}
}

func TestRelayBoundsIncompleteGuestBody(t *testing.T) {
	for _, tc := range []struct {
		name          string
		requestBudget time.Duration
		callerBudget  time.Duration
		rejected      bool
	}{
		{"relay deadline", 2 * time.Second, 0, false},
		{"earlier caller deadline", time.Minute, 2 * time.Second, false},
		{"rejected request", 2 * time.Second, 0, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			done := make(chan struct{})
			var dispatched atomic.Bool
			handler, _ := newRelay(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				dispatched.Store(true)
				_, _ = io.Copy(io.Discard, r.Body)
			}), func(config *relay.Config) {
				config.RequestTimeout = tc.requestBudget
			})
			server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				defer close(done)
				if tc.callerBudget > 0 {
					ctx, cancel := context.WithTimeout(r.Context(), tc.callerBudget)
					defer cancel()
					r = r.WithContext(ctx)
				}
				handler.ServeHTTP(w, r)
			}))
			server.Config.ErrorLog = log.New(io.Discard, "", 0)
			server.Start()
			t.Cleanup(server.Close)
			connection, err := net.DialTimeout("tcp", server.Listener.Addr().String(), 5*time.Second)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = connection.Close() })
			headers := "POST /write HTTP/1.1\r\nHost: relay.example.com\r\nContent-Length: 65536\r\n"
			if tc.rejected {
				headers += "Upgrade: websocket\r\n"
			}
			if _, err := io.WriteString(connection, headers+"\r\n"+strings.Repeat("x", 32768)); err != nil {
				t.Fatal(err)
			}
			closed := make(chan error, 1)
			go func() {
				_, err := io.Copy(io.Discard, connection)
				closed <- err
			}()
			watchdog := time.NewTimer(10 * time.Second)
			defer watchdog.Stop()
			select {
			case <-done:
			case <-watchdog.C:
				t.Fatal("incomplete guest body kept the handler past its deadline")
			}
			select {
			case err := <-closed:
				if err != nil {
					t.Fatalf("guest connection did not close cleanly: %v", err)
				}
			case <-watchdog.C:
				t.Fatal("incomplete guest body kept the connection open after the handler ended")
			}
			if dispatched.Load() == tc.rejected {
				t.Fatalf("upstream dispatched = %v, request rejected = %v", dispatched.Load(), tc.rejected)
			}
		})
	}
}

func TestRelayAbortsWhenDeadlineCannotBeSet(t *testing.T) {
	for _, tc := range []struct {
		name        string
		readError   error
		writeError  error
		unsupported bool
	}{
		{"unsupported read deadline", nil, nil, true},
		{"failed read deadline", errors.New("synthetic read deadline failure"), nil, false},
		{"unsupported write deadline", nil, http.ErrNotSupported, false},
		{"failed write deadline", nil, errors.New("synthetic write deadline failure"), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var dispatched atomic.Bool
			var failures []relay.FailureKind
			handler, _ := newRelay(t, http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
				dispatched.Store(true)
			}), func(config *relay.Config) {
				config.OnError = func(kind relay.FailureKind) { failures = append(failures, kind) }
			})
			response := newDeadlineRecorder()
			response.readError, response.writeError = tc.readError, tc.writeError
			var writer http.ResponseWriter = response
			if tc.unsupported {
				writer = response.ResponseRecorder
			}
			var aborted any
			func() {
				defer func() { aborted = recover() }()
				handler.ServeHTTP(writer, httptest.NewRequest(http.MethodGet, "/stream", nil))
			}()
			if aborted != http.ErrAbortHandler || dispatched.Load() || response.Body.Len() != 0 {
				t.Fatalf("abort = %v, upstream dispatched = %v, response body = %q", aborted, dispatched.Load(), response.Body.String())
			}
			if len(failures) != 1 || failures[0] != relay.FailureOther {
				t.Fatalf("reported failures = %v, want one deadline setup failure", failures)
			}
		})
	}
}

func TestRelayRejectsUnsafeConfiguration(t *testing.T) {
	client := clientTLS(t)
	cases := []struct {
		name   string
		change func(*relay.Config)
	}{
		{"missing endpoint", func(c *relay.Config) { c.Endpoint = nil }},
		{"http endpoint", func(c *relay.Config) { c.Endpoint.Scheme = "http" }},
		{"missing host", func(c *relay.Config) { c.Endpoint.Host = "" }},
		{"userinfo", func(c *relay.Config) { c.Endpoint.User = url.User("user") }},
		{"query", func(c *relay.Config) { c.Endpoint.RawQuery = "credential=synthetic" }},
		{"empty query", func(c *relay.Config) { c.Endpoint.ForceQuery = true }},
		{"path", func(c *relay.Config) { c.Endpoint.Path = "/route" }},
		{"encoded path", func(c *relay.Config) { c.Endpoint.RawPath = "/%2f" }},
		{"fragment", func(c *relay.Config) { c.Endpoint.Fragment = "fragment" }},
		{"opaque", func(c *relay.Config) { c.Endpoint.Opaque = "//run.example.com" }},
		{"empty port", func(c *relay.Config) { c.Endpoint.Host = "run.example.com:" }},
		{"invalid port", func(c *relay.Config) { c.Endpoint.Host = "run.example.com:65536" }},
		{"ambiguous port", func(c *relay.Config) { c.Endpoint.Host = "run.example.com:0443" }},
		{"userinfo host", func(c *relay.Config) { c.Endpoint.Host = "run.example.com@other.example.com" }},
		{"invalid label", func(c *relay.Config) { c.Endpoint.Host = "run..example.com" }},
		{"rooted host", func(c *relay.Config) { c.Endpoint.Host = "run.example.com." }},
		{"uppercase host", func(c *relay.Config) { c.Endpoint.Host = "RUN.example.com" }},
		{"missing TLS", func(c *relay.Config) { c.TLSConfig = nil }},
		{"unverified TLS", func(c *relay.Config) { c.TLSConfig.InsecureSkipVerify = true }},
		{"missing client certificate", func(c *relay.Config) { c.TLSConfig.Certificates = nil }},
		{"old TLS minimum", func(c *relay.Config) { c.TLSConfig.MinVersion = tls.VersionTLS12 }},
		{"old TLS maximum", func(c *relay.Config) { c.TLSConfig.MaxVersion = tls.VersionTLS12 }},
		{"foreign SNI", func(c *relay.Config) { c.TLSConfig.ServerName = "other.example.com" }},
		{"missing request timeout", func(c *relay.Config) { c.RequestTimeout = 0 }},
		{"negative request timeout", func(c *relay.Config) { c.RequestTimeout = -time.Second }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			config := relay.Config{Endpoint: &url.URL{Scheme: "https", Host: "run.example.com"}, TLSConfig: client.Clone(), RequestTimeout: time.Minute}
			tc.change(&config)
			if _, err := relay.New(config); err == nil {
				t.Fatal("unsafe configuration accepted")
			}
		})
	}
}
