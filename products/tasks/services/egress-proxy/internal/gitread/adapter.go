package gitread

import (
	"bytes"
	"compress/gzip"
	"context"
	"errors"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

var (
	ErrInvalidRequest = errors.New("invalid Git read request")
	ErrDenied         = errors.New("Git read not authorized")
	ErrUnavailable    = errors.New("Git grant unavailable")
	ErrUpstream       = errors.New("Git upstream unavailable")
	ownerName         = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]{0,38}$`)
	repositoryName    = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,100}$`)
)

const maxRequestBytes = 1 << 20

type LookupRequest struct {
	Identity   identity.Registration
	Repository string
}

type ReadGrant struct {
	Identity          identity.Registration
	Repository        string
	Token             string `json:"-"`
	CredentialVersion string
	ExpiresAt         time.Time
}

type Lookup func(context.Context, LookupRequest) (ReadGrant, error)

type Config struct {
	Lookup         Lookup
	Transport      http.RoundTripper
	LookupTimeout  time.Duration
	RequestTimeout time.Duration
}

type Adapter struct {
	config Config
}

type Operation struct {
	CredentialVersion string
	request           *http.Request
	transport         http.RoundTripper
	deadline          time.Time
	responseType      string
	gzip              bool
}

func New(config Config) (*Adapter, error) {
	if config.Lookup == nil || config.Transport == nil || config.LookupTimeout <= 0 || config.RequestTimeout <= 0 {
		return nil, errors.New("invalid Git adapter configuration")
	}
	return &Adapter{config: config}, nil
}

func route(r *http.Request) (string, string, error) {
	if r.URL == nil || r.URL.IsAbs() || r.URL.Host != "" || r.URL.User != nil || r.URL.Opaque != "" ||
		r.URL.RawPath != "" || r.URL.Fragment != "" || r.URL.ForceQuery || len(r.Trailer) != 0 ||
		len(r.Header.Values("Upgrade")) != 0 {
		return "", "", ErrInvalidRequest
	}
	encoding := r.Header.Values("Content-Encoding")
	if len(encoding) > 0 && (len(encoding) != 1 || encoding[0] != "gzip" || r.Method != http.MethodPost) {
		return "", "", ErrInvalidRequest
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/git/"), "/")
	if !strings.HasPrefix(r.URL.Path, "/v1/git/") || len(parts) < 3 || !strings.HasSuffix(parts[1], ".git") {
		return "", "", ErrInvalidRequest
	}
	owner, repo := parts[0], strings.TrimSuffix(parts[1], ".git")
	if !ownerName.MatchString(owner) || !repositoryName.MatchString(repo) || repo == "." || repo == ".." || strings.HasSuffix(repo, ".git") {
		return "", "", ErrInvalidRequest
	}
	protocol := r.Header.Values("Git-Protocol")
	if len(protocol) > 1 || (len(protocol) == 1 && protocol[0] != "version=2") {
		return "", "", ErrInvalidRequest
	}
	repository := strings.ToLower(owner + "/" + repo)
	if len(parts) == 4 && parts[2] == "info" && parts[3] == "refs" && r.Method == http.MethodGet &&
		r.URL.RawQuery == "service=git-upload-pack" && r.ContentLength == 0 && len(r.TransferEncoding) == 0 {
		return repository, "application/x-git-upload-pack-advertisement", nil
	}
	if len(parts) == 3 && parts[2] == "git-upload-pack" && r.Method == http.MethodPost && r.URL.RawQuery == "" &&
		r.ContentLength <= maxRequestBytes && len(r.Header.Values("Content-Type")) == 1 &&
		r.Header.Get("Content-Type") == "application/x-git-upload-pack-request" {
		return repository, "application/x-git-upload-pack-result", nil
	}
	return "", "", ErrInvalidRequest
}

func sameIdentity(a, b identity.Registration) bool {
	return a.TeamID > 0 && a.ActorID > 0 && a.ActorEpoch > 0 && a.RunID != "" && a.ExecutionID != "" &&
		a.RelayKeySHA256 != "" && a.Authority != "" && !a.Revoked && !b.Revoked &&
		a.TeamID == b.TeamID && a.RunID == b.RunID && a.ExecutionID == b.ExecutionID &&
		a.ActorID == b.ActorID && a.ActorEpoch == b.ActorEpoch && a.RelayKeySHA256 == b.RelayKeySHA256 &&
		a.Authority == b.Authority
}

func (a *Adapter) Prepare(r *http.Request, registration identity.Registration) (*Operation, error) {
	deadline := time.Now().Add(a.config.RequestTimeout)
	repository, responseType, err := route(r)
	if err != nil {
		return nil, err
	}
	if !sameIdentity(registration, registration) || !time.Now().Before(registration.LeaseExpiresAt) {
		return nil, ErrDenied
	}
	ctx, cancel := context.WithTimeout(r.Context(), a.config.LookupTimeout)
	defer cancel()
	grant, err := a.config.Lookup(ctx, LookupRequest{Identity: registration, Repository: repository})
	if ctx.Err() != nil {
		return nil, ErrUnavailable
	}
	if errors.Is(err, ErrDenied) {
		return nil, ErrDenied
	}
	if err != nil {
		return nil, ErrUnavailable
	}
	if !sameIdentity(registration, grant.Identity) || grant.Repository != repository || grant.Token == "" ||
		len(grant.Token) > 8192 || strings.ContainsAny(grant.Token, " \t\r\n") || grant.CredentialVersion == "" {
		return nil, ErrDenied
	}
	for _, expires := range []time.Time{registration.LeaseExpiresAt, grant.Identity.LeaseExpiresAt, grant.ExpiresAt} {
		if expires.Before(deadline) {
			deadline = expires
		}
	}
	if !time.Now().Before(deadline) {
		return nil, ErrDenied
	}
	path := "/" + repository + ".git/git-upload-pack"
	if r.Method == http.MethodGet {
		path = "/" + repository + ".git/info/refs"
	}
	out := r.Clone(r.Context())
	out.URL = &url.URL{Scheme: "https", Host: "github.com", Path: path, RawQuery: r.URL.RawQuery}
	out.Host, out.RequestURI = "github.com", ""
	out.Header = make(http.Header)
	out.Header.Set("Accept", responseType)
	out.Header.Set("Accept-Encoding", "identity")
	out.Header.Set("User-Agent", "posthog-agent-egress")
	out.SetBasicAuth("x-access-token", grant.Token)
	if r.Method == http.MethodPost {
		out.Header.Set("Content-Type", "application/x-git-upload-pack-request")
	}
	if r.Header.Get("Git-Protocol") != "" {
		out.Header.Set("Git-Protocol", "version=2")
	}
	out.GetBody, out.Trailer, out.TransferEncoding = nil, nil, nil
	out.Close = false
	if out.Method == http.MethodGet {
		out.Body = nil
	}
	return &Operation{CredentialVersion: grant.CredentialVersion, request: out, transport: a.config.Transport,
		deadline: deadline, responseType: responseType, gzip: r.Header.Get("Content-Encoding") == "gzip"}, nil
}

func requestBody(w http.ResponseWriter, body io.ReadCloser, compressed bool) ([]byte, error) {
	if body == nil {
		return nil, ErrInvalidRequest
	}
	var reader io.Reader = http.MaxBytesReader(w, body, maxRequestBytes)
	if compressed {
		decoded, err := gzip.NewReader(reader)
		if err != nil {
			return nil, ErrInvalidRequest
		}
		defer decoded.Close()
		reader = decoded
	}
	payload, err := io.ReadAll(io.LimitReader(reader, maxRequestBytes+1))
	if err != nil || len(payload) > maxRequestBytes {
		return nil, ErrInvalidRequest
	}
	return payload, nil
}

func (o *Operation) Forward(w http.ResponseWriter) error {
	if !time.Now().Before(o.deadline) {
		return ErrDenied
	}
	ctx, cancel := context.WithDeadline(o.request.Context(), o.deadline)
	defer cancel()
	if ctx.Err() != nil {
		return ErrUnavailable
	}
	deadline, _ := ctx.Deadline()
	controller := http.NewResponseController(w)
	if controller.SetReadDeadline(deadline) != nil || controller.SetWriteDeadline(deadline) != nil {
		return ErrUnavailable
	}
	out := o.request.Clone(ctx)
	if out.Method == http.MethodPost {
		payload, err := requestBody(w, out.Body, o.gzip)
		if err != nil {
			return err
		}
		out.Body = io.NopCloser(bytes.NewReader(payload))
		out.ContentLength = int64(len(payload))
	}
	if ctx.Err() != nil {
		return ErrUnavailable
	}
	response, err := o.transport.RoundTrip(out)
	if err != nil {
		return ErrUpstream
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK || response.Header.Get("Content-Type") != o.responseType ||
		response.Header.Get("Content-Encoding") != "" {
		return ErrUpstream
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", o.responseType)
	w.WriteHeader(http.StatusOK)
	if _, err := io.Copy(w, response.Body); err != nil {
		panic(http.ErrAbortHandler)
	}
	return nil
}
