package app_test

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"encoding/pem"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

type gitFixture struct {
	*proxyFixture
	grantStatus    atomic.Int32
	upstreamStatus atomic.Int32
	proxyStatus    atomic.Int32
	grants         atomic.Int32
	tunnels        atomic.Int32
	upstreams      atomic.Int32
	version        atomic.Int32
	truncate       atomic.Bool
}

func newGitFixture(t *testing.T) *gitFixture {
	t.Helper()
	f := &gitFixture{}
	f.proxyFixture = newProxyFixture(t, func(p *proxyFixture) {
		f.proxyFixture = p
		ca := issueTestCertificate(t, nil, false)
		certificate := issueTestCertificate(t, &ca, true, "github.com")
		cert, err := tls.LoadX509KeyPair(certificate.certFile, certificate.keyFile)
		if err != nil {
			t.Fatal(err)
		}
		upstream := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			f.upstreams.Add(1)
			user, token, ok := r.BasicAuth()
			if !ok || user != "x-access-token" || token != f.upstreamToken() || r.Host != "github.com" ||
				r.Header.Get("Cookie") != "" || r.Header.Get("X-Api-Key") != "" {
				t.Error("upstream received unexpected credentials or caller headers")
			}
			if code := f.upstreamStatus.Load(); code != 0 {
				w.Header().Set("Location", "https://example.com/secret")
				w.WriteHeader(int(code))
				_, _ = io.WriteString(w, "synthetic-private-upstream-error")
				return
			}
			w.Header().Set("Content-Type", "application/x-git-upload-pack-advertisement")
			if r.Method == http.MethodPost {
				w.Header().Set("Content-Type", "application/x-git-upload-pack-result")
			}
			if f.truncate.Load() {
				w.Header().Set("Content-Length", "10000")
			}
			_, _ = io.Copy(io.Discard, r.Body)
			_, _ = io.WriteString(w, "0000")
		}))
		upstream.TLS = &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS12}
		upstream.StartTLS()
		t.Cleanup(upstream.Close)
		endpoint, _ := url.Parse(upstream.URL)
		smokescreen := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			f.tunnels.Add(1)
			if r.Method != http.MethodConnect || r.Host != "github.com:443" || r.Header.Get("Authorization") != "" || r.Header.Get("Proxy-Authorization") != "" {
				t.Error("unexpected CONNECT destination or authentication")
				w.WriteHeader(http.StatusForbidden)
				return
			}
			if code := f.proxyStatus.Load(); code != 0 {
				w.WriteHeader(int(code))
				return
			}
			out, err := net.DialTimeout("tcp", endpoint.Host, 10*time.Second)
			if err != nil {
				w.WriteHeader(http.StatusBadGateway)
				return
			}
			defer out.Close()
			in, buffer, err := w.(http.Hijacker).Hijack()
			if err != nil {
				return
			}
			defer in.Close()
			_, _ = buffer.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n")
			_ = buffer.Flush()
			done := make(chan struct{})
			go func() {
				_, _ = io.Copy(out, buffer)
				_ = out.Close()
				close(done)
			}()
			_, _ = io.Copy(in, out)
			_ = in.Close()
			<-done
		}))
		t.Cleanup(smokescreen.Close)
		key := "synthetic-git-grant-signing-key-000000000"
		grants := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			f.grants.Add(1)
			token, err := jwt.Parse(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), func(_ *jwt.Token) (any, error) {
				return []byte(key), nil
			}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithAudience("posthog:agent_egress_credentials"))
			if err != nil {
				t.Error("grant lookup used an invalid identity")
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			claims := token.Claims.(jwt.MapClaims)
			if claims["sub"] != p.registration.RunID || claims["execution_id"] != p.registration.ExecutionID ||
				claims["team_id"] != float64(p.registration.TeamID) || claims["region"] != "test-region" {
				t.Error("grant lookup lost run scope")
			}
			if code := f.grantStatus.Load(); code != 0 {
				w.WriteHeader(int(code))
				return
			}
			if claims["repository"] != "example/repo" {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			registration := p.registration
			registration.LeaseExpiresAt = time.Now().Add(30 * time.Second)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"registration": struct {
					identity.Registration
					Region string `json:"region"`
				}{registration, "test-region"},
				"repository": "example/repo", "token": f.upstreamToken(), "credential_version": f.credentialVersion(),
				"expires_at": time.Now().Add(time.Hour),
			})
		}))
		t.Cleanup(grants.Close)
		p.config.GitRead = &app.GitReadConfig{
			GrantURL: grants.URL, GrantSigningKeyFile: writeTestFile(t, "grant-key", []byte(key)),
			GrantCAFile:    writeTestFile(t, "grant-ca.pem", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: grants.Certificate().Raw})),
			SmokescreenURL: smokescreen.URL, UpstreamCAFile: ca.certFile,
		}
	})
	return f
}

func (f *gitFixture) upstreamToken() string {
	if f.version.Load() > 0 {
		return "synthetic-github-token-replacement"
	}
	return "synthetic-github-token-initial"
}

func (f *gitFixture) credentialVersion() string {
	if f.version.Load() > 0 {
		return "00000000-0000-4000-8000-000000000004"
	}
	return "00000000-0000-4000-8000-000000000003"
}

func TestProxyGitReadAuthorizationAndRotation(t *testing.T) {
	f := newGitFixture(t)
	client := f.client(t, &f.relayCert)
	token := f.capability(t, f.signer, "initial")
	path := "/v1/git/example/repo.git/info/refs?service=git-upload-pack"
	for _, version := range []int32{0, 1} {
		f.version.Store(version)
		method, target, payload := http.MethodGet, path, ""
		if version == 1 {
			method, target, payload = http.MethodPost, "/v1/git/example/repo.git/git-upload-pack", "0000"
		}
		request, _ := http.NewRequestWithContext(t.Context(), method, f.endpoint+target, strings.NewReader(payload))
		if version == 1 {
			request.Header.Set("Content-Type", "application/x-git-upload-pack-request")
		}
		request.Header.Set("Authorization", "Bearer "+token)
		request.Header.Set("Cookie", "untrusted-cookie")
		request.Header.Set("X-Api-Key", "untrusted-key")
		response, err := client.Do(request)
		if err != nil {
			t.Fatal(err)
		}
		body, err := io.ReadAll(response.Body)
		response.Body.Close()
		if err != nil || response.StatusCode != http.StatusOK || string(body) != "0000" {
			t.Fatalf("Git response: status=%d body=%q error=%v", response.StatusCode, body, err)
		}
	}
	for _, tc := range []struct {
		name, path, token string
		status            int
	}{
		{"missing identity", path, "", http.StatusUnauthorized},
		{"foreign repository", strings.Replace(path, "example/repo", "example/other", 1), token, http.StatusForbidden},
		{"push", "/v1/git/example/repo.git/info/refs?service=git-receive-pack", token, http.StatusBadRequest},
	} {
		t.Run(tc.name, func(t *testing.T) {
			requestStatus(t, client, f.endpoint+tc.path, tc.token, tc.status)
		})
	}
	foreign := issueTestCertificate(t, &f.ca, false)
	requestStatus(t, f.client(t, &foreign), f.endpoint+path, token, http.StatusUnauthorized)
	if f.grants.Load() != 3 || f.upstreams.Load() != 2 || f.tunnels.Load() == 0 {
		t.Fatalf("grant/upstream/tunnel requests = %d/%d/%d", f.grants.Load(), f.upstreams.Load(), f.tunnels.Load())
	}
	if err := f.audit.Close(t.Context()); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(f.auditOutput.Bytes(), []byte(token)) || bytes.Contains(f.auditOutput.Bytes(), []byte("synthetic-github")) ||
		bytes.Contains(f.auditOutput.Bytes(), []byte("example/repo")) {
		t.Fatal("audit exposed credentials or repository")
	}
	decoder := json.NewDecoder(bytes.NewReader(f.auditOutput.Bytes()))
	for i := 0; i < 12; i++ {
		var event telemetry.Event
		if err := decoder.Decode(&event); err != nil {
			t.Fatal(err)
		}
		if i < 4 && (event.Operation != "git_read" || event.CredentialVersion == "" || event.Outcome != "allowed") {
			t.Fatalf("invalid Git audit: %+v", event)
		}
		if i < 4 && i%2 == 1 && event.BytesSent != 4 {
			t.Fatalf("missing byte count: %+v", event)
		}
		if i < 2 && event.CredentialVersion != "00000000-0000-4000-8000-000000000003" ||
			i >= 2 && i < 4 && event.CredentialVersion != f.credentialVersion() ||
			i == 3 && event.BytesReceived != 4 {
			t.Fatalf("incorrect credential version or received bytes: %+v", event)
		}
	}
}

func TestProxyGitFailuresStayClosed(t *testing.T) {
	for _, tc := range []struct {
		name   string
		change func(*gitFixture)
		status int
	}{
		{"grant revoked", func(f *gitFixture) { f.grantStatus.Store(404) }, 403},
		{"grant outage", func(f *gitFixture) { f.grantStatus.Store(503) }, 503},
		{"upstream error", func(f *gitFixture) { f.upstreamStatus.Store(500) }, 502},
		{"redirect", func(f *gitFixture) { f.upstreamStatus.Store(302) }, 502},
		{"Smokescreen denial", func(f *gitFixture) { f.proxyStatus.Store(403) }, 502},
		{"untrusted upstream", func(f *gitFixture) { f.config.GitRead.UpstreamCAFile = f.ca.certFile }, 502},
		{"untrusted grant endpoint", func(f *gitFixture) { f.config.GitRead.GrantCAFile = f.ca.certFile }, 503},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newGitFixture(t)
			tc.change(f)
			if err := f.proxy.Reload(); err != nil {
				t.Fatal(err)
			}
			token := f.capability(t, f.signer, "initial")
			response := requestStatus(t, f.client(t, &f.relayCert), f.endpoint+"/v1/git/example/repo.git/info/refs?service=git-upload-pack", token, tc.status)
			if response.Header.Get("Location") != "" || response.Header.Get("Cache-Control") != "no-store" {
				t.Fatal("unsafe failure headers")
			}
			if err := f.audit.Close(t.Context()); err != nil {
				t.Fatal(err)
			}
			decoder := json.NewDecoder(bytes.NewReader(f.auditOutput.Bytes()))
			for i := 0; i < 2; i++ {
				var event telemetry.Event
				if err := decoder.Decode(&event); err != nil {
					t.Fatal(err)
				}
				if i == 1 && (event.Status != tc.status || event.Outcome == "allowed") {
					t.Fatalf("false successful completion: %+v", event)
				}
			}
		})
	}
}

func TestProxyGitTruncatedResponseAndAuditFailure(t *testing.T) {
	f := newGitFixture(t)
	f.truncate.Store(true)
	client := f.client(t, &f.relayCert)
	token := f.capability(t, f.signer, "initial")
	request, _ := http.NewRequestWithContext(t.Context(), http.MethodGet, f.endpoint+"/v1/git/example/repo.git/info/refs?service=git-upload-pack", nil)
	request.Header.Set("Authorization", "Bearer "+token)
	response, err := client.Do(request)
	if err == nil {
		_, err = io.ReadAll(response.Body)
		response.Body.Close()
	}
	if err == nil {
		t.Fatal("incomplete pack was accepted")
	}
	if err := f.audit.Close(t.Context()); err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(bytes.NewReader(f.auditOutput.Bytes()))
	var admission, completion telemetry.Event
	if decoder.Decode(&admission) != nil || decoder.Decode(&completion) != nil ||
		admission.Outcome != "allowed" || completion.Outcome != "interrupted" || completion.BytesSent != 4 {
		t.Fatal("interrupted transfer missing from audit")
	}
	requestStatus(t, client, request.URL.String(), token, 503)
	if f.upstreams.Load() != 1 {
		t.Fatal("Git dispatched without audit reservation")
	}
}

func TestProxyGitConfigurationFailsClosed(t *testing.T) {
	f := newGitFixture(t)
	token := f.capability(t, f.signer, "initial")
	client := f.client(t, &f.relayCert)
	config := *f.config.GitRead
	for _, tc := range []struct {
		name   string
		change func(*app.GitReadConfig)
	}{
		{"missing proxy", func(c *app.GitReadConfig) { c.SmokescreenURL = "" }},
		{"proxy credentials", func(c *app.GitReadConfig) { c.SmokescreenURL = "http://user:secret@example.com" }},
		{"plaintext grant", func(c *app.GitReadConfig) { c.GrantURL = "http://example.com" }},
		{"missing key", func(c *app.GitReadConfig) { c.GrantSigningKeyFile = "" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			copy := config
			tc.change(&copy)
			*f.config.GitRead = copy
			if err := f.proxy.Reload(); err == nil {
				t.Fatal("invalid Git configuration accepted")
			}
			requestStatus(t, client, f.endpoint+"/v1/git/example/repo.git/info/refs?service=git-upload-pack", token, 200)
		})
	}
}
