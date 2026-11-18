package app_test

import (
	"testing"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/app"
)

func TestConfigurationRejectsUnsafeLimitsAndListeners(t *testing.T) {
	for _, tc := range []struct {
		name string
		data string
	}{
		{"unknown field", `{"registry_siging_key_file":"key"}`},
		{"trailing data", `{} {}`},
		{"public administration", `{"admin_address":"0.0.0.0:9090"}`},
		{"hostname administration", `{"admin_address":"localhost:9090"}`},
		{"invalid port", `{"listen_address":"127.0.0.1:65536"}`},
		{"disabled request timeout", `{"request_timeout_seconds":0}`},
		{"disabled shutdown timeout", `{"shutdown_timeout_seconds":0}`},
		{"unbounded cache", `{"cache_entries":1000001}`},
		{"unbounded lookups", `{"cache_lookups":10001}`},
		{"insufficient audit reservation", `{"audit_capacity":1}`},
		{"lookup exceeds request budget", `{"lookup_timeout_seconds":31}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			path := writeTestFile(t, "config.json", []byte(tc.data))
			if _, err := app.LoadProxyConfig(path); err == nil {
				t.Fatal("unsafe configuration was accepted")
			}
		})
	}
	if _, err := app.LoadRelayConfig(writeTestFile(t, "relay.json", []byte(`{"admin_address":"[::]:9090"}`))); err == nil {
		t.Fatal("relay accepted public administration listener")
	}
}
