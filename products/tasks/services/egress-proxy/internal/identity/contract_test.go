package identity_test

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/identity"
)

func TestPythonCapability(t *testing.T) {
	data, err := os.ReadFile("testdata/python-capability.json")
	if err != nil {
		t.Fatal(err)
	}
	var contract struct {
		Now          time.Time
		Token        string
		Keys         json.RawMessage
		Certificate  string
		Registration identity.Registration
	}
	if err := json.Unmarshal(data, &contract); err != nil {
		t.Fatal(err)
	}
	keys, err := identity.ParseKeyBundle(contract.Keys)
	if err != nil {
		t.Fatal(err)
	}
	block, _ := pem.Decode([]byte(contract.Certificate))
	if block == nil {
		t.Fatal("missing relay certificate")
	}
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		t.Fatal(err)
	}
	verifier, err := identity.New(identity.Config{
		Issuer: "posthog:tasks", Keys: keys, MaxLifetime: 5 * time.Minute,
		LookupTimeout: time.Second, ClockSkew: 3 * time.Second,
		Now: func() time.Time { return contract.Now },
		Lookup: func(_ context.Context, lookup identity.LookupRequest) (identity.Registration, error) {
			if lookup != (identity.LookupRequest{
				TeamID: contract.Registration.TeamID, RunID: contract.Registration.RunID, ExecutionID: contract.Registration.ExecutionID,
			}) {
				return identity.Registration{}, identity.ErrUnauthorized
			}
			return contract.Registration, nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodGet, "https://"+contract.Registration.Authority+"/operation", nil)
	request.Header.Set("Authorization", "Bearer "+contract.Token)
	request.TLS = &tls.ConnectionState{
		HandshakeComplete: true,
		ServerName:        request.URL.Hostname(),
		PeerCertificates:  []*x509.Certificate{certificate},
		VerifiedChains:    [][]*x509.Certificate{{certificate}},
	}
	if got, err := verifier.Authorize(request); err != nil || got != contract.Registration {
		t.Fatalf("Authorize() = %v, %v; want Python-issued run identity", got, err)
	}
}
