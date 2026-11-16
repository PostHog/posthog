package relay

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type FailureKind string

const (
	FailureCanceled FailureKind = "canceled"
	FailureTLS      FailureKind = "tls_verification"
	FailureDNS      FailureKind = "dns"
	FailureTimeout  FailureKind = "timeout"
	FailureConnect  FailureKind = "connect"
	FailureOther    FailureKind = "other"
)

type Config struct {
	Endpoint       *url.URL
	TLSConfig      *tls.Config
	RequestTimeout time.Duration
	OnError        func(FailureKind)
}

func classifyFailure(err error) FailureKind {
	var certificateError *tls.CertificateVerificationError
	var dnsError *net.DNSError
	var networkError net.Error
	var operationError *net.OpError
	switch {
	case errors.Is(err, context.Canceled):
		return FailureCanceled
	case errors.As(err, &certificateError):
		return FailureTLS
	case errors.As(err, &dnsError):
		return FailureDNS
	case errors.As(err, &networkError) && networkError.Timeout():
		return FailureTimeout
	case errors.As(err, &operationError) && operationError.Op == "dial":
		return FailureConnect
	default:
		return FailureOther
	}
}

func New(config Config) (http.Handler, error) {
	if !validEndpoint(config.Endpoint) {
		return nil, errors.New("relay requires an HTTPS origin")
	}
	if config.RequestTimeout <= 0 {
		return nil, errors.New("relay requires a positive request timeout")
	}
	if config.TLSConfig == nil || config.TLSConfig.InsecureSkipVerify ||
		len(config.TLSConfig.Certificates) != 1 ||
		len(config.TLSConfig.Certificates[0].Certificate) == 0 ||
		config.TLSConfig.Certificates[0].PrivateKey == nil ||
		config.TLSConfig.GetClientCertificate != nil ||
		(config.TLSConfig.MinVersion != 0 && config.TLSConfig.MinVersion < tls.VersionTLS13) ||
		(config.TLSConfig.MaxVersion != 0 && config.TLSConfig.MaxVersion < tls.VersionTLS13) {
		return nil, errors.New("relay requires verified TLS and one client certificate")
	}
	target := *config.Endpoint
	tlsConfig := config.TLSConfig.Clone()
	if tlsConfig.ServerName != "" && tlsConfig.ServerName != target.Hostname() {
		return nil, errors.New("relay TLS name must match the endpoint")
	}
	tlsConfig.ServerName = target.Hostname()
	tlsConfig.MinVersion = tls.VersionTLS13
	transport := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 10 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		TLSClientConfig:       tlsConfig,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		IdleConnTimeout:       90 * time.Second,
		ExpectContinueTimeout: time.Second,
		MaxIdleConns:          64,
		MaxIdleConnsPerHost:   16,
		ForceAttemptHTTP2:     true,
	}
	proxy := &httputil.ReverseProxy{
		Transport:     transport,
		FlushInterval: -1,
		Rewrite: func(request *httputil.ProxyRequest) {
			request.SetURL(&target)
			request.Out.Host = target.Host
			request.Out.GetBody = nil
			request.Out.Trailer = nil
			for name := range request.Out.Header {
				if untrustedIdentityHeader(name) {
					request.Out.Header.Del(name)
				}
			}
			if request.Out.Method != http.MethodGet && request.Out.Method != http.MethodHead &&
				request.Out.Method != http.MethodOptions && request.Out.Body == nil {
				request.Out.Body = io.NopCloser(strings.NewReader(""))
				request.Out.ContentLength = -1
			}
		},
		ErrorHandler: func(w http.ResponseWriter, _ *http.Request, err error) {
			if config.OnError != nil {
				config.OnError(classifyFailure(err))
			}
			http.Error(w, "relay upstream unavailable", http.StatusBadGateway)
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), config.RequestTimeout)
		defer cancel()
		deadline, _ := ctx.Deadline()
		controller := http.NewResponseController(w)
		err := controller.SetReadDeadline(deadline)
		if err == nil {
			err = controller.SetWriteDeadline(deadline)
		}
		if err != nil {
			if config.OnError != nil {
				config.OnError(classifyFailure(err))
			}
			panic(http.ErrAbortHandler)
		}
		if r.Method == http.MethodConnect {
			http.Error(w, "relay method not supported", http.StatusMethodNotAllowed)
			return
		}
		if r.URL.IsAbs() || r.URL.Host != "" || r.URL.Opaque != "" ||
			!strings.HasPrefix(r.URL.Path, "/") || strings.HasPrefix(r.URL.Path, "//") ||
			r.Header.Get("Upgrade") != "" || headerHasToken(r.Header.Values("Connection"), "upgrade") {
			http.Error(w, "relay request rejected", http.StatusBadRequest)
			return
		}
		proxy.ServeHTTP(w, r.WithContext(ctx))
	}), nil
}

func validEndpoint(endpoint *url.URL) bool {
	if endpoint == nil || endpoint.Scheme != "https" || endpoint.User != nil ||
		endpoint.Opaque != "" || endpoint.RawQuery != "" || endpoint.ForceQuery ||
		endpoint.Fragment != "" || endpoint.RawFragment != "" || endpoint.RawPath != "" ||
		(endpoint.Path != "" && endpoint.Path != "/") {
		return false
	}
	host := endpoint.Hostname()
	if host == "" || host != strings.ToLower(host) || strings.HasSuffix(host, ".") {
		return false
	}
	if net.ParseIP(host) == nil {
		if len(host) > 253 {
			return false
		}
		for _, label := range strings.Split(host, ".") {
			if label == "" || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
				return false
			}
			for _, c := range label {
				if (c < 'a' || c > 'z') && (c < '0' || c > '9') && c != '-' {
					return false
				}
			}
		}
	}
	authority := host
	if strings.Contains(host, ":") {
		authority = "[" + host + "]"
	}
	if port := endpoint.Port(); port != "" {
		n, err := strconv.Atoi(port)
		if err != nil || n < 1 || n > 65535 || strconv.Itoa(n) != port {
			return false
		}
		authority = net.JoinHostPort(host, port)
	}
	return endpoint.Host == authority
}

func untrustedIdentityHeader(name string) bool {
	name = strings.ToLower(name)
	return name == "forwarded" || name == "x-real-ip" || name == "x-client-cert" ||
		name == "proxy-authorization" || name == "proxy-connection" ||
		strings.HasPrefix(name, "x-forwarded-") || strings.HasPrefix(name, "x-envoy-") ||
		strings.HasPrefix(name, "x-ssl-") || strings.HasPrefix(name, "x-posthog-") ||
		strings.HasPrefix(name, "x-run-") || strings.HasPrefix(name, "x-team-") ||
		strings.HasPrefix(name, "x-actor-") || strings.HasPrefix(name, "x-execution-") ||
		strings.HasPrefix(name, "x-relay-")
}

func headerHasToken(values []string, token string) bool {
	for _, value := range values {
		for _, part := range strings.Split(value, ",") {
			if strings.EqualFold(strings.TrimSpace(part), token) {
				return true
			}
		}
	}
	return false
}
