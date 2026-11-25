package app

import (
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/hex"
	"errors"
	"net/http"
	"strings"
	"sync/atomic"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/gitread"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/registry"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

type proxyState struct {
	verifier      *identity.Verifier
	tls           *tls.Config
	transport     *http.Transport
	git           *gitread.Adapter
	gitTransports []*http.Transport
}

func (s *proxyState) close() {
	s.transport.CloseIdleConnections()
	for _, transport := range s.gitTransports {
		transport.CloseIdleConnections()
	}
}

type Proxy struct {
	config  ProxyConfig
	state   atomic.Pointer[proxyState]
	audit   *telemetry.Audit
	metrics *telemetry.Metrics
	limits  *requestLimits
}

func NewProxy(config ProxyConfig, audit *telemetry.Audit, metrics *telemetry.Metrics) (*Proxy, error) {
	p := &Proxy{config: config, audit: audit, metrics: metrics, limits: newRequestLimits(config.CacheEntries)}
	if err := p.Reload(); err != nil {
		return nil, err
	}
	return p, nil
}

func (p *Proxy) Reload() error {
	cert, err := certificate(p.config.CertificateFile, p.config.PrivateKeyFile)
	if err != nil {
		return err
	}
	clientCAs, err := roots(p.config.ClientCAFile)
	if err != nil || clientCAs == nil {
		return errors.New("client CA bundle required")
	}
	keyData, err := readFile(p.config.VerificationKeysFile)
	if err != nil {
		return err
	}
	keys, err := identity.ParseKeyBundle(keyData)
	if err != nil {
		return err
	}
	signingKey, err := readFile(p.config.RegistrySigningKeyFile)
	if err != nil {
		return err
	}
	registryCAs, err := roots(p.config.RegistryCAFile)
	if err != nil {
		return err
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.Proxy = nil
	transport.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: registryCAs}
	client, err := registry.New(registry.Config{
		AllowClusterHTTP: p.config.RegistryAllowClusterHTTP,
		BaseURL:          p.config.RegistryURL, Region: p.config.RegistryRegion, SigningKey: strings.TrimSpace(string(signingKey)),
		Timeout: time.Duration(p.config.LookupTimeoutSeconds) * time.Second, HTTPClient: &http.Client{Transport: transport},
	})
	if err != nil {
		return err
	}
	cache, err := registry.NewCache(registry.CacheConfig{
		Lookup: client.Lookup, MaxEntries: p.config.CacheEntries, MaxConcurrentLookups: p.config.CacheLookups,
	})
	if err != nil {
		return err
	}
	verifier, err := identity.New(identity.Config{
		Issuer: "posthog:tasks", Keys: keys, Lookup: cache.Lookup, MaxLifetime: 5 * time.Minute,
		LookupTimeout: time.Duration(p.config.LookupTimeoutSeconds) * time.Second, ClockSkew: 3 * time.Second,
	})
	if err != nil {
		return err
	}
	state := &proxyState{verifier: verifier, transport: transport, tls: &tls.Config{
		MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{cert},
		ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: clientCAs,
		NextProtos: []string{"h2", "http/1.1"},
	}}
	if p.config.GitRead != nil {
		state.git, state.gitTransports, err = newGitRead(*p.config.GitRead, p.config.RegistryRegion,
			time.Duration(p.config.LookupTimeoutSeconds)*time.Second, p.config.requestTimeout())
		if err != nil {
			state.close()
			return err
		}
	}
	if old := p.state.Swap(state); old != nil {
		old.close()
	}
	return nil
}

func (p *Proxy) TLSConfig() *tls.Config {
	return &tls.Config{
		MinVersion: tls.VersionTLS13,
		GetConfigForClient: func(_ *tls.ClientHelloInfo) (*tls.Config, error) {
			state := p.state.Load()
			if !certificateActive(state.tls.Certificates[0].Leaf) {
				return nil, errors.New("TLS certificate unavailable")
			}
			return state.tls, nil
		},
	}
}

func (p *Proxy) Ready() bool {
	return p.audit.Healthy() && certificateActive(p.state.Load().tls.Certificates[0].Leaf)
}

func (p *Proxy) Close() {
	p.state.Load().close()
}

func currentPeer(r *http.Request, roots *x509.CertPool) *http.Request {
	if r.TLS == nil || len(r.TLS.PeerCertificates) == 0 {
		return r
	}
	intermediates := x509.NewCertPool()
	for _, cert := range r.TLS.PeerCertificates[1:] {
		intermediates.AddCert(cert)
	}
	chains, err := r.TLS.PeerCertificates[0].Verify(x509.VerifyOptions{
		Roots: roots, Intermediates: intermediates, KeyUsages: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	})
	copy := r.Clone(r.Context())
	connection := *r.TLS
	connection.VerifiedChains = chains
	if err != nil {
		connection.VerifiedChains = nil
	}
	copy.TLS = &connection
	return copy
}

func auditRequestID() string {
	var id [16]byte
	_, _ = rand.Read(id[:])
	return hex.EncodeToString(id[:])
}

func (p *Proxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	r, cancel := boundedRequest(w, r, p.config.requestTimeout())
	defer cancel()
	ctx := r.Context()
	relayKey := ""
	expires := started.Add(5 * time.Minute)
	if r.TLS != nil && len(r.TLS.VerifiedChains) > 0 && len(r.TLS.VerifiedChains[0]) > 0 {
		peer := r.TLS.VerifiedChains[0][0]
		relayKey, expires = identity.KeySHA256(peer), peer.NotAfter
	}
	if allowed, report := p.limits.admit(relayKey, expires); !allowed {
		p.metrics.Request("rate_limited", time.Since(started))
		if report {
			if record, ok := p.audit.TryReserve(); ok {
				event := telemetry.Event{RequestID: auditRequestID(), RelayKeySHA256: relayKey, Operation: "unknown", Outcome: "rate_limited", Status: http.StatusTooManyRequests}
				record.Emit(event)
				record.Emit(event)
			}
		}
		w.Header().Set("Retry-After", "1")
		if r.ProtoMajor == 1 && (r.ContentLength != 0 || len(r.TransferEncoding) != 0 || len(r.Trailer) != 0) {
			w.Header().Set("Connection", "close")
			if http.NewResponseController(w).SetReadDeadline(time.Now()) != nil {
				panic(http.ErrAbortHandler)
			}
		}
		http.Error(w, "request limit exceeded", http.StatusTooManyRequests)
		return
	}
	record, ok := p.audit.TryReserve()
	if !ok {
		p.metrics.Request("audit_unavailable", time.Since(started))
		http.Error(w, "audit unavailable", http.StatusServiceUnavailable)
		return
	}
	event := telemetry.Event{RequestID: auditRequestID(), RelayKeySHA256: relayKey, Operation: "unknown", Outcome: "denied", Status: http.StatusUnauthorized}
	admitted := false
	defer func() {
		if !admitted {
			event.Outcome, event.Status = "unavailable", http.StatusServiceUnavailable
			record.Emit(event)
		}
		event.DurationMS = float64(time.Since(started)) / float64(time.Millisecond)
		record.Emit(event)
		p.metrics.Request(event.Outcome, time.Since(started))
	}()
	state := p.state.Load()
	gitRoute := state.git != nil && strings.HasPrefix(r.URL.Path, "/v1/git/")
	if gitRoute && len(r.Header.Values("Authorization")) == 1 {
		if username, capability, ok := r.BasicAuth(); ok && username == "egress" && capability != "" && len(capability) <= 8192 {
			r = r.Clone(r.Context())
			r.Header.Set("Authorization", "Bearer "+capability)
		}
	}
	registration, err := state.verifier.Authorize(currentPeer(r, state.tls.ClientCAs))
	if errors.Is(err, identity.ErrUnavailable) || !certificateActive(state.tls.Certificates[0].Leaf) {
		event.Outcome, event.Status = "unavailable", http.StatusServiceUnavailable
	} else if err == nil {
		event.TeamID, event.RunID, event.ExecutionID = registration.TeamID, registration.RunID, registration.ExecutionID
		event.ActorID, event.ActorEpoch = registration.ActorID, registration.ActorEpoch
		if gitRoute {
			admitted = true
			serveGit(w, r, state.git, registration, record, &event)
			return
		}
		event.Outcome, event.Status = "not_found", http.StatusNotFound
		if r.Method == http.MethodGet && r.URL.Path == "/v1/probe" && r.URL.RawPath == "" &&
			r.URL.RawQuery == "" && !r.URL.ForceQuery && !r.URL.IsAbs() && r.URL.Host == "" && r.Header.Get("Upgrade") == "" {
			event.Operation = "probe"
			if r.ContentLength == 0 && len(r.TransferEncoding) == 0 && len(r.Trailer) == 0 && ctx.Err() == nil {
				event.Outcome, event.Status = "allowed", http.StatusNoContent
			} else {
				event.Outcome, event.Status = "invalid_request", http.StatusBadRequest
				if r.ProtoMajor == 1 {
					w.Header().Set("Connection", "close")
					if err := http.NewResponseController(w).SetReadDeadline(time.Now()); err != nil {
						panic(http.ErrAbortHandler)
					}
				}
			}
		}
	}
	record.Emit(event)
	admitted = true
	if gitRoute && event.Status == http.StatusUnauthorized {
		w.Header().Set("WWW-Authenticate", `Basic realm="agent-egress"`)
	}
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(event.Status)
}
