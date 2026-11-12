package integration_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httptrace"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/relay"
)

func TestRelayRunIdentity(t *testing.T) {
	now := time.Now().Truncate(time.Second)
	var verificationTime atomic.Int64
	verificationTime.Store(now.UnixNano())
	tlsTime := func() time.Time { return now }
	ca, caKey := certificateAuthority(t, now)
	serverCert := issueCertificate(t, now, ca, caKey, true)
	relayCert := issueCertificate(t, now, ca, caKey, false)
	foreignCert := issueCertificate(t, now, ca, caKey, false)
	roots := x509.NewCertPool()
	roots.AddCert(ca)
	signer, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	registration := identity.Registration{
		RunID:          "run-example",
		TeamID:         123,
		ActorID:        456,
		ActorEpoch:     1,
		ExecutionID:    "execution-example",
		RelayKeySHA256: identity.KeySHA256(relayCert.Leaf),
		LeaseExpiresAt: now.Add(time.Minute),
	}
	var secondRegistration identity.Registration
	var lookupError error
	var mu sync.Mutex
	verifier, err := identity.New(identity.Config{
		Issuer: "https://issuer.example.com",
		Keys:   map[string]*rsa.PublicKey{"test-key": &signer.PublicKey},
		Lookup: func(_ context.Context, runID string) (identity.Registration, error) {
			mu.Lock()
			defer mu.Unlock()
			if lookupError != nil {
				return identity.Registration{}, lookupError
			}
			if runID == registration.RunID {
				return registration, nil
			}
			if runID == secondRegistration.RunID {
				return secondRegistration, nil
			}
			return identity.Registration{}, identity.ErrUnauthorized
		},
		Now:           func() time.Time { return time.Unix(0, verificationTime.Load()) },
		MaxLifetime:   5 * time.Minute,
		LookupTimeout: time.Minute,
		ClockSkew:     3 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	var accepted atomic.Int32
	regional := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := verifier.Authorize(r); err != nil {
			if errors.Is(err, identity.ErrUnavailable) {
				http.Error(w, "authorization unavailable", http.StatusServiceUnavailable)
				return
			}
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		accepted.Add(1)
		w.WriteHeader(http.StatusNoContent)
	}))
	regional.EnableHTTP2 = true
	regional.Config.ErrorLog = log.New(io.Discard, "", 0)
	regional.TLS = &tls.Config{
		Time:         tlsTime,
		MinVersion:   tls.VersionTLS13,
		Certificates: []tls.Certificate{serverCert},
		ClientCAs:    roots,
		ClientAuth:   tls.RequireAndVerifyClientCert,
	}
	regional.StartTLS()
	t.Cleanup(regional.Close)
	endpoint, err := url.Parse(regional.URL)
	if err != nil {
		t.Fatal(err)
	}
	endpoint.Host = "localhost:" + endpoint.Port()
	registration.Authority = endpoint.Host
	baseline := registration
	capability := func(state identity.Registration) string {
		t.Helper()
		claims := identity.Claims{
			RegisteredClaims: jwt.RegisteredClaims{
				Issuer:    "https://issuer.example.com",
				Subject:   state.RunID,
				Audience:  jwt.ClaimStrings{identity.Audience},
				IssuedAt:  jwt.NewNumericDate(now),
				ExpiresAt: jwt.NewNumericDate(now.Add(2 * time.Minute)),
			},
			TeamID:         state.TeamID,
			ActorID:        state.ActorID,
			ActorEpoch:     state.ActorEpoch,
			ExecutionID:    state.ExecutionID,
			RelayKeySHA256: state.RelayKeySHA256,
		}
		token := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
		token.Header["kid"] = "test-key"
		signed, err := token.SignedString(signer)
		if err != nil {
			t.Fatal(err)
		}
		return signed
	}
	startRelay := func(cert tls.Certificate) *httptest.Server {
		t.Helper()
		handler, err := relay.New(relay.Config{
			Endpoint:       endpoint,
			RequestTimeout: time.Minute,
			TLSConfig: &tls.Config{
				Time:         tlsTime,
				MinVersion:   tls.VersionTLS13,
				RootCAs:      roots,
				Certificates: []tls.Certificate{cert},
			},
		})
		if err != nil {
			t.Fatal(err)
		}
		server := httptest.NewServer(handler)
		t.Cleanup(server.Close)
		return server
	}
	legitimateRelay := startRelay(relayCert)
	foreignRelay := startRelay(foreignCert)
	copiedCapability := capability(baseline)
	request := func(t *testing.T, server *httptest.Server, token string, status int) {
		t.Helper()
		req, err := http.NewRequest(http.MethodGet, server.URL+"/probe", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer "+token)
		response, err := server.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer response.Body.Close()
		body, err := io.ReadAll(response.Body)
		if err != nil {
			t.Fatal(err)
		}
		if response.StatusCode != status {
			t.Fatalf("status = %d, want %d", response.StatusCode, status)
		}
		if strings.Contains(string(body), token) {
			t.Fatal("response exposed capability")
		}
	}
	request(t, legitimateRelay, copiedCapability, http.StatusNoContent)
	request(t, foreignRelay, copiedCapability, http.StatusUnauthorized)
	for _, tc := range []struct {
		name   string
		change func(*identity.Registration)
	}{
		{"authority differs from relay endpoint", func(r *identity.Registration) {
			r.Authority = net.JoinHostPort("run-a.example.com", endpoint.Port())
		}},
		{"revoked", func(r *identity.Registration) { r.Revoked = true }},
		{"expired lease", func(r *identity.Registration) { r.LeaseExpiresAt = now }},
		{"actor rebound", func(r *identity.Registration) { r.ActorEpoch++ }},
		{"restored execution", func(r *identity.Registration) { r.ExecutionID = "execution-restored" }},
		{"replaced relay key", func(r *identity.Registration) { r.RelayKeySHA256 = identity.KeySHA256(foreignCert.Leaf) }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			mu.Lock()
			registration = baseline
			tc.change(&registration)
			mu.Unlock()
			request(t, legitimateRelay, copiedCapability, http.StatusUnauthorized)
		})
	}
	mu.Lock()
	registration = baseline
	registration.ExecutionID = "execution-restored"
	registration.RelayKeySHA256 = identity.KeySHA256(foreignCert.Leaf)
	restored := registration
	mu.Unlock()
	request(t, legitimateRelay, copiedCapability, http.StatusUnauthorized)
	request(t, foreignRelay, capability(restored), http.StatusNoContent)
	if accepted.Load() != 2 {
		t.Fatalf("authorized operations = %d, want 2", accepted.Load())
	}
	t.Run("lookup unavailable", func(t *testing.T) {
		mu.Lock()
		registration = baseline
		lookupError = errors.New("registry unavailable")
		mu.Unlock()
		defer func() {
			mu.Lock()
			lookupError = nil
			mu.Unlock()
		}()
		request(t, legitimateRelay, copiedCapability, http.StatusServiceUnavailable)
	})

	mu.Lock()
	registration = baseline
	registration.Authority = "run-a.example.com"
	secondRegistration = registration
	secondRegistration.RunID = "run-second"
	secondRegistration.TeamID++
	secondRegistration.ActorID++
	secondRegistration.ExecutionID = "execution-second"
	secondRegistration.Authority = "run-b.example.com"
	secondRegistration.RelayKeySHA256 = identity.KeySHA256(foreignCert.Leaf)
	firstRun, secondRun := registration, secondRegistration
	mu.Unlock()
	client := func(t *testing.T, cert tls.Certificate, serverName string) *http.Client {
		t.Helper()
		transport := &http.Transport{
			DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
				return (&net.Dialer{}).DialContext(ctx, network, regional.Listener.Addr().String())
			},
			TLSClientConfig: &tls.Config{
				Time:         tlsTime,
				MinVersion:   tls.VersionTLS13,
				RootCAs:      roots,
				Certificates: []tls.Certificate{cert},
				ServerName:   serverName,
			},
			ForceAttemptHTTP2: true,
		}
		t.Cleanup(transport.CloseIdleConnections)
		return &http.Client{Transport: transport}
	}
	firstToken, secondToken := capability(firstRun), capability(secondRun)
	warmTokens := map[string]string{firstRun.Authority: firstToken, secondRun.Authority: secondToken}
	for _, tc := range []struct {
		name        string
		certificate tls.Certificate
		serverName  string
		target      string
		authority   string
		token       string
		status      int
		reused      bool
		verifyAt    time.Time
	}{
		{"first run", relayCert, firstRun.Authority, firstRun.Authority, firstRun.Authority, firstToken, http.StatusNoContent, false, time.Time{}},
		{"second run", foreignCert, secondRun.Authority, secondRun.Authority, secondRun.Authority, secondToken, http.StatusNoContent, false, time.Time{}},
		{"second capability on first relay", relayCert, firstRun.Authority, firstRun.Authority, firstRun.Authority, secondToken, http.StatusUnauthorized, true, time.Time{}},
		{"first capability on second relay", foreignCert, secondRun.Authority, secondRun.Authority, secondRun.Authority, firstToken, http.StatusUnauthorized, true, time.Time{}},
		{"second authority on first connection", relayCert, firstRun.Authority, firstRun.Authority, secondRun.Authority, firstToken, http.StatusUnauthorized, true, time.Time{}},
		{"first authority on second connection", foreignCert, secondRun.Authority, secondRun.Authority, firstRun.Authority, secondToken, http.StatusUnauthorized, true, time.Time{}},
		{"second SNI with first identity", relayCert, secondRun.Authority, firstRun.Authority, firstRun.Authority, firstToken, http.StatusUnauthorized, false, time.Time{}},
		{"CA expires on reused connection", relayCert, firstRun.Authority, firstRun.Authority, firstRun.Authority, firstToken, http.StatusUnauthorized, true, ca.NotAfter},
	} {
		t.Run(tc.name, func(t *testing.T) {
			httpClient := client(t, tc.certificate, tc.serverName)
			send := func(authority, token string, status int, wantReused bool) {
				t.Helper()
				before := accepted.Load()
				req, err := http.NewRequest(http.MethodGet, "https://"+tc.target+"/probe", nil)
				if err != nil {
					t.Fatal(err)
				}
				req.Host = authority
				req.Header.Set("Authorization", "Bearer "+token)
				var reused bool
				req = req.WithContext(httptrace.WithClientTrace(req.Context(), &httptrace.ClientTrace{
					GotConn: func(info httptrace.GotConnInfo) { reused = info.Reused },
				}))
				response, err := httpClient.Do(req)
				if err != nil {
					t.Fatal(err)
				}
				defer response.Body.Close()
				if _, err := io.Copy(io.Discard, response.Body); err != nil {
					t.Fatal(err)
				}
				if response.StatusCode != status || response.ProtoMajor != 2 || reused != wantReused {
					t.Fatalf("status=%d protocol=%s reused=%t; want status=%d HTTP/2 reused=%t", response.StatusCode, response.Proto, reused, status, wantReused)
				}
				wantAccepted := before
				if status == http.StatusNoContent {
					wantAccepted++
				}
				if got := accepted.Load(); got != wantAccepted {
					t.Fatalf("authorized operations = %d, want %d", got, wantAccepted)
				}
			}
			if tc.reused {
				send(tc.target, warmTokens[tc.target], http.StatusNoContent, false)
			}
			if !tc.verifyAt.IsZero() {
				verificationTime.Store(tc.verifyAt.UnixNano())
				defer verificationTime.Store(now.UnixNano())
			}
			send(tc.authority, tc.token, tc.status, tc.reused)
		})
	}
}

func certificateAuthority(t *testing.T, now time.Time) (*x509.Certificate, *ecdsa.PrivateKey) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "test CA"},
		NotBefore:             now.Add(-time.Hour),
		NotAfter:              now.Add(30 * time.Second),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	cert, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return cert, key
}

func issueCertificate(t *testing.T, now time.Time, ca *x509.Certificate, caKey *ecdsa.PrivateKey, server bool) tls.Certificate {
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
		SerialNumber: serial,
		NotBefore:    now.Add(-time.Hour),
		NotAfter:     now.Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	if server {
		template.DNSNames = []string{"localhost", "run-a.example.com", "run-b.example.com"}
		template.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
	}
	der, err := x509.CreateCertificate(rand.Reader, template, ca, &key.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key, Leaf: leaf}
}
