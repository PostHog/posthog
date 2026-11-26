package app

import (
	"crypto/tls"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/gitread"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

func newGitRead(config GitReadConfig, region string, lookupTimeout, requestTimeout time.Duration) (*gitread.Adapter, []*http.Transport, error) {
	smokescreen, err := url.Parse(config.SmokescreenURL)
	if err != nil || smokescreen.Hostname() == "" || (smokescreen.Scheme != "http" && smokescreen.Scheme != "https") ||
		smokescreen.User != nil || smokescreen.Opaque != "" || smokescreen.RawQuery != "" || smokescreen.ForceQuery ||
		smokescreen.Fragment != "" || (smokescreen.Path != "" && smokescreen.Path != "/") {
		return nil, nil, errors.New("Git reads require an explicit Smokescreen endpoint")
	}
	key, err := readFile(config.GrantSigningKeyFile)
	if err != nil {
		return nil, nil, err
	}
	grantRoots, err := roots(config.GrantCAFile)
	if err != nil {
		return nil, nil, err
	}
	upstreamRoots, err := roots(config.UpstreamCAFile)
	if err != nil {
		return nil, nil, err
	}
	grants := http.DefaultTransport.(*http.Transport).Clone()
	grants.Proxy = nil
	grants.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: grantRoots}
	client, err := gitread.NewClient(gitread.ClientConfig{
		BaseURL: config.GrantURL, Region: region, SigningKey: strings.TrimSpace(string(key)),
		Timeout: lookupTimeout, HTTPClient: &http.Client{Transport: grants},
	})
	if err != nil {
		return nil, nil, err
	}
	upstream := http.DefaultTransport.(*http.Transport).Clone()
	upstream.Proxy = http.ProxyURL(smokescreen)
	upstream.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: upstreamRoots}
	upstream.MaxConnsPerHost = 64
	adapter, err := gitread.New(gitread.Config{
		Lookup: client.Lookup, Transport: upstream, LookupTimeout: lookupTimeout, RequestTimeout: requestTimeout,
	})
	return adapter, []*http.Transport{grants, upstream}, err
}

type gitResponse struct {
	http.ResponseWriter
	status int
	bytes  int64
}

func (w *gitResponse) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (w *gitResponse) WriteHeader(status int) {
	if w.status == 0 {
		w.status = status
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *gitResponse) Write(body []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	n, err := w.ResponseWriter.Write(body)
	w.bytes += int64(n)
	return n, err
}

type gitBody struct {
	io.ReadCloser
	bytes int64
}

func (b *gitBody) Read(buffer []byte) (int, error) {
	n, err := b.ReadCloser.Read(buffer)
	b.bytes += int64(n)
	return n, err
}

func gitFailure(err error) (string, int) {
	switch {
	case errors.Is(err, gitread.ErrDenied):
		return "denied", http.StatusForbidden
	case errors.Is(err, gitread.ErrInvalidRequest):
		return "invalid_request", http.StatusBadRequest
	case errors.Is(err, gitread.ErrUpstream):
		return "upstream_unavailable", http.StatusBadGateway
	default:
		return "unavailable", http.StatusServiceUnavailable
	}
}

func rejectGit(w http.ResponseWriter, r *http.Request, status int) {
	if r.ProtoMajor == 1 && r.Body != nil && r.ContentLength != 0 {
		w.Header().Set("Connection", "close")
		if http.NewResponseController(w).SetReadDeadline(time.Now()) != nil {
			panic(http.ErrAbortHandler)
		}
	}
	w.WriteHeader(status)
}

func serveGit(w http.ResponseWriter, r *http.Request, adapter *gitread.Adapter, registration identity.Registration, record *telemetry.Record, event *telemetry.Event) {
	event.Operation = "git_read"
	w.Header().Set("Cache-Control", "no-store")
	response := &gitResponse{ResponseWriter: w}
	var body *gitBody
	if r.Body != nil {
		body = &gitBody{ReadCloser: r.Body}
		r = r.Clone(r.Context())
		r.Body = body
	}
	defer func() {
		event.BytesSent = response.bytes
		if body != nil {
			event.BytesReceived = body.bytes
		}
		if response.status != 0 {
			event.Status = response.status
		}
	}()
	operation, err := adapter.Prepare(r, registration)
	if err != nil {
		event.Outcome, event.Status = gitFailure(err)
		record.Emit(*event)
		rejectGit(response, r, event.Status)
		return
	}
	event.CredentialVersion = operation.CredentialVersion
	event.Outcome, event.Status = "allowed", http.StatusOK
	record.Emit(*event)
	event.Outcome, event.Status = "interrupted", 0
	if err := operation.Forward(response); err != nil {
		event.Outcome, event.Status = gitFailure(err)
		rejectGit(response, r, event.Status)
		return
	}
	event.Outcome, event.Status = "allowed", http.StatusOK
}
