package products

import (
	"fmt"
	"sort"
	"strings"

	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
)

type ProductConfig struct {
	AllowedApplicationIDs map[string]bool
	AllowedModels         []string
	AllowAPIKeys          bool
}

const (
	PostHogCodeUSAppID = "019a3066-4aa2-0000-ca70-48ecdcc519cf"
	PostHogCodeEUAppID = "019a3067-5be7-0000-33c7-c6743eb59a79"
	WizardUSAppID      = "019a0c79-b69d-0000-f31b-b41345208c9d"
	WizardEUAppID      = "019a12d0-6edd-0000-0458-86616af3a3db"
)

var aliases = map[string]string{"array": "posthog_code", "twig": "posthog_code", "slack-twig": "slack-posthog-code"}

var Products = map[string]ProductConfig{
	"llm_gateway":                       {AllowedApplicationIDs: nil, AllowedModels: nil, AllowAPIKeys: true},
	"posthog_code":                      {AllowedApplicationIDs: ids(PostHogCodeUSAppID, PostHogCodeEUAppID), AllowedModels: models("claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5-mini"), AllowAPIKeys: false},
	"background_agents":                 {AllowedApplicationIDs: ids(PostHogCodeUSAppID, PostHogCodeEUAppID), AllowedModels: models("claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-sonnet-4-5", "claude-haiku-4-5", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2", "gpt-5-mini"), AllowAPIKeys: false},
	"wizard":                            {AllowedApplicationIDs: ids(WizardUSAppID, WizardEUAppID), AllowedModels: nil, AllowAPIKeys: true},
	"llma_labeling":                     {AllowedApplicationIDs: nil, AllowedModels: models("gpt-5.4"), AllowAPIKeys: true},
	"django":                            {AllowedApplicationIDs: nil, AllowedModels: nil, AllowAPIKeys: true},
	"slack-posthog-code":                {AllowedApplicationIDs: nil, AllowedModels: models("claude-haiku-4-5"), AllowAPIKeys: true},
	"growth":                            {AllowedApplicationIDs: nil, AllowedModels: nil, AllowAPIKeys: true},
	"llma_translation":                  {AllowedApplicationIDs: nil, AllowedModels: models("gpt-4.1-mini"), AllowAPIKeys: true},
	"llma_summarization":                {AllowedApplicationIDs: nil, AllowedModels: models("gpt-4.1-nano", "gpt-4.1-mini"), AllowAPIKeys: true},
	"llma_eval_summary":                 {AllowedApplicationIDs: nil, AllowedModels: models("gpt-5-mini"), AllowAPIKeys: true},
	"customer_archetype_classification": {AllowedApplicationIDs: nil, AllowedModels: models("gpt-5-mini"), AllowAPIKeys: true},
	"product_analytics":                 {AllowedApplicationIDs: nil, AllowedModels: models("gpt-4.1-mini"), AllowAPIKeys: true},
	"signals":                           {AllowedApplicationIDs: ids(PostHogCodeUSAppID, PostHogCodeEUAppID), AllowedModels: nil, AllowAPIKeys: false},
	"subscriptions":                     {AllowedApplicationIDs: nil, AllowedModels: models("gpt-4.1-mini"), AllowAPIKeys: true},
}

func ResolveAlias(product string) string {
	if resolved, ok := aliases[product]; ok {
		return resolved
	}
	return product
}

func Validate(product string) error {
	if _, ok := Products[ResolveAlias(product)]; ok {
		return nil
	}
	names := make([]string, 0, len(Products))
	for name := range Products {
		names = append(names, name)
	}
	sort.Strings(names)
	return fmt.Errorf("Invalid product '%s'. Allowed products: %s", product, strings.Join(names, ", "))
}

func CheckAccess(settings *config.Settings, product string, user *auth.User, model string, provider string) (bool, string) {
	cfg, ok := Products[ResolveAlias(product)]
	if !ok {
		return false, "Unknown product: " + product
	}
	if user.AuthMethod == "personal_api_key" && !cfg.AllowAPIKeys {
		return false, fmt.Sprintf("Product '%s' requires OAuth authentication", product)
	}
	if user.AuthMethod == "oauth_access_token" && !settings.Debug {
		if user.ApplicationID == nil || !cfg.AllowedApplicationIDs[*user.ApplicationID] {
			return false, fmt.Sprintf("OAuth application not authorized for product '%s'", product)
		}
	}
	if model != "" && cfg.AllowedModels != nil {
		normalized := strings.ToLower(model)
		matched := false
		for _, allowed := range cfg.AllowedModels {
			if strings.HasPrefix(normalized, strings.ToLower(allowed)) {
				matched = true
				break
			}
		}
		if provider == "bedrock" && !matched {
			for _, allowed := range cfg.AllowedModels {
				allowedLower := strings.ToLower(allowed)
				if strings.Contains(normalized, "."+allowedLower) || strings.Contains(normalized, ":"+allowedLower) || strings.Contains(normalized, "/"+allowedLower) {
					matched = true
					break
				}
			}
		}
		if !matched {
			return false, fmt.Sprintf("Model '%s' not allowed for product '%s'", model, product)
		}
	}
	return true, ""
}

func ids(values ...string) map[string]bool {
	result := map[string]bool{}
	for _, value := range values {
		result[value] = true
	}
	return result
}

func models(values ...string) []string { return values }
