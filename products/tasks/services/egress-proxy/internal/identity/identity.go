package identity

import (
	"context"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"errors"
	"math/big"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const Audience = "posthog:agent_egress"

var (
	ErrUnauthorized = errors.New("unauthorized run")
	ErrUnavailable  = errors.New("run authorization unavailable")
)

type Claims struct {
	jwt.RegisteredClaims
	TeamID         int64  `json:"team_id"`
	ActorID        int64  `json:"actor_id"`
	ActorEpoch     uint64 `json:"actor_epoch"`
	ExecutionID    string `json:"execution_id"`
	RelayKeySHA256 string `json:"relay_key_sha256"`
}

type Registration struct {
	RunID          string
	TeamID         int64
	ActorID        int64
	ActorEpoch     uint64
	ExecutionID    string
	RelayKeySHA256 string
	Authority      string
	LeaseExpiresAt time.Time
	Revoked        bool
}

type Lookup func(context.Context, string) (Registration, error)

type Config struct {
	Issuer        string
	Keys          map[string]*rsa.PublicKey
	Lookup        Lookup
	Now           func() time.Time
	MaxLifetime   time.Duration
	LookupTimeout time.Duration
	ClockSkew     time.Duration
}

type Verifier struct {
	keys          map[string]*rsa.PublicKey
	lookup        Lookup
	now           func() time.Time
	maxLifetime   time.Duration
	lookupTimeout time.Duration
	clockSkew     time.Duration
	parser        *jwt.Parser
}

func New(config Config) (*Verifier, error) {
	if config.Issuer == "" || config.Lookup == nil || config.MaxLifetime <= 0 ||
		config.LookupTimeout <= 0 || config.ClockSkew < 0 || len(config.Keys) == 0 {
		return nil, errors.New("invalid verifier configuration")
	}
	keys := make(map[string]*rsa.PublicKey, len(config.Keys))
	for id, key := range config.Keys {
		if id == "" || key == nil || key.N == nil || key.N.Sign() <= 0 || key.N.BitLen() < 2048 || key.E < 3 || key.E%2 == 0 {
			return nil, errors.New("invalid verification key")
		}
		keys[id] = &rsa.PublicKey{N: new(big.Int).Set(key.N), E: key.E}
	}
	if config.Now == nil {
		config.Now = time.Now
	}
	return &Verifier{
		keys:          keys,
		lookup:        config.Lookup,
		now:           config.Now,
		maxLifetime:   config.MaxLifetime,
		lookupTimeout: config.LookupTimeout,
		clockSkew:     config.ClockSkew,
		parser: jwt.NewParser(
			jwt.WithValidMethods([]string{jwt.SigningMethodRS256.Alg()}),
			jwt.WithAudience(Audience),
			jwt.WithIssuer(config.Issuer),
			jwt.WithExpirationRequired(),
			jwt.WithIssuedAt(),
			jwt.WithLeeway(config.ClockSkew),
			jwt.WithStrictDecoding(),
			jwt.WithTimeFunc(config.Now),
		),
	}, nil
}

func validVerifiedChain(chains [][]*x509.Certificate, leaf *x509.Certificate, now time.Time) bool {
	for _, chain := range chains {
		if len(chain) == 0 || chain[0] == nil || !chain[0].Equal(leaf) {
			continue
		}
		valid := true
		for _, cert := range chain {
			if cert == nil || now.Before(cert.NotBefore) || !now.Before(cert.NotAfter) {
				valid = false
				break
			}
		}
		if valid {
			return true
		}
	}
	return false
}

func (v *Verifier) Authorize(r *http.Request) (Registration, error) {
	if r == nil || r.TLS == nil || !r.TLS.HandshakeComplete ||
		len(r.TLS.PeerCertificates) == 0 || r.TLS.PeerCertificates[0] == nil {
		return Registration{}, ErrUnauthorized
	}
	leaf := r.TLS.PeerCertificates[0]
	if !validVerifiedChain(r.TLS.VerifiedChains, leaf, v.now()) {
		return Registration{}, ErrUnauthorized
	}
	values := r.Header.Values("Authorization")
	if len(values) != 1 {
		return Registration{}, ErrUnauthorized
	}
	scheme, encoded, ok := strings.Cut(values[0], " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") || encoded == "" || len(encoded) > 8192 || strings.ContainsAny(encoded, " \t\r\n") {
		return Registration{}, ErrUnauthorized
	}
	claims := new(Claims)
	if _, err := v.parser.ParseWithClaims(encoded, claims, v.verificationKey); err != nil || !claims.valid(v.now(), v.maxLifetime, v.clockSkew) || claims.RelayKeySHA256 != KeySHA256(leaf) {
		return Registration{}, ErrUnauthorized
	}
	ctx, cancel := context.WithTimeout(r.Context(), v.lookupTimeout)
	defer cancel()
	if ctx.Err() != nil {
		return Registration{}, ErrUnavailable
	}
	registration, err := v.lookup(ctx, claims.Subject)
	if ctx.Err() != nil {
		return Registration{}, ErrUnavailable
	}
	if err != nil {
		if errors.Is(err, ErrUnauthorized) {
			return Registration{}, ErrUnauthorized
		}
		return Registration{}, ErrUnavailable
	}
	now := v.now()
	host, port, valid := parseAuthority(registration.Authority)
	requestHost, requestPort, requestValid := parseAuthority(r.Host)
	if !claims.valid(now, v.maxLifetime, v.clockSkew) || !validVerifiedChain(r.TLS.VerifiedChains, leaf, now) ||
		!registration.matches(claims, now) || !valid || !requestValid ||
		registration.Authority != strings.ToLower(registration.Authority) ||
		!strings.EqualFold(r.TLS.ServerName, host) || requestHost != host || requestPort != port {
		return Registration{}, ErrUnauthorized
	}
	return registration, nil
}

func (v *Verifier) verificationKey(token *jwt.Token) (any, error) {
	id, ok := token.Header["kid"].(string)
	if !ok || v.keys[id] == nil {
		return nil, ErrUnauthorized
	}
	return v.keys[id], nil
}

func (c *Claims) valid(now time.Time, maxLifetime, clockSkew time.Duration) bool {
	if c.Subject == "" || c.TeamID <= 0 || c.ActorID <= 0 || c.ActorEpoch == 0 ||
		c.ExecutionID == "" || c.RelayKeySHA256 == "" || len(c.Audience) != 1 ||
		c.Audience[0] != Audience || c.IssuedAt == nil || c.ExpiresAt == nil {
		return false
	}
	lifetime := c.ExpiresAt.Sub(c.IssuedAt.Time)
	return lifetime > 0 && lifetime <= maxLifetime && !now.Add(clockSkew).Before(c.IssuedAt.Time) &&
		now.Before(c.ExpiresAt.Time) && (c.NotBefore == nil ||
		c.NotBefore.Before(c.ExpiresAt.Time) && !now.Add(clockSkew).Before(c.NotBefore.Time))
}

func (r Registration) matches(c *Claims, now time.Time) bool {
	return !r.Revoked && now.Before(r.LeaseExpiresAt) && r.RunID == c.Subject &&
		r.TeamID == c.TeamID && r.ActorID == c.ActorID && r.ActorEpoch == c.ActorEpoch &&
		r.ExecutionID == c.ExecutionID && r.RelayKeySHA256 == c.RelayKeySHA256
}

func parseAuthority(authority string) (string, string, bool) {
	host, port := authority, "443"
	if strings.Contains(authority, ":") {
		var err error
		host, port, err = net.SplitHostPort(authority)
		if err != nil {
			return "", "", false
		}
		number, err := strconv.Atoi(port)
		if err != nil || number < 1 || number > 65535 || strconv.Itoa(number) != port {
			return "", "", false
		}
	}
	host = strings.ToLower(host)
	if len(host) > 253 || net.ParseIP(host) != nil ||
		strings.Contains(authority, ":") && strings.ToLower(authority) != net.JoinHostPort(host, port) {
		return "", "", false
	}
	labels := strings.Split(host, ".")
	if len(labels) < 2 && host != "localhost" {
		return "", "", false
	}
	for _, label := range labels {
		if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return "", "", false
		}
		for _, char := range label {
			if !(char >= 'a' && char <= 'z' || char >= '0' && char <= '9' || char == '-') {
				return "", "", false
			}
		}
	}
	return host, port, true
}

func KeySHA256(cert *x509.Certificate) string {
	hash := sha256.Sum256(cert.RawSubjectPublicKeyInfo)
	return base64.RawURLEncoding.EncodeToString(hash[:])
}
