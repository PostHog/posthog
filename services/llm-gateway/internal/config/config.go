package config

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

type ProductCostLimit struct {
	LimitUSD      float64 `json:"limit_usd"`
	WindowSeconds int     `json:"window_seconds"`
}

type UserCostLimit struct {
	BurstLimitUSD          float64 `json:"burst_limit_usd"`
	BurstWindowSeconds     int     `json:"burst_window_seconds"`
	SustainedLimitUSD      float64 `json:"sustained_limit_usd"`
	SustainedWindowSeconds int     `json:"sustained_window_seconds"`
}

type Settings struct {
	Debug                    bool
	Port                     string
	DatabaseURL              string
	DBPoolMinSize            int
	DBPoolMaxSize            int
	RedisURL                 string
	RequestTimeout           time.Duration
	StreamingTimeout         time.Duration
	MaxRequestBodySize       int64
	CorsOrigins              []string
	AnthropicAPIKey          string
	BedrockRegionName        string
	OpenAIAPIKey             string
	OpenAIAPIBaseURL         string
	OpenRouterAPIKey         string
	FireworksAPIKey          string
	PostHogProjectToken      string
	PostHogHost              string
	MetricsEnabled           bool
	AuthCacheMaxSize         int
	AuthCacheTTL             time.Duration
	AuthCacheTTLOAuth        time.Duration
	TeamRateLimitMultipliers map[int]int
	ProductCostLimits        map[string]ProductCostLimit
	UserCostLimits           map[string]UserCostLimit
	UserCostLimitsDisabled   bool
	DefaultFallbackCostUSD   float64
	PostHogAPIBaseURL        string
	PlanCacheTTL             time.Duration
	BillingPeriodDays        int
}

func Load() (*Settings, error) {
	settings := &Settings{
		Debug:                    boolEnv("LLM_GATEWAY_DEBUG", false),
		Port:                     stringEnv("LLM_GATEWAY_PORT", "3308"),
		DatabaseURL:              stringEnv("LLM_GATEWAY_DATABASE_URL", "postgres://posthog:posthog@localhost:5432/posthog"),
		DBPoolMinSize:            intEnv("LLM_GATEWAY_DB_POOL_MIN_SIZE", 2),
		DBPoolMaxSize:            intEnv("LLM_GATEWAY_DB_POOL_MAX_SIZE", 10),
		RedisURL:                 stringEnv("LLM_GATEWAY_REDIS_URL", ""),
		RequestTimeout:           durationEnv("LLM_GATEWAY_REQUEST_TIMEOUT", 300*time.Second),
		StreamingTimeout:         durationEnv("LLM_GATEWAY_STREAMING_TIMEOUT", 300*time.Second),
		MaxRequestBodySize:       int64(intEnv("LLM_GATEWAY_MAX_REQUEST_BODY_SIZE", 10485760)),
		CorsOrigins:              listEnv("LLM_GATEWAY_CORS_ORIGINS", []string{"*"}),
		AnthropicAPIKey:          firstNonEmpty(os.Getenv("LLM_GATEWAY_ANTHROPIC_API_KEY"), os.Getenv("ANTHROPIC_API_KEY")),
		BedrockRegionName:        firstNonEmpty(os.Getenv("LLM_GATEWAY_BEDROCK_REGION_NAME"), os.Getenv("AWS_REGION"), os.Getenv("AWS_DEFAULT_REGION")),
		OpenAIAPIKey:             firstNonEmpty(os.Getenv("LLM_GATEWAY_OPENAI_API_KEY"), os.Getenv("OPENAI_API_KEY")),
		OpenAIAPIBaseURL:         firstNonEmpty(os.Getenv("LLM_GATEWAY_OPENAI_API_BASE_URL"), os.Getenv("OPENAI_BASE_URL")),
		OpenRouterAPIKey:         firstNonEmpty(os.Getenv("LLM_GATEWAY_OPENROUTER_API_KEY"), os.Getenv("OPENROUTER_API_KEY")),
		FireworksAPIKey:          firstNonEmpty(os.Getenv("LLM_GATEWAY_FIREWORKS_API_KEY"), os.Getenv("FIREWORKS_API_KEY")),
		PostHogProjectToken:      os.Getenv("LLM_GATEWAY_POSTHOG_PROJECT_TOKEN"),
		PostHogHost:              stringEnv("LLM_GATEWAY_POSTHOG_HOST", "https://us.i.posthog.com"),
		MetricsEnabled:           boolEnv("LLM_GATEWAY_METRICS_ENABLED", true),
		AuthCacheMaxSize:         intEnv("LLM_GATEWAY_AUTH_CACHE_MAX_SIZE", 10000),
		AuthCacheTTL:             time.Duration(intEnv("LLM_GATEWAY_AUTH_CACHE_TTL", 900)) * time.Second,
		AuthCacheTTLOAuth:        time.Duration(intEnv("LLM_GATEWAY_AUTH_CACHE_TTL_OAUTH", 300)) * time.Second,
		TeamRateLimitMultipliers: map[int]int{},
		ProductCostLimits: map[string]ProductCostLimit{
			"llm_gateway":       {LimitUSD: 1000, WindowSeconds: 86400},
			"wizard":            {LimitUSD: 2000, WindowSeconds: 86400},
			"posthog_code":      {LimitUSD: 1000, WindowSeconds: 3600},
			"background_agents": {LimitUSD: 1000, WindowSeconds: 3600},
			"django":            {LimitUSD: 5000, WindowSeconds: 86400},
		},
		UserCostLimits: map[string]UserCostLimit{
			"wizard":            {BurstLimitUSD: 100, BurstWindowSeconds: 2592000, SustainedLimitUSD: 100, SustainedWindowSeconds: 2592000},
			"posthog_code":      {BurstLimitUSD: 200, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000},
			"background_agents": {BurstLimitUSD: 100, BurstWindowSeconds: 86400, SustainedLimitUSD: 1000, SustainedWindowSeconds: 2592000},
		},
		UserCostLimitsDisabled: boolEnv("LLM_GATEWAY_USER_COST_LIMITS_DISABLED", false),
		DefaultFallbackCostUSD: floatEnv("LLM_GATEWAY_DEFAULT_FALLBACK_COST_USD", 0.01),
		PostHogAPIBaseURL:      stringEnv("LLM_GATEWAY_POSTHOG_API_BASE_URL", "https://us.posthog.com"),
		PlanCacheTTL:           time.Duration(intEnv("LLM_GATEWAY_PLAN_CACHE_TTL", 900)) * time.Second,
		BillingPeriodDays:      intEnv("LLM_GATEWAY_BILLING_PERIOD_DAYS", 30),
	}
	if err := parseJSONEnv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", &settings.TeamRateLimitMultipliers); err != nil {
		return nil, err
	}
	if err := parseCostLimits("LLM_GATEWAY_PRODUCT_COST_LIMITS", settings.ProductCostLimits); err != nil {
		return nil, err
	}
	if err := parseUserCostLimits("LLM_GATEWAY_USER_COST_LIMITS", settings.UserCostLimits); err != nil {
		return nil, err
	}
	normalizeCostAliases(settings)
	return settings, nil
}

func normalizeCostAliases(settings *Settings) {
	aliases := map[string]string{"array": "posthog_code", "twig": "posthog_code", "slack-twig": "slack-posthog-code"}
	for alias, target := range aliases {
		if value, ok := settings.ProductCostLimits[alias]; ok {
			settings.ProductCostLimits[target] = value
			delete(settings.ProductCostLimits, alias)
		}
		if value, ok := settings.UserCostLimits[alias]; ok {
			settings.UserCostLimits[target] = value
			delete(settings.UserCostLimits, alias)
		}
	}
}

func parseCostLimits(key string, target map[string]ProductCostLimit) error {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return nil
	}
	parsed := map[string]ProductCostLimit{}
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		return fmt.Errorf("invalid JSON in %s: %w", strings.ToLower(strings.TrimPrefix(key, "LLM_GATEWAY_")), err)
	}
	for k, v := range parsed {
		target[k] = v
	}
	return nil
}

func parseUserCostLimits(key string, target map[string]UserCostLimit) error {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return nil
	}
	parsed := map[string]UserCostLimit{}
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		return fmt.Errorf("invalid JSON in %s: %w", strings.ToLower(strings.TrimPrefix(key, "LLM_GATEWAY_")), err)
	}
	for k, v := range parsed {
		target[k] = v
	}
	return nil
}

func parseJSONEnv[T any](key string, target *T) error {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return nil
	}
	if err := json.Unmarshal([]byte(raw), target); err != nil {
		return fmt.Errorf("invalid JSON in %s: %w", strings.ToLower(strings.TrimPrefix(key, "LLM_GATEWAY_")), err)
	}
	return nil
}

func stringEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	if value := os.Getenv(key); value != "" {
		parsed, err := strconv.Atoi(value)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func floatEnv(key string, fallback float64) float64 {
	if value := os.Getenv(key); value != "" {
		parsed, err := strconv.ParseFloat(value, 64)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func boolEnv(key string, fallback bool) bool {
	if value := os.Getenv(key); value != "" {
		parsed, err := strconv.ParseBool(value)
		if err == nil {
			return parsed
		}
	}
	return fallback
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.ParseFloat(value, 64); err == nil {
			return time.Duration(parsed * float64(time.Second))
		}
		if parsed, err := time.ParseDuration(value); err == nil {
			return parsed
		}
	}
	return fallback
}

func listEnv(key string, fallback []string) []string {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	var parsed []string
	if json.Unmarshal([]byte(raw), &parsed) == nil {
		return parsed
	}
	return strings.Split(raw, ",")
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
