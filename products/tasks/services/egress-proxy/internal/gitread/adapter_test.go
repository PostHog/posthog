package gitread

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/tls"
	"errors"
	"io"
	"math/rand"
	"net"
	"net/http"
	"net/http/cgi"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

func registration() identity.Registration {
	return identity.Registration{TeamID: 1, ActorID: 2, ActorEpoch: 1, RunID: "run-example", ExecutionID: "execution-example",
		Authority: "run-example.egress.example.com", RelayKeySHA256: "example-relay-key", LeaseExpiresAt: time.Now().Add(time.Minute)}
}

func readGrant(reg identity.Registration) ReadGrant {
	return ReadGrant{Identity: reg, Repository: "example/repo", Token: "synthetic-upstream-token",
		CredentialVersion: "version-1", ExpiresAt: time.Now().Add(time.Minute)}
}

func transport(t *testing.T, upstream *httptest.Server) *http.Transport {
	t.Helper()
	u, err := url.Parse(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}
	result := upstream.Client().Transport.(*http.Transport).Clone()
	result.TLSClientConfig = result.TLSClientConfig.Clone()
	result.TLSClientConfig.ServerName = "example.com"
	result.TLSClientConfig.MinVersion = tls.VersionTLS12
	result.Proxy = nil
	result.DialContext = func(ctx context.Context, network, address string) (net.Conn, error) {
		if address != "github.com:443" {
			t.Errorf("unexpected upstream address %q", address)
			return nil, errors.New("unexpected upstream")
		}
		return (&net.Dialer{}).DialContext(ctx, network, u.Host)
	}
	t.Cleanup(result.CloseIdleConnections)
	return result
}

func adapterServer(t *testing.T, reg identity.Registration, upstream *httptest.Server, lookup Lookup, observers ...func(*http.Request)) *httptest.Server {
	t.Helper()
	adapter, err := New(Config{Lookup: lookup, Transport: transport(t, upstream), LookupTimeout: time.Second, RequestTimeout: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for _, observe := range observers {
			observe(r)
		}
		op, err := adapter.Prepare(r, reg)
		if err == nil {
			err = op.Forward(w)
		}
		if err != nil {
			status := http.StatusBadGateway
			switch {
			case errors.Is(err, ErrDenied):
				status = http.StatusForbidden
			case errors.Is(err, ErrUnavailable):
				status = http.StatusServiceUnavailable
			case errors.Is(err, ErrInvalidRequest):
				status = http.StatusBadRequest
			}
			http.Error(w, err.Error(), status)
		}
	}))
	t.Cleanup(server.Close)
	return server
}

func TestReadProtocolAndCredentials(t *testing.T) {
	reg := registration()
	grant := readGrant(reg)
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		t.Run(method, func(t *testing.T) {
			responseType := "application/x-git-upload-pack-result"
			suffix, upstreamPath := "/git-upload-pack", "/example/repo.git/git-upload-pack"
			body := "0000"
			if method == http.MethodGet {
				responseType = "application/x-git-upload-pack-advertisement"
				suffix, upstreamPath, body = "/info/refs?service=git-upload-pack", "/example/repo.git/info/refs", ""
			}
			var calls atomic.Int32
			upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				user, token, ok := r.BasicAuth()
				if !ok || user != "x-access-token" || token != grant.Token || r.Host != "github.com" || r.URL.Path != upstreamPath {
					t.Error("upstream identity or path mismatch")
				}
				for _, header := range []string{"Cookie", "Proxy-Authorization", "X-Forwarded-Host", "X-Api-Key", "X-Posthog-Team", "Range"} {
					if r.Header.Get(header) != "" {
						t.Errorf("caller header forwarded: %s", header)
					}
				}
				if r.Header.Get("Git-Protocol") != "version=2" {
					t.Error("Git protocol lost")
				}
				payload, _ := io.ReadAll(r.Body)
				if string(payload) != body {
					t.Error("Git request changed")
				}
				w.Header().Set("Content-Type", responseType)
				w.Header().Set("Set-Cookie", "upstream-cookie=secret")
				w.Header().Set("X-Upstream-Secret", "not-for-the-guest")
				_, _ = io.WriteString(w, "0000")
			}))
			defer upstream.Close()
			server := adapterServer(t, reg, upstream, func(_ context.Context, request LookupRequest) (ReadGrant, error) {
				if request.Identity != reg || request.Repository != "example/repo" {
					t.Error("grant lookup lost scope")
				}
				return grant, nil
			})
			request, _ := http.NewRequest(method, server.URL+"/v1/git/Example/Repo.git"+suffix, strings.NewReader(body))
			request.Header.Set("Authorization", "Bearer synthetic-run-capability")
			request.Header.Set("Git-Protocol", "version=2")
			request.Header.Set("Content-Type", "application/x-git-upload-pack-request")
			for _, header := range []string{"Cookie", "Proxy-Authorization", "X-Forwarded-Host", "X-Api-Key", "X-Posthog-Team", "Range"} {
				request.Header.Set(header, "untrusted")
			}
			response, err := server.Client().Do(request)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			payload, _ := io.ReadAll(response.Body)
			if response.StatusCode != 200 || string(payload) != "0000" || calls.Load() != 1 ||
				response.Header.Get("Set-Cookie") != "" || response.Header.Get("X-Upstream-Secret") != "" {
				t.Fatalf("unexpected response: status=%d calls=%d", response.StatusCode, calls.Load())
			}
		})
	}
}

func TestRejectBeforeDispatch(t *testing.T) {
	reg := registration()
	var calls atomic.Int32
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls.Add(1) }))
	defer upstream.Close()
	cases := []struct {
		name   string
		mutate func(*http.Request, *ReadGrant)
		lookup error
		want   error
	}{
		{"foreign_team", func(_ *http.Request, g *ReadGrant) { g.Identity.TeamID++ }, nil, ErrDenied},
		{"foreign_run", func(_ *http.Request, g *ReadGrant) { g.Identity.RunID = "other" }, nil, ErrDenied},
		{"old_execution", func(_ *http.Request, g *ReadGrant) { g.Identity.ExecutionID = "old" }, nil, ErrDenied},
		{"old_actor", func(_ *http.Request, g *ReadGrant) { g.Identity.ActorID++ }, nil, ErrDenied},
		{"old_epoch", func(_ *http.Request, g *ReadGrant) { g.Identity.ActorEpoch++ }, nil, ErrDenied},
		{"other_relay", func(_ *http.Request, g *ReadGrant) { g.Identity.RelayKeySHA256 = "other" }, nil, ErrDenied},
		{"other_authority", func(_ *http.Request, g *ReadGrant) { g.Identity.Authority = "other.example.com" }, nil, ErrDenied},
		{"foreign_repo", func(_ *http.Request, g *ReadGrant) { g.Repository = "example/other" }, nil, ErrDenied},
		{"revoked", func(_ *http.Request, g *ReadGrant) { g.Identity.Revoked = true }, nil, ErrDenied},
		{"expired_lease", func(_ *http.Request, g *ReadGrant) { g.Identity.LeaseExpiresAt = time.Now().Add(-time.Minute) }, nil, ErrDenied},
		{"expired_token", func(_ *http.Request, g *ReadGrant) { g.ExpiresAt = time.Now().Add(-time.Minute) }, nil, ErrDenied},
		{"missing_token", func(_ *http.Request, g *ReadGrant) { g.Token = "" }, nil, ErrDenied},
		{"missing_version", func(_ *http.Request, g *ReadGrant) { g.CredentialVersion = "" }, nil, ErrDenied},
		{"missing_grant", func(*http.Request, *ReadGrant) {}, ErrDenied, ErrDenied},
		{"unavailable_grant", func(*http.Request, *ReadGrant) {}, errors.New("private store details"), ErrUnavailable},
		{"push", func(r *http.Request, _ *ReadGrant) { r.URL.RawQuery = "service=git-receive-pack" }, nil, ErrInvalidRequest},
		{"push_rpc", func(r *http.Request, _ *ReadGrant) {
			r.Method, r.URL.Path, r.URL.RawQuery = "POST", "/v1/git/example/repo.git/git-receive-pack", ""
		}, nil, ErrInvalidRequest},
		{"extra_query", func(r *http.Request, _ *ReadGrant) { r.URL.RawQuery += "&service=git-receive-pack" }, nil, ErrInvalidRequest},
		{"encoded_path", func(r *http.Request, _ *ReadGrant) { r.URL.RawPath = "/v1/git/%65xample/repo.git/info/refs" }, nil, ErrInvalidRequest},
		{"traversal", func(r *http.Request, _ *ReadGrant) { r.URL.Path = "/v1/git/example/../repo.git/info/refs" }, nil, ErrInvalidRequest},
		{"dot_segment", func(r *http.Request, _ *ReadGrant) { r.URL.Path = "/v1/git/example/..git/info/refs" }, nil, ErrInvalidRequest},
		{"parent_segment", func(r *http.Request, _ *ReadGrant) { r.URL.Path = "/v1/git/example/...git/info/refs" }, nil, ErrInvalidRequest},
		{"absolute_url", func(r *http.Request, _ *ReadGrant) { r.URL.Scheme, r.URL.Host = "https", "foreign.example.com" }, nil, ErrInvalidRequest},
		{"upgrade", func(r *http.Request, _ *ReadGrant) { r.Header.Set("Upgrade", "websocket") }, nil, ErrInvalidRequest},
		{"compressed", func(r *http.Request, _ *ReadGrant) { r.Header.Set("Content-Encoding", "gzip") }, nil, ErrInvalidRequest},
		{"protocol_capability", func(r *http.Request, _ *ReadGrant) { r.Header.Set("Git-Protocol", "version=2:server-option=other") }, nil, ErrInvalidRequest},
		{"lfs", func(r *http.Request, _ *ReadGrant) { r.URL.Path = "/v1/git/example/repo.git/info/lfs/objects/batch" }, nil, ErrInvalidRequest},
		{"large_body", func(r *http.Request, _ *ReadGrant) {
			r.Method, r.URL.Path, r.URL.RawQuery = "POST", "/v1/git/example/repo.git/git-upload-pack", ""
			r.Header.Set("Content-Type", "application/x-git-upload-pack-request")
			r.ContentLength = maxRequestBytes + 1
		}, nil, ErrInvalidRequest},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			grant := readGrant(reg)
			r := httptest.NewRequest(http.MethodGet, "/v1/git/example/repo.git/info/refs?service=git-upload-pack", nil)
			tc.mutate(r, &grant)
			adapter, err := New(Config{Lookup: func(context.Context, LookupRequest) (ReadGrant, error) { return grant, tc.lookup },
				Transport: transport(t, upstream), LookupTimeout: time.Second, RequestTimeout: time.Minute})
			if err != nil {
				t.Fatal(err)
			}
			if _, err := adapter.Prepare(r, reg); !errors.Is(err, tc.want) {
				t.Fatalf("got %v, want %v", err, tc.want)
			}
		})
	}
	if calls.Load() != 0 {
		t.Fatal("denied request reached upstream")
	}
}

func TestRequestBodyLimits(t *testing.T) {
	compressed := func(data []byte) []byte {
		t.Helper()
		var buffer bytes.Buffer
		writer := gzip.NewWriter(&buffer)
		if _, err := writer.Write(data); err != nil {
			t.Fatal(err)
		}
		if err := writer.Close(); err != nil {
			t.Fatal(err)
		}
		return buffer.Bytes()
	}
	incompressible := make([]byte, maxRequestBytes)
	if _, err := rand.New(rand.NewSource(1)).Read(incompressible); err != nil {
		t.Fatal(err)
	}
	oversizedCompressed := compressed(incompressible)
	if len(oversizedCompressed) <= maxRequestBytes {
		t.Fatal("fixture did not exceed the compressed size limit")
	}
	for _, tc := range []struct {
		name, encoding string
		body           []byte
		want           int
	}{
		{"gzip", "gzip", compressed([]byte("0000")), 200},
		{"invalid_gzip", "gzip", []byte("invalid"), 400},
		{"expanded_body", "gzip", compressed(bytes.Repeat([]byte("x"), maxRequestBytes+1)), 400},
		{"wire_body", "gzip", oversizedCompressed, 400},
		{"plain_body", "", bytes.Repeat([]byte("x"), maxRequestBytes+1), 400},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var calls atomic.Int32
			upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				payload, err := io.ReadAll(r.Body)
				if err != nil || string(payload) != "0000" || r.ContentLength != 4 || r.Header.Get("Content-Encoding") != "" {
					t.Error("upstream did not receive decoded Git request")
				}
				w.Header().Set("Content-Type", "application/x-git-upload-pack-result")
				_, _ = io.WriteString(w, "0000")
			}))
			defer upstream.Close()
			reg := registration()
			server := adapterServer(t, reg, upstream, func(context.Context, LookupRequest) (ReadGrant, error) { return readGrant(reg), nil })
			request, _ := http.NewRequest(http.MethodPost, server.URL+"/v1/git/example/repo.git/git-upload-pack", io.NopCloser(bytes.NewReader(tc.body)))
			request.Header.Set("Content-Type", "application/x-git-upload-pack-request")
			if tc.encoding != "" {
				request.Header.Set("Content-Encoding", tc.encoding)
			}
			response, err := server.Client().Do(request)
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			if response.StatusCode != tc.want || (tc.want == 200) != (calls.Load() == 1) {
				t.Fatalf("status=%d upstream calls=%d", response.StatusCode, calls.Load())
			}
		})
	}
}

func TestUpstreamFailureIsNotForwarded(t *testing.T) {
	for _, status := range []int{301, 302, 307, 401, 403, 500} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			var calls atomic.Int32
			upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				w.Header().Set("Content-Type", "application/x-git-upload-pack-advertisement")
				w.Header().Set("Location", "https://foreign.example.com/repo.git")
				w.Header().Set("WWW-Authenticate", "Basic upstream details")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, "private upstream error")
			}))
			defer upstream.Close()
			reg := registration()
			server := adapterServer(t, reg, upstream, func(context.Context, LookupRequest) (ReadGrant, error) { return readGrant(reg), nil })
			response, err := server.Client().Get(server.URL + "/v1/git/example/repo.git/info/refs?service=git-upload-pack")
			if err != nil {
				t.Fatal(err)
			}
			defer response.Body.Close()
			body, _ := io.ReadAll(response.Body)
			if response.StatusCode != 502 || calls.Load() != 1 || strings.Contains(string(body), "private") ||
				response.Header.Get("Location") != "" || response.Header.Get("WWW-Authenticate") != "" {
				t.Fatal("upstream failure or redirect escaped")
			}
		})
	}
}

func TestLookupAndTransferCancellation(t *testing.T) {
	reg := registration()
	grant := readGrant(reg)
	started, stopped := make(chan struct{}), make(chan struct{})
	release := make(chan struct{})
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started)
		select {
		case <-r.Context().Done():
		case <-release:
		}
		close(stopped)
	}))
	defer upstream.Close()
	defer close(release)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	adapter, err := New(Config{Lookup: func(context.Context, LookupRequest) (ReadGrant, error) {
		cancel()
		return grant, nil
	}, Transport: transport(t, upstream), LookupTimeout: time.Second, RequestTimeout: time.Minute})
	if err != nil {
		t.Fatal(err)
	}
	r := httptest.NewRequest(http.MethodGet, "/v1/git/example/repo.git/info/refs?service=git-upload-pack", nil).WithContext(ctx)
	if _, err := adapter.Prepare(r, reg); !errors.Is(err, ErrUnavailable) {
		t.Fatalf("late grant accepted: %v", err)
	}
	server := adapterServer(t, reg, upstream, func(context.Context, LookupRequest) (ReadGrant, error) { return grant, nil })
	ctx, cancelTransfer := context.WithCancel(context.Background())
	defer cancelTransfer()
	request, _ := http.NewRequestWithContext(ctx, http.MethodGet, server.URL+r.URL.String(), nil)
	done := make(chan error, 1)
	go func() {
		response, err := server.Client().Do(request)
		if response != nil {
			response.Body.Close()
		}
		done <- err
	}()
	select {
	case <-started:
	case <-time.After(5 * time.Second):
		t.Fatal("transfer did not start")
	}
	cancelTransfer()
	select {
	case <-stopped:
	case <-time.After(5 * time.Second):
		t.Fatal("disconnect left upstream running")
	}
	if err := <-done; !errors.Is(err, context.Canceled) {
		t.Fatalf("transfer did not cancel: %v", err)
	}
}

func TestIncompletePackAbortsTransfer(t *testing.T) {
	upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-git-upload-pack-result")
		w.Header().Set("Content-Length", "100")
		_, _ = io.WriteString(w, "partial")
	}))
	defer upstream.Close()
	reg := registration()
	server := adapterServer(t, reg, upstream, func(context.Context, LookupRequest) (ReadGrant, error) { return readGrant(reg), nil })
	response, err := server.Client().Post(server.URL+"/v1/git/example/repo.git/git-upload-pack", "application/x-git-upload-pack-request", strings.NewReader("0000"))
	if err == nil {
		defer response.Body.Close()
		if _, err := io.ReadAll(response.Body); err == nil {
			t.Fatal("incomplete pack reported success")
		}
	}
}

func TestCloneFetchAndRotation(t *testing.T) {
	for _, repo := range []string{"repo", ".github"} {
		t.Run(repo, func(t *testing.T) {
			root := t.TempDir()
			git, err := exec.LookPath("git")
			if err != nil {
				t.Fatal(err)
			}
			gitEnv := []string{"PATH=" + os.Getenv("PATH"), "HOME=" + root, "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null",
				"GIT_TERMINAL_PROMPT=0", "GIT_AUTHOR_NAME=Example", "GIT_AUTHOR_EMAIL=example@example.com",
				"GIT_COMMITTER_NAME=Example", "GIT_COMMITTER_EMAIL=example@example.com"}
			run := func(args ...string) string {
				t.Helper()
				ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
				defer cancel()
				command := exec.CommandContext(ctx, git, args...)
				command.Env = gitEnv
				output, err := command.CombinedOutput()
				if err != nil {
					t.Fatalf("git %v: %v\n%s", args, err, output)
				}
				return strings.TrimSpace(string(output))
			}
			bare, source, clone := filepath.Join(root, "example", repo+".git"), filepath.Join(root, "source"), filepath.Join(root, "clone")
			run("init", "--bare", "--initial-branch=main", bare)
			run("init", "--initial-branch=main", source)
			if err := os.WriteFile(filepath.Join(source, "example.txt"), []byte("first revision\n"), 0600); err != nil {
				t.Fatal(err)
			}
			run("-C", source, "add", "example.txt")
			run("-C", source, "-c", "commit.gpgsign=false", "commit", "-m", "first")
			tree := run("-C", source, "rev-parse", "HEAD^{tree}")
			parent := run("-C", source, "rev-parse", "HEAD")
			for i := range 40 {
				name := "branch-" + strconv.Itoa(i)
				commit := run("-C", source, "commit-tree", tree, "-p", parent, "-m", name)
				run("-C", source, "update-ref", "refs/heads/"+name, commit)
			}
			run("-C", source, "push", "--all", bare)
			backend := &cgi.Handler{Path: git, Args: []string{"http-backend"}, Env: append(gitEnv, "GIT_PROJECT_ROOT="+root, "GIT_HTTP_EXPORT_ALL=1")}
			var version atomic.Int32
			version.Store(1)
			var calls atomic.Int32
			upstream := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, token, ok := r.BasicAuth()
				if !ok || token != "synthetic-token-"+strconv.Itoa(int(version.Load())) {
					t.Error("stale or guest token reached upstream")
					w.WriteHeader(http.StatusUnauthorized)
					return
				}
				calls.Add(1)
				backend.ServeHTTP(w, r)
			}))
			defer upstream.Close()
			reg := registration()
			var revoked atomic.Bool
			var compressed atomic.Int32
			server := adapterServer(t, reg, upstream, func(context.Context, LookupRequest) (ReadGrant, error) {
				if revoked.Load() {
					return ReadGrant{}, ErrDenied
				}
				grant := readGrant(reg)
				grant.Repository = "example/" + repo
				grant.Token = "synthetic-token-" + strconv.Itoa(int(version.Load()))
				grant.CredentialVersion = "version-" + strconv.Itoa(int(version.Load()))
				return grant, nil
			}, func(r *http.Request) {
				if r.Header.Get("Content-Encoding") == "gzip" {
					compressed.Add(1)
				}
			})
			remote := server.URL + "/v1/git/example/" + repo + ".git"
			run("-c", "http.extraHeader=Authorization: Bearer synthetic-capability", "clone", remote, clone)
			if run("-C", clone, "rev-parse", "HEAD") != run("-C", source, "rev-parse", "HEAD") {
				t.Fatal("clone did not receive the commit")
			}
			version.Store(2)
			if err := os.WriteFile(filepath.Join(source, "example.txt"), []byte("second revision\n"), 0600); err != nil {
				t.Fatal(err)
			}
			run("-C", source, "-c", "commit.gpgsign=false", "commit", "-am", "second")
			run("-C", source, "push", bare, "main")
			run("-C", clone, "-c", "http.extraHeader=Authorization: Bearer synthetic-capability", "fetch", "origin")
			if run("-C", clone, "rev-parse", "origin/main") != run("-C", source, "rev-parse", "HEAD") {
				t.Fatal("fetch did not receive the new commit")
			}
			if run("-C", clone, "remote", "get-url", "origin") != remote {
				t.Fatal("credential-bearing remote persisted")
			}
			if compressed.Load() == 0 {
				t.Fatal("Git negotiation did not exercise gzip")
			}
			before := calls.Load()
			for _, args := range [][]string{{"-C", clone, "push", "origin", "HEAD:blocked"}, {"ls-remote", server.URL + "/v1/git/example/other.git"}} {
				command := exec.Command(git, args...)
				command.Env = gitEnv
				if _, err := command.CombinedOutput(); err == nil {
					t.Fatalf("unauthorized Git operation succeeded: %v", args)
				}
			}
			revoked.Store(true)
			command := exec.Command(git, "-C", clone, "fetch", "origin")
			command.Env = gitEnv
			if _, err := command.CombinedOutput(); err == nil || calls.Load() != before {
				t.Fatal("denied Git operation reached upstream")
			}

		})
	}
}
