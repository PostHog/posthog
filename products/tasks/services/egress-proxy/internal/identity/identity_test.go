package identity_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/synctest"
	"time"

	"github.com/golang-jwt/jwt/v5"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

type fixture struct {
	now          time.Time
	claims       identity.Claims
	registration identity.Registration
	request      *http.Request
	key          any
	method       jwt.SigningMethod
	kid          any
	lookupError  error
	afterLookup  func()
	clockSkew    time.Duration
}

func newFixture(t *testing.T, key *rsa.PrivateKey, certificate *x509.Certificate) *fixture {
	t.Helper()
	now := time.Date(2030, 1, 2, 3, 4, 5, 0, time.UTC)
	f := &fixture{
		now:       now,
		clockSkew: 3 * time.Second,
		claims: identity.Claims{
			RegisteredClaims: jwt.RegisteredClaims{
				Issuer:    "https://issuer.example.com",
				Subject:   "run-test-1",
				Audience:  jwt.ClaimStrings{identity.Audience},
				IssuedAt:  jwt.NewNumericDate(now),
				ExpiresAt: jwt.NewNumericDate(now.Add(time.Minute)),
			},
			TeamID: 10, ActorID: 20, ActorEpoch: 1, ExecutionID: "execution-test-1",
			RelayKeySHA256: identity.KeySHA256(certificate),
		},
		registration: identity.Registration{
			RunID: "run-test-1", TeamID: 10, ActorID: 20, ActorEpoch: 1,
			ExecutionID: "execution-test-1", RelayKeySHA256: identity.KeySHA256(certificate),
			Authority: "run-test-1.example.com", LeaseExpiresAt: now.Add(5 * time.Second),
		},
		request: httptest.NewRequest(http.MethodGet, "https://run-test-1.example.com/operation", nil),
		key:     key,
		method:  jwt.SigningMethodRS256,
		kid:     "current",
	}
	f.request.TLS = &tls.ConnectionState{
		HandshakeComplete: true,
		ServerName:        "run-test-1.example.com",
		PeerCertificates:  []*x509.Certificate{certificate},
		VerifiedChains:    [][]*x509.Certificate{{certificate}},
	}
	return f
}

func (f *fixture) sign(t *testing.T) {
	t.Helper()
	token := jwt.NewWithClaims(f.method, f.claims)
	if f.kid != nil {
		token.Header["kid"] = f.kid
	}
	encoded, err := token.SignedString(f.key)
	if err != nil {
		t.Fatal(err)
	}
	f.request.Header.Set("Authorization", "Bearer "+encoded)
}

func (f *fixture) config(keys map[string]*rsa.PublicKey) identity.Config {
	return identity.Config{
		Issuer: "https://issuer.example.com", Keys: keys, MaxLifetime: 5 * time.Minute,
		LookupTimeout: time.Minute, ClockSkew: f.clockSkew,
		Now: func() time.Time { return f.now },
		Lookup: func(context.Context, string) (identity.Registration, error) {
			if f.afterLookup != nil {
				f.afterLookup()
			}
			return f.registration, f.lookupError
		},
	}
}

func (f *fixture) verifier(t *testing.T, keys map[string]*rsa.PublicKey) *identity.Verifier {
	t.Helper()
	v, err := identity.New(f.config(keys))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func signingKey(t *testing.T) *rsa.PrivateKey {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	return key
}

func relayCertificate(t *testing.T) *x509.Certificate {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2030, 1, 2, 3, 4, 5, 0, time.UTC)
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1), NotBefore: now.Add(-time.Hour), NotAfter: now.Add(time.Hour),
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return certificate
}

func TestAuthorize(t *testing.T) {
	key, otherKey := signingKey(t), signingKey(t)
	certificate, otherCertificate := relayCertificate(t), relayCertificate(t)
	cases := []struct {
		name      string
		change    func(*fixture)
		request   func(*http.Request)
		allowed   bool
		wantError error
	}{
		{name: "valid", allowed: true},
		{name: "explicit default port", allowed: true, request: func(r *http.Request) { r.Host += ":443" }},
		{name: "registered default port", allowed: true, change: func(f *fixture) { f.registration.Authority += ":443" }},
		{name: "case insensitive authority", allowed: true, request: func(r *http.Request) { r.Host = "RUN-TEST-1.EXAMPLE.COM" }},
		{name: "registered dev port", allowed: true, change: func(f *fixture) {
			f.registration.Authority, f.request.Host, f.request.TLS.ServerName = "localhost:8443", "localhost:8443", "localhost"
		}},
		{name: "missing authorization", request: func(r *http.Request) { r.Header.Del("Authorization") }},
		{name: "duplicate authorization", request: func(r *http.Request) { r.Header.Add("Authorization", r.Header.Get("Authorization")) }},
		{name: "malformed authorization", request: func(r *http.Request) { r.Header.Set("Authorization", "Bearer invalid") }},
		{name: "no TLS", request: func(r *http.Request) { r.TLS = nil }},
		{name: "unverified peer", request: func(r *http.Request) { r.TLS.VerifiedChains = nil }},
		{name: "empty verified chain", request: func(r *http.Request) { r.TLS.VerifiedChains = [][]*x509.Certificate{{}} }},
		{name: "nil peer certificate", request: func(r *http.Request) { r.TLS.PeerCertificates[0] = nil }},
		{name: "nil verified leaf", request: func(r *http.Request) { r.TLS.VerifiedChains[0][0] = nil }},
		{name: "nil chain certificate", request: func(r *http.Request) { r.TLS.VerifiedChains[0] = append(r.TLS.VerifiedChains[0], nil) }},
		{name: "expired root", change: func(f *fixture) {
			f.request.TLS.VerifiedChains[0] = append(f.request.TLS.VerifiedChains[0], &x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now})
		}},
		{name: "expired intermediate", change: func(f *fixture) {
			f.request.TLS.VerifiedChains[0] = append(f.request.TLS.VerifiedChains[0],
				&x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now},
				&x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now.Add(time.Hour)})
		}},
		{name: "future authority", change: func(f *fixture) {
			f.request.TLS.VerifiedChains[0] = append(f.request.TLS.VerifiedChains[0], &x509.Certificate{NotBefore: f.now.Add(time.Second), NotAfter: f.now.Add(time.Hour)})
		}},
		{name: "authority activates now", allowed: true, change: func(f *fixture) {
			f.request.TLS.VerifiedChains[0] = append(f.request.TLS.VerifiedChains[0], &x509.Certificate{NotBefore: f.now, NotAfter: f.now.Add(time.Hour)})
		}},
		{name: "valid alternate chain", allowed: true, change: func(f *fixture) {
			f.request.TLS.VerifiedChains = [][]*x509.Certificate{
				{certificate, &x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now}},
				{certificate, &x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now.Add(time.Hour)}},
			}
		}},
		{name: "alternate chain must match peer", change: func(f *fixture) {
			f.request.TLS.VerifiedChains = [][]*x509.Certificate{
				{certificate, &x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: f.now}},
				{otherCertificate},
			}
		}},
		{name: "wrong peer key", request: func(r *http.Request) {
			r.TLS.PeerCertificates, r.TLS.VerifiedChains = []*x509.Certificate{otherCertificate}, [][]*x509.Certificate{{otherCertificate}}
		}},
		{name: "peer differs from verified chain", request: func(r *http.Request) { r.TLS.PeerCertificates = []*x509.Certificate{otherCertificate} }},
		{name: "missing key ID", change: func(f *fixture) { f.kid = nil }},
		{name: "unknown key ID", change: func(f *fixture) { f.kid = "unknown" }},
		{name: "wrong signature", change: func(f *fixture) { f.key = otherKey }},
		{name: "wrong signing algorithm", change: func(f *fixture) { f.method, f.key = jwt.SigningMethodHS256, []byte("synthetic-test-secret") }},
		{name: "wrong issuer", change: func(f *fixture) { f.claims.Issuer = "https://other.example.com" }},
		{name: "missing audience", change: func(f *fixture) { f.claims.Audience = nil }},
		{name: "unrelated audience", change: func(f *fixture) { f.claims.Audience = jwt.ClaimStrings{"posthog:unrelated"} }},
		{name: "multiple audiences", change: func(f *fixture) { f.claims.Audience = append(f.claims.Audience, "posthog:unrelated") }},
		{name: "missing expiry", change: func(f *fixture) { f.claims.ExpiresAt = nil }},
		{name: "expired capability", change: func(f *fixture) { f.claims.ExpiresAt = jwt.NewNumericDate(f.now) }},
		{name: "missing issue time", change: func(f *fixture) { f.claims.IssuedAt = nil }},
		{name: "issue time at skew limit", allowed: true, change: func(f *fixture) { f.claims.IssuedAt = jwt.NewNumericDate(f.now.Add(3 * time.Second)) }},
		{name: "activation at skew limit", allowed: true, change: func(f *fixture) { f.claims.NotBefore = jwt.NewNumericDate(f.now.Add(3 * time.Second)) }},
		{name: "issue time beyond skew", change: func(f *fixture) { f.claims.IssuedAt = jwt.NewNumericDate(f.now.Add(4 * time.Second)) }},
		{name: "activation beyond skew", change: func(f *fixture) { f.claims.NotBefore = jwt.NewNumericDate(f.now.Add(4 * time.Second)) }},
		{name: "skew disabled", change: func(f *fixture) {
			f.clockSkew = 0
			f.claims.IssuedAt = jwt.NewNumericDate(f.now.Add(time.Second))
		}},
		{name: "expired within skew", change: func(f *fixture) {
			f.claims.IssuedAt = jwt.NewNumericDate(f.now.Add(-time.Minute))
			f.claims.ExpiresAt = jwt.NewNumericDate(f.now.Add(-time.Second))
		}},
		{name: "activation at expiry", change: func(f *fixture) {
			f.claims.ExpiresAt = jwt.NewNumericDate(f.now.Add(time.Second))
			f.claims.NotBefore = f.claims.ExpiresAt
		}},
		{name: "excessive lifetime", change: func(f *fixture) { f.claims.ExpiresAt = jwt.NewNumericDate(f.now.Add(6 * time.Minute)) }},
		{name: "missing execution", change: func(f *fixture) { f.claims.ExecutionID = "" }},
		{name: "missing team", change: func(f *fixture) { f.claims.TeamID = 0 }},
		{name: "missing actor", change: func(f *fixture) { f.claims.ActorID = 0 }},
		{name: "missing actor epoch", change: func(f *fixture) { f.claims.ActorEpoch = 0 }},
		{name: "unknown run", change: func(f *fixture) { f.lookupError = identity.ErrUnauthorized }},
		{name: "lookup timeout", wantError: identity.ErrUnavailable, change: func(f *fixture) { f.lookupError = context.DeadlineExceeded }},
		{name: "lookup outage", wantError: identity.ErrUnavailable, change: func(f *fixture) { f.lookupError = errors.New("registry disconnected") }},
		{name: "different run", change: func(f *fixture) { f.registration.RunID = "run-test-2" }},
		{name: "different team", change: func(f *fixture) { f.registration.TeamID++ }},
		{name: "different actor", change: func(f *fixture) { f.registration.ActorID++ }},
		{name: "actor rebound", change: func(f *fixture) { f.registration.ActorEpoch++ }},
		{name: "restored execution", change: func(f *fixture) { f.registration.ExecutionID = "execution-test-2" }},
		{name: "key replaced", change: func(f *fixture) { f.registration.RelayKeySHA256 = identity.KeySHA256(otherCertificate) }},
		{name: "revoked run", change: func(f *fixture) { f.registration.Revoked = true }},
		{name: "expired lease", change: func(f *fixture) { f.registration.LeaseExpiresAt = f.now }},
		{name: "missing lease", change: func(f *fixture) { f.registration.LeaseExpiresAt = time.Time{} }},
		{name: "domain fronting", request: func(r *http.Request) { r.Host = "other.example.com" }},
		{name: "different SNI", request: func(r *http.Request) { r.TLS.ServerName = "other.example.com" }},
		{name: "unregistered port", request: func(r *http.Request) { r.Host += ":8443" }},
		{name: "bracketed DNS authority", request: func(r *http.Request) { r.Host = "[run-test-1.example.com]:443" }},
		{name: "malformed registered port", change: func(f *fixture) {
			f.registration.Authority += ":0443"
			f.request.Host = f.registration.Authority
		}},
		{name: "trailing dot", change: func(f *fixture) {
			f.registration.Authority += "."
			f.request.Host, f.request.TLS.ServerName = f.registration.Authority, f.registration.Authority
		}},
		{name: "wildcard authority", change: func(f *fixture) {
			f.registration.Authority, f.request.Host, f.request.TLS.ServerName = "*.example.com", "*.example.com", "*.example.com"
		}},
		{name: "IP authority", change: func(f *fixture) {
			f.registration.Authority, f.request.Host, f.request.TLS.ServerName = "127.0.0.1", "127.0.0.1", "127.0.0.1"
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newFixture(t, key, certificate)
			if tc.change != nil {
				tc.change(f)
			}
			f.sign(t)
			if tc.request != nil {
				tc.request(f.request)
			}
			v := f.verifier(t, map[string]*rsa.PublicKey{"current": &key.PublicKey})
			got, err := v.Authorize(f.request)
			if tc.allowed {
				if err != nil || got != f.registration {
					t.Fatalf("Authorize() = %#v, %v; want registered run", got, err)
				}
			} else {
				wantError := tc.wantError
				if wantError == nil {
					wantError = identity.ErrUnauthorized
				}
				if !errors.Is(err, wantError) || got != (identity.Registration{}) {
					t.Fatalf("Authorize() = %#v, %v; want no authority and %v", got, err, wantError)
				}
			}
		})
	}
}

func TestAuthorizeLookupDeadline(t *testing.T) {
	key, certificate := signingKey(t), relayCertificate(t)
	for _, tc := range []struct {
		name               string
		parentTimeout      time.Duration
		cancelDuringLookup bool
		wantDuration       time.Duration
	}{
		{name: "lookup timeout", wantDuration: 2 * time.Second},
		{name: "earlier request deadline", parentTimeout: time.Second, wantDuration: time.Second},
		{name: "later request deadline", parentTimeout: 3 * time.Second, wantDuration: 2 * time.Second},
		{name: "request canceled during lookup", cancelDuringLookup: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			synctest.Test(t, func(t *testing.T) {
				f := newFixture(t, key, certificate)
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				if tc.parentTimeout > 0 {
					var timeoutCancel context.CancelFunc
					ctx, timeoutCancel = context.WithTimeout(ctx, tc.parentTimeout)
					defer timeoutCancel()
				}
				f.request = f.request.WithContext(ctx)
				f.sign(t)
				config := f.config(map[string]*rsa.PublicKey{"current": &key.PublicKey})
				config.LookupTimeout = 2 * time.Second
				config.Lookup = func(ctx context.Context, _ string) (identity.Registration, error) {
					if tc.cancelDuringLookup {
						cancel()
					}
					<-ctx.Done()
					return f.registration, nil
				}
				verifier, err := identity.New(config)
				if err != nil {
					t.Fatal(err)
				}
				start := time.Now()
				got, err := verifier.Authorize(f.request)
				if !errors.Is(err, identity.ErrUnavailable) || got != (identity.Registration{}) {
					t.Fatalf("Authorize() = %#v, %v; want no authority and unavailable", got, err)
				}
				if elapsed := time.Since(start); elapsed != tc.wantDuration {
					t.Fatalf("virtual lookup duration = %v, want %v", elapsed, tc.wantDuration)
				}
			})
		})
	}
}

func TestAuthorizeRechecksTimeAfterLookup(t *testing.T) {
	key, certificate := signingKey(t), relayCertificate(t)
	for _, item := range []struct {
		name   string
		change func(*fixture)
	}{
		{name: "lease expires during lookup", change: func(f *fixture) {
			f.afterLookup = func() { f.now = f.registration.LeaseExpiresAt }
		}},
		{name: "capability expires during lookup", change: func(f *fixture) {
			f.registration.LeaseExpiresAt = f.now.Add(time.Hour)
			f.afterLookup = func() { f.now = f.claims.ExpiresAt.Time }
		}},
		{name: "certificate expires on reused connection", change: func(f *fixture) {
			f.now = certificate.NotAfter.Add(-time.Second)
			f.claims.IssuedAt = jwt.NewNumericDate(f.now)
			f.claims.ExpiresAt = jwt.NewNumericDate(f.now.Add(time.Minute))
			f.registration.LeaseExpiresAt = f.now.Add(5 * time.Second)
			f.afterLookup = func() { f.now = certificate.NotAfter }
		}},
		{name: "authority expires during lookup", change: func(f *fixture) {
			expires := f.now.Add(time.Second)
			f.request.TLS.VerifiedChains[0] = append(f.request.TLS.VerifiedChains[0], &x509.Certificate{NotBefore: f.now.Add(-time.Hour), NotAfter: expires})
			f.afterLookup = func() { f.now = expires }
		}},
	} {
		t.Run(item.name, func(t *testing.T) {
			f := newFixture(t, key, certificate)
			item.change(f)
			f.sign(t)
			if _, err := f.verifier(t, map[string]*rsa.PublicKey{"current": &key.PublicKey}).Authorize(f.request); !errors.Is(err, identity.ErrUnauthorized) {
				t.Fatalf("Authorize() error = %v; want expired authority rejected", err)
			}
		})
	}
}

func TestSigningKeyRotation(t *testing.T) {
	current, previous, certificate := signingKey(t), signingKey(t), relayCertificate(t)
	keys := map[string]*rsa.PublicKey{"current": &current.PublicKey, "previous": &previous.PublicKey}
	f := newFixture(t, previous, certificate)
	f.kid = "previous"
	f.sign(t)
	if _, err := f.verifier(t, keys).Authorize(f.request); err != nil {
		t.Fatalf("overlapping previous key rejected: %v", err)
	}
	delete(keys, "previous")
	if _, err := f.verifier(t, keys).Authorize(f.request); !errors.Is(err, identity.ErrUnauthorized) {
		t.Fatalf("retired signing key accepted: %v", err)
	}
}
