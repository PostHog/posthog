package products

import (
	"strings"
	"testing"

	"github.com/posthog/posthog/services/llm-gateway/internal/auth"
	"github.com/posthog/posthog/services/llm-gateway/internal/config"
)

func TestValidateProductAliases(t *testing.T) {
	if ResolveAlias("array") != "posthog_code" || ResolveAlias("slack-twig") != "slack-posthog-code" {
		t.Fatal("product alias not resolved")
	}
	if err := Validate("wizard"); err != nil {
		t.Fatal(err)
	}
	if err := Validate("invalid"); err == nil || !strings.Contains(err.Error(), "Invalid product") {
		t.Fatal("invalid product accepted")
	}
}

func TestProductAccess(t *testing.T) {
	settings := &config.Settings{Debug: false}
	user := &auth.User{AuthMethod: "personal_api_key"}
	if allowed, _ := CheckAccess(settings, "posthog_code", user, "claude-sonnet-4-6", "anthropic"); allowed {
		t.Fatal("api key allowed for oauth-only product")
	}
	appID := PostHogCodeUSAppID
	oauthUser := &auth.User{AuthMethod: "oauth_access_token", ApplicationID: &appID}
	if allowed, msg := CheckAccess(settings, "posthog_code", oauthUser, "claude-sonnet-4-6", "anthropic"); !allowed {
		t.Fatalf("oauth user rejected: %s", msg)
	}
	if allowed, _ := CheckAccess(settings, "posthog_code", oauthUser, "gpt-4.1-mini", "openai"); allowed {
		t.Fatal("disallowed model accepted")
	}
}
