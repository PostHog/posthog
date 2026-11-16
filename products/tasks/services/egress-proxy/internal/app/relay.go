package app

import (
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net/http"
	"net/url"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/relay"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

type Relay struct {
	handler http.Handler
	cert    *x509.Certificate
	timeout time.Duration
}

func (r *Relay) Ready() bool {
	return certificateActive(r.cert)
}

func (r *Relay) ServeHTTP(w http.ResponseWriter, request *http.Request) {
	request, cancel := boundedRequest(w, request, r.timeout)
	defer cancel()
	if !r.Ready() {
		w.Header().Set("Connection", "close")
		http.Error(w, "relay credential unavailable", http.StatusServiceUnavailable)
		return
	}
	r.handler.ServeHTTP(w, request)
}

func NewRelay(config RelayConfig, metrics *telemetry.Metrics) (*Relay, error) {
	cert, err := certificate(config.CertificateFile, config.PrivateKeyFile)
	if err != nil {
		return nil, err
	}
	serverCAs, err := roots(config.ServerCAFile)
	if err != nil {
		return nil, err
	}
	endpoint, err := url.Parse(config.Endpoint)
	if err != nil {
		return nil, errors.New("invalid relay endpoint")
	}
	handler, err := relay.New(relay.Config{
		Endpoint: endpoint, RequestTimeout: config.requestTimeout(),
		TLSConfig: &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{cert}, RootCAs: serverCAs},
		OnError:   func(kind relay.FailureKind) { metrics.RelayFailure(string(kind)) },
	})
	if err != nil {
		return nil, err
	}
	return &Relay{handler: handler, cert: cert.Leaf, timeout: config.requestTimeout()}, nil
}
