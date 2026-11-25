package app

import (
	"bytes"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net/http"
	"net/url"
	"slices"
	"sync/atomic"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/relay"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

type Relay struct {
	config  RelayConfig
	metrics *telemetry.Metrics
	state   atomic.Pointer[relayState]
}

type relayState struct {
	handler *relay.Handler
	cert    *x509.Certificate
}

func (r *Relay) Ready() bool {
	return certificateActive(r.state.Load().cert)
}

func (r *Relay) ServeHTTP(w http.ResponseWriter, request *http.Request) {
	request, cancel := boundedRequest(w, request, r.config.requestTimeout())
	defer cancel()
	state := r.state.Load()
	if !certificateActive(state.cert) {
		w.Header().Set("Connection", "close")
		http.Error(w, "relay credential unavailable", http.StatusServiceUnavailable)
		return
	}
	state.handler.ServeHTTP(w, request)
}

func NewRelay(config RelayConfig, metrics *telemetry.Metrics) (*Relay, error) {
	r := &Relay{config: config, metrics: metrics}
	if err := r.Reload(); err != nil {
		return nil, err
	}
	return r, nil
}

func (r *Relay) Close() {
	r.state.Load().handler.CloseIdleConnections()
}

func (r *Relay) Reload() error {
	cert, err := certificate(r.config.CertificateFile, r.config.PrivateKeyFile)
	if err != nil {
		return err
	}
	if (len(cert.Leaf.ExtKeyUsage) > 0 || len(cert.Leaf.UnknownExtKeyUsage) > 0) &&
		!slices.Contains(cert.Leaf.ExtKeyUsage, x509.ExtKeyUsageClientAuth) &&
		!slices.Contains(cert.Leaf.ExtKeyUsage, x509.ExtKeyUsageAny) {
		return errors.New("relay certificate does not permit client authentication")
	}
	current := r.state.Load()
	if current != nil && !bytes.Equal(current.cert.RawSubjectPublicKeyInfo, cert.Leaf.RawSubjectPublicKeyInfo) {
		return errors.New("relay certificate key changed")
	}
	if current != nil || r.config.ClientCAFile != "" {
		if err := verifyClientCertificate(cert, r.config.ClientCAFile); err != nil {
			return err
		}
	}
	serverCAs, err := roots(r.config.ServerCAFile)
	if err != nil {
		return err
	}
	endpoint, err := url.Parse(r.config.Endpoint)
	if err != nil {
		return errors.New("invalid relay endpoint")
	}
	handler, err := relay.New(relay.Config{
		Endpoint: endpoint, RequestTimeout: r.config.requestTimeout(),
		TLSConfig: &tls.Config{MinVersion: tls.VersionTLS13, Certificates: []tls.Certificate{cert}, RootCAs: serverCAs},
		OnError:   func(kind relay.FailureKind) { r.metrics.RelayFailure(string(kind)) },
	})
	if err != nil {
		return err
	}
	if old := r.state.Swap(&relayState{handler: handler, cert: cert.Leaf}); old != nil {
		old.handler.CloseIdleConnections()
	}
	return nil
}
