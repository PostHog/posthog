package config

import "testing"

func TestLoadParsesJSONEnv(t *testing.T) {
	t.Setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", `{"1":10}`)
	t.Setenv("LLM_GATEWAY_PRODUCT_COST_LIMITS", `{"array":{"limit_usd":2,"window_seconds":3}}`)
	settings, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if settings.TeamRateLimitMultipliers[1] != 10 {
		t.Fatal("team multiplier not parsed")
	}
	if settings.ProductCostLimits["posthog_code"].LimitUSD != 2 {
		t.Fatal("cost alias not normalized")
	}
}
