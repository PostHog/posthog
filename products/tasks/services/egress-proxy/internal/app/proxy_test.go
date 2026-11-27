package app_test

import (
	"bufio"
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httptrace"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

type testCertificate struct {
	certificate *x509.Certificate
	key         *ecdsa.PrivateKey
	certFile    string
	keyFile     string
}

func writeTestFile(t *testing.T, name string, data []byte) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func issueTestCertificate(t *testing.T, issuer *testCertificate, server bool, names ...string) testCertificate {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	serial, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: serial, Subject: pkix.Name{CommonName: "synthetic egress test"},
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour),
		BasicConstraintsValid: true, KeyUsage: x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	parent, signer := template, key
	if issuer == nil {
		template.IsCA, template.KeyUsage, template.ExtKeyUsage = true, x509.KeyUsageCertSign, nil
	} else {
		parent, signer = issuer.certificate, issuer.key
	}
	if server {
		template.DNSNames = append([]string{"localhost"}, names...)
		template.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
	}
	der, err := x509.CreateCertificate(rand.Reader, template, parent, &key.PublicKey, signer)
	if err != nil {
		t.Fatal(err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	private, err := x509.MarshalPKCS8PrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	return testCertificate{
		certificate: cert, key: key,
		certFile: writeTestFile(t, "certificate.pem", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})),
		keyFile:  writeTestFile(t, "private-key.pem", pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: private})),
	}
}

func writeKeyBundle(t *testing.T, path string, keys map[string]*rsa.PrivateKey) {
	t.Helper()
	bundle := make(map[string]string, len(keys))
	for id, key := range keys {
		der, err := x509.MarshalPKIXPublicKey(&key.PublicKey)
		if err != nil {
			t.Fatal(err)
		}
		bundle[id] = string(pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der}))
	}
	data, err := json.Marshal(bundle)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
}

type proxyFixture struct {
	config       app.ProxyConfig
	proxy        *app.Proxy
	audit        *telemetry.Audit
	auditOutput  bytes.Buffer
	metrics      *telemetry.Metrics
	ca           testCertificate
	relayCert    testCertificate
	signer       *rsa.PrivateKey
	registration identity.Registration
	registryCode atomic.Int32
	endpoint     string
}

func newProxyFixture(t *testing.T, configure ...func(*proxyFixture)) *proxyFixture {
	t.Helper()
	f := &proxyFixture{ca: issueTestCertificate(t, nil, false), metrics: telemetry.NewMetrics()}
	serverCert := issueTestCertificate(t, &f.ca, true)
	f.relayCert = issueTestCertificate(t, &f.ca, false)
	var err error
	f.signer, err = rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	f.registration = identity.Registration{
		RunID: "00000000-0000-4000-8000-000000000001", ExecutionID: "00000000-0000-4000-8000-000000000002",
		TeamID: 123, ActorID: 456, ActorEpoch: 1, RelayKeySHA256: identity.KeySHA256(f.relayCert.certificate),
	}
	serviceKey := "synthetic-registry-signing-key-000000000"
	registryServer := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if code := f.registryCode.Load(); code != 0 {
			w.WriteHeader(int(code))
			return
		}
		_, err := jwt.Parse(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), func(token *jwt.Token) (any, error) {
			return []byte(serviceKey), nil
		}, jwt.WithValidMethods([]string{"HS256"}), jwt.WithAudience("posthog:agent_egress_registry"))
		if err != nil {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		registration := f.registration
		registration.LeaseExpiresAt = time.Now().Add(30 * time.Second)
		_ = json.NewEncoder(w).Encode(struct {
			identity.Registration
			Region string `json:"region"`
		}{registration, "test-region"})
	}))
	t.Cleanup(registryServer.Close)
	f.config = app.ProxyConfig{
		ServerConfig:    app.ServerConfig{ListenAddress: "127.0.0.1:0", AdminAddress: "127.0.0.1:0", RequestTimeoutSeconds: 30, ShutdownTimeoutSeconds: 10},
		CertificateFile: serverCert.certFile, PrivateKeyFile: serverCert.keyFile, ClientCAFile: f.ca.certFile,
		VerificationKeysFile: writeTestFile(t, "verification-keys.json", nil), RegistryURL: registryServer.URL,
		RegistryRegion: "test-region", RegistrySigningKeyFile: writeTestFile(t, "registry-key", []byte(serviceKey)),
		RegistryCAFile:       writeTestFile(t, "registry-ca.pem", pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: registryServer.Certificate().Raw})),
		LookupTimeoutSeconds: 10, CacheEntries: 16, CacheLookups: 4, AuditCapacity: 128,
	}
	writeKeyBundle(t, f.config.VerificationKeysFile, map[string]*rsa.PrivateKey{"initial": f.signer})
	f.audit, err = telemetry.NewAudit(&f.auditOutput, f.config.AuditCapacity)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := f.audit.Close(ctx); err != nil {
			t.Error(err)
		}
	})
	f.metrics.BindAudit(f.audit)
	for _, apply := range configure {
		apply(f)
	}
	f.proxy, err = app.NewProxy(f.config, f.audit, f.metrics)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(f.proxy.Close)
	server := httptest.NewUnstartedServer(f.proxy)
	server.EnableHTTP2 = true
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.TLS = f.proxy.TLSConfig()
	server.StartTLS()
	t.Cleanup(server.Close)
	endpoint, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	f.registration.Authority = "localhost:" + endpoint.Port()
	f.endpoint = "https://" + f.registration.Authority
	return f
}

func (f *proxyFixture) capability(t *testing.T, key *rsa.PrivateKey, kid string) string {
	t.Helper()
	now := time.Now().Truncate(time.Second)
	token := jwt.NewWithClaims(jwt.SigningMethodRS256, identity.Claims{
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer: "posthog:tasks", Subject: f.registration.RunID, Audience: jwt.ClaimStrings{identity.Audience},
			IssuedAt: jwt.NewNumericDate(now), ExpiresAt: jwt.NewNumericDate(now.Add(5 * time.Minute)),
		},
		TeamID: f.registration.TeamID, ActorID: f.registration.ActorID, ActorEpoch: f.registration.ActorEpoch,
		ExecutionID: f.registration.ExecutionID, RelayKeySHA256: f.registration.RelayKeySHA256,
	})
	token.Header["kid"] = kid
	signed, err := token.SignedString(key)
	if err != nil {
		t.Fatal(err)
	}
	return signed
}

func (f *proxyFixture) client(t *testing.T, cert *testCertificate) *http.Client {
	t.Helper()
	pool := x509.NewCertPool()
	pool.AddCert(f.ca.certificate)
	config := &tls.Config{MinVersion: tls.VersionTLS13, RootCAs: pool}
	if cert != nil {
		loaded, err := tls.LoadX509KeyPair(cert.certFile, cert.keyFile)
		if err != nil {
			t.Fatal(err)
		}
		config.Certificates = []tls.Certificate{loaded}
	}
	transport := &http.Transport{TLSClientConfig: config, ForceAttemptHTTP2: true}
	t.Cleanup(transport.CloseIdleConnections)
	return &http.Client{Transport: transport, Timeout: 30 * time.Second}
}

func requestStatus(t *testing.T, client *http.Client, endpoint, token string, expected int) *http.Response {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, endpoint, nil)
	if err != nil {
		t.Fatal(err)
	}
	if token != "" {
		request.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil || response.StatusCode != expected {
		t.Fatalf("status = %d, want %d; body read error = %v", response.StatusCode, expected, err)
	}
	if token != "" && bytes.Contains(body, []byte(token)) {
		t.Fatal("response leaked capability")
	}
	return response
}

func TestProxyRelayAdmission(t *testing.T) {
	f := newProxyFixture(t)
	token := f.capability(t, f.signer, "initial")
	foreign := issueTestCertificate(t, &f.ca, false)
	events := 2
	for _, tc := range []struct {
		name   string
		cert   testCertificate
		path   string
		token  string
		status int
	}{
		{"approved probe", f.relayCert, "/v1/probe", token, http.StatusNoContent},
		{"copied capability", foreign, "/v1/probe", token, http.StatusUnauthorized},
		{"missing capability", f.relayCert, "/v1/probe", "", http.StatusUnauthorized},
		{"unknown operation", f.relayCert, "/not-an-adapter", token, http.StatusNotFound},
		{"Git disabled", f.relayCert, "/v1/git/example/repo.git/info/refs?service=git-upload-pack", token, http.StatusNotFound},
		{"metrics are private", f.relayCert, "/metrics", token, http.StatusNotFound},
		{"readiness is private", f.relayCert, "/readyz", token, http.StatusNotFound},
	} {
		t.Run(tc.name, func(t *testing.T) {
			events += 2
			handler, err := app.NewRelay(app.RelayConfig{
				ServerConfig: app.ServerConfig{RequestTimeoutSeconds: 30}, Endpoint: f.endpoint,
				CertificateFile: tc.cert.certFile, PrivateKeyFile: tc.cert.keyFile, ServerCAFile: f.ca.certFile,
			}, telemetry.NewMetrics())
			if err != nil {
				t.Fatal(err)
			}
			relay := httptest.NewServer(handler)
			defer relay.Close()
			requestStatus(t, relay.Client(), relay.URL+tc.path, tc.token, tc.status)
		})
	}
	f.registryCode.Store(http.StatusServiceUnavailable)
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	requestStatus(t, f.client(t, &f.relayCert), f.endpoint+"/v1/probe", token, http.StatusServiceUnavailable)
	if response, err := f.client(t, nil).Get(f.endpoint + "/v1/probe"); err == nil {
		response.Body.Close()
		t.Fatal("request without a client certificate reached the handler")
	}
	if err := f.audit.Close(t.Context()); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(f.auditOutput.Bytes(), []byte(token)) || bytes.Contains(f.auditOutput.Bytes(), []byte("not-an-adapter")) {
		t.Fatal("audit output exposed request contents")
	}
	decoder := json.NewDecoder(bytes.NewReader(f.auditOutput.Bytes()))
	for index := 0; index < events; index++ {
		var event telemetry.Event
		if err := decoder.Decode(&event); err != nil {
			t.Fatal(err)
		}
		if event.SchemaVersion != 1 || event.RequestID == "" || index%2 == 0 && event.Phase != "admission" || index%2 == 1 && event.Phase != "completion" {
			t.Fatalf("invalid audit event: %+v", event)
		}
		if event.Outcome == "allowed" && (event.TeamID != f.registration.TeamID || event.RunID != f.registration.RunID) {
			t.Fatal("accepted operation did not carry registered identity")
		}
	}
}

func TestProxyClusterRegistryRequiresOptIn(t *testing.T) {
	f := newProxyFixture(t)
	for _, allow := range []bool{false, true} {
		t.Run(fmt.Sprint(allow), func(t *testing.T) {
			config := f.config
			config.RegistryURL = "http://registry.tasks.svc.cluster.local:8000"
			config.RegistryAllowClusterHTTP = allow
			data, err := json.Marshal(config)
			if err != nil {
				t.Fatal(err)
			}
			loaded, err := app.LoadProxyConfig(writeTestFile(t, "cluster.json", data))
			if err != nil {
				t.Fatal(err)
			}
			proxy, err := app.NewProxy(loaded, f.audit, f.metrics)
			if (err == nil) != allow {
				t.Fatalf("NewProxy() = %v; allow=%v", err, allow)
			}
			if proxy != nil {
				proxy.Close()
			}
		})
	}
}

func TestInvalidRelayEndpointDoesNotExposeConfiguration(t *testing.T) {
	cert := issueTestCertificate(t, nil, false)
	_, err := app.NewRelay(app.RelayConfig{
		ServerConfig:    app.ServerConfig{RequestTimeoutSeconds: 30},
		CertificateFile: cert.certFile, PrivateKeyFile: cert.keyFile,
		Endpoint: "https://example.com:sentinel-secret",
	}, telemetry.NewMetrics())
	if err == nil || strings.Contains(err.Error(), "sentinel-secret") {
		t.Fatalf("relay endpoint diagnostic = %v; want a sanitized failure", err)
	}
}

func TestReloadRetiresAuthorityOnReusedTLSConnection(t *testing.T) {
	f := newProxyFixture(t)
	client := f.client(t, &f.relayCert)
	initialToken := f.capability(t, f.signer, "initial")
	response := requestStatus(t, client, f.endpoint+"/v1/probe", initialToken, http.StatusNoContent)
	if response.ProtoMajor != 2 || response.TLS.Version != tls.VersionTLS13 {
		t.Fatalf("protocol = %s, TLS = %x", response.Proto, response.TLS.Version)
	}
	request := func(token string, status int) {
		t.Helper()
		var reused bool
		traced := &http.Client{Transport: client.Transport, Timeout: client.Timeout}
		transport := traced.Transport
		traced.Transport = roundTripperFunc(func(r *http.Request) (*http.Response, error) {
			return transport.RoundTrip(r.WithContext(httptrace.WithClientTrace(r.Context(), &httptrace.ClientTrace{
				GotConn: func(info httptrace.GotConnInfo) { reused = info.Reused },
			})))
		})
		requestStatus(t, traced, f.endpoint+"/v1/probe", token, status)
		if !reused {
			t.Fatal("reload test did not reuse the established TLS connection")
		}
	}
	next, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	nextToken := f.capability(t, next, "next")
	writeKeyBundle(t, f.config.VerificationKeysFile, map[string]*rsa.PrivateKey{"initial": f.signer, "next": next})
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	request(initialToken, http.StatusNoContent)
	request(nextToken, http.StatusNoContent)
	writeKeyBundle(t, f.config.VerificationKeysFile, map[string]*rsa.PrivateKey{"next": next})
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	request(initialToken, http.StatusUnauthorized)
	request(nextToken, http.StatusNoContent)
	if err := os.WriteFile(f.config.VerificationKeysFile, []byte("invalid bundle"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.proxy.Reload(); err == nil {
		t.Fatal("invalid replacement bundle was accepted")
	}
	request(nextToken, http.StatusNoContent)
	writeKeyBundle(t, f.config.VerificationKeysFile, map[string]*rsa.PrivateKey{"next": next})
	replacementCA := issueTestCertificate(t, nil, false)
	data, err := os.ReadFile(replacementCA.certFile)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(f.config.ClientCAFile, data, 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	request(nextToken, http.StatusUnauthorized)
}

func TestProxyRequiresAuditAdmission(t *testing.T) {
	f := newProxyFixture(t)
	client := f.client(t, &f.relayCert)
	token := f.capability(t, f.signer, "initial")
	requestStatus(t, client, f.endpoint+"/v1/probe", token, http.StatusNoContent)
	if err := f.audit.Close(t.Context()); err != nil {
		t.Fatal(err)
	}
	if f.proxy.Ready() {
		t.Fatal("proxy remained ready without audit output")
	}
	requestStatus(t, client, f.endpoint+"/v1/probe", token, http.StatusServiceUnavailable)
}

func TestProbeRejectsStalledBodies(t *testing.T) {
	for _, tc := range []struct {
		name   string
		http2  bool
		length int64
	}{
		{"HTTP1 declared", false, 1},
		{"HTTP1 chunked", false, -1},
		{"HTTP2 declared", true, 1},
		{"HTTP2 streaming", true, -1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newProxyFixture(t)
			token := f.capability(t, f.signer, "initial")
			client := f.client(t, &f.relayCert)
			client.Timeout = 10 * time.Second
			var response *http.Response
			if tc.http2 {
				reader, writer := io.Pipe()
				defer reader.Close()
				defer writer.Close()
				request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, f.endpoint+"/v1/probe", reader)
				if err != nil {
					t.Fatal(err)
				}
				request.ContentLength = tc.length
				request.Header.Set("Authorization", "Bearer "+token)
				response, err = client.Do(request)
				if err != nil {
					t.Fatal(err)
				}
				if response.ProtoMajor != 2 {
					response.Body.Close()
					t.Fatalf("protocol = %s; want HTTP/2", response.Proto)
				}
			} else {
				config := client.Transport.(*http.Transport).TLSClientConfig
				connection, err := tls.DialWithDialer(&net.Dialer{Timeout: 10 * time.Second}, "tcp", f.registration.Authority, config)
				if err != nil {
					t.Fatal(err)
				}
				defer connection.Close()
				if err := connection.SetDeadline(time.Now().Add(10 * time.Second)); err != nil {
					t.Fatal(err)
				}
				bodyHeader := "Content-Length: 1"
				if tc.length < 0 {
					bodyHeader = "Transfer-Encoding: chunked"
				}
				if _, err := fmt.Fprintf(connection, "GET /v1/probe HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\n%s\r\n\r\n", f.registration.Authority, token, bodyHeader); err != nil {
					t.Fatal(err)
				}
				response, err = http.ReadResponse(bufio.NewReader(connection), nil)
				if err != nil {
					t.Fatal(err)
				}
				if !response.Close {
					response.Body.Close()
					t.Fatal("rejected HTTP/1 upload left the connection reusable")
				}
			}
			defer response.Body.Close()
			if _, err := io.ReadAll(response.Body); err != nil || response.StatusCode != http.StatusBadRequest {
				t.Fatalf("status = %d; body error = %v", response.StatusCode, err)
			}
			requestStatus(t, client, f.endpoint+"/v1/probe", token, http.StatusNoContent)
		})
	}
}

type roundTripperFunc func(*http.Request) (*http.Response, error)

func (f roundTripperFunc) RoundTrip(r *http.Request) (*http.Response, error) {
	return f(r)
}
