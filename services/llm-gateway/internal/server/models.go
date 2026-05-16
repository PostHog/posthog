package server

import (
	"github.com/posthog/posthog/services/llm-gateway/internal/products"
	"net/http"
	"strings"
)

func (a *App) models(w http.ResponseWriter, r *http.Request) {
	product := products.ResolveAlias(pathProduct(r))
	if err := products.Validate(product); err != nil {
		writeJSON(w, 400, map[string]string{"detail": err.Error()})
		return
	}
	models := availableModels(product)
	writeJSON(w, 200, map[string]any{"object": "list", "data": models, "models": models})
}

func availableModels(product string) []map[string]any {
	ids := []string{"gpt-4.1-mini", "gpt-4.1-nano", "gpt-5-mini", "gpt-5.2", "gpt-5.3-codex", "gpt-5.4", "gpt-5.5", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7"}
	cfg := products.Products[products.ResolveAlias(product)]
	if cfg.AllowedModels != nil {
		ids = cfg.AllowedModels
	}
	result := make([]map[string]any, 0, len(ids))
	for _, id := range ids {
		provider := "openai"
		if strings.HasPrefix(id, "claude") {
			provider = "anthropic"
		}
		result = append(result, map[string]any{"id": id, "slug": id, "display_name": id, "object": "model", "created": 1669766400, "owned_by": provider, "context_window": 200000, "supports_streaming": true, "supports_vision": true, "supported_reasoning_levels": []string{}, "shell_type": "default", "visibility": "list", "supported_in_api": true, "priority": 0, "base_instructions": "", "supports_reasoning_summaries": false, "support_verbosity": false, "truncation_policy": map[string]any{"mode": "bytes", "limit": 10000}, "supports_parallel_tool_calls": true, "experimental_supported_tools": []string{}})
	}
	return result
}
