package app_test

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestCertificateMetricsFollowAcceptedReloads(t *testing.T) {
	f := newProxyFixture(t, func(f *proxyFixture) { f.config.ServerCAFile = f.ca.certFile })
	scrape := func() string {
		t.Helper()
		response := httptest.NewRecorder()
		f.metrics.Handler().ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
		if response.Code != http.StatusOK {
			t.Fatalf("metrics status = %d", response.Code)
		}
		return response.Body.String()
	}
	assertExpiry := func(data, role string, expiry time.Time) {
		t.Helper()
		want := fmt.Sprintf("egress_certificate_expiration_timestamp_seconds{role=%q} %s\n", role, fmt.Sprint(float64(expiry.Unix())))
		if !strings.Contains(data, want) {
			t.Fatalf("missing %s in %s", want, data)
		}
	}
	before := scrape()
	for _, role := range []string{"client_ca", "server_ca"} {
		assertExpiry(before, role, f.ca.certificate.NotAfter)
	}
	for _, role := range []string{"server", "registry_ca"} {
		if !strings.Contains(before, fmt.Sprintf("role=%q", role)) {
			t.Fatalf("missing TLS role %q", role)
		}
	}
	replacement := issueTestCertificateUntil(t, nil, false, time.Now().Add(24*time.Hour))
	data, err := os.ReadFile(replacement.certFile)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(f.config.ClientCAFile, data, 0600); err != nil {
		t.Fatal(err)
	}
	if scrape() != before {
		t.Fatal("unloaded files changed certificate metrics")
	}
	keys, err := os.ReadFile(f.config.VerificationKeysFile)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(f.config.VerificationKeysFile, []byte("invalid bundle"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.proxy.Reload(); err == nil {
		t.Fatal("invalid reload succeeded")
	}
	if scrape() != before {
		t.Fatal("failed reload changed certificate metrics")
	}
	if err := os.WriteFile(f.config.VerificationKeysFile, keys, 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	assertExpiry(scrape(), "client_ca", replacement.certificate.NotAfter)
	earlier := issueTestCertificateUntil(t, nil, false, time.Now().Add(-time.Minute))
	earlierPEM, err := os.ReadFile(earlier.certFile)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(f.config.ClientCAFile, append(data, earlierPEM...), 0600); err != nil {
		t.Fatal(err)
	}
	if err := f.proxy.Reload(); err != nil {
		t.Fatal(err)
	}
	assertExpiry(scrape(), "client_ca", earlier.certificate.NotAfter)
}
