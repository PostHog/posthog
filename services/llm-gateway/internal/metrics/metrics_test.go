package metrics

import (
	"strings"
	"testing"
)

func TestMetricsExport(t *testing.T) {
	RequestCount.WithLabelValues("test", "openai", "gpt-4", "200", "personal_api_key", "llm_gateway").Inc()
	RequestLatency.WithLabelValues("test", "openai", "false", "llm_gateway").Observe(0.1)
	TokensInput.WithLabelValues("openai", "gpt-4", "llm_gateway").Inc()
	TokensOutput.WithLabelValues("openai", "gpt-4", "llm_gateway").Inc()
	ProviderErrors.WithLabelValues("openai", "timeout", "llm_gateway").Inc()
	ActiveStreams.WithLabelValues("openai", "gpt-4", "llm_gateway").Set(1)
	ConcurrentRequests.WithLabelValues("openai", "gpt-4", "llm_gateway").Set(1)
	names := []string{"llm_gateway_requests_total", "llm_gateway_request_duration_seconds", "llm_gateway_tokens_input_total", "llm_gateway_tokens_output_total", "llm_gateway_provider_errors_total", "llm_gateway_active_streams", "llm_gateway_concurrent_requests"}
	families, err := Registry.Gather()
	if err != nil {
		t.Fatal(err)
	}
	output := ""
	for _, family := range families {
		output += family.GetName() + "\n"
	}
	for _, name := range names {
		if !strings.Contains(output, name) {
			t.Fatalf("missing metric %s", name)
		}
	}
}

func TestCountersAcceptLargeValues(t *testing.T) {
	TokensInput.WithLabelValues("anthropic", "claude-3", "llm_gateway").Add(100000)
	if _, err := Registry.Gather(); err != nil {
		t.Fatal(err)
	}
}
