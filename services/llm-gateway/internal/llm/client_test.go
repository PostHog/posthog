package llm

import (
	"encoding/json"
	"testing"
)

func TestSanitizeJSONRemovesDangerousParamsRecursively(t *testing.T) {
	raw := []byte(`{"model":"gpt-4","messages":[{"role":"user","content":"hi"}],"api_key":"stolen","metadata":{"safe":"ok","base_url":"https://attacker.example.com","nested":{"organization":"bad","keep":"yes"}},"model_list":[{"litellm_params":{"api_key":"bad"}}]}`)
	sanitized, err := SanitizeJSON(raw, nil)
	if err != nil {
		t.Fatal(err)
	}
	var body map[string]any
	if err := json.Unmarshal(sanitized, &body); err != nil {
		t.Fatal(err)
	}
	if _, ok := body["api_key"]; ok {
		t.Fatal("api_key was forwarded")
	}
	if _, ok := body["model_list"]; ok {
		t.Fatal("model_list was forwarded")
	}
	metadata := body["metadata"].(map[string]any)
	if _, ok := metadata["base_url"]; ok {
		t.Fatal("nested base_url was forwarded")
	}
	nested := metadata["nested"].(map[string]any)
	if _, ok := nested["organization"]; ok {
		t.Fatal("deep organization was forwarded")
	}
	if metadata["safe"] != "ok" || nested["keep"] != "yes" {
		t.Fatal("safe metadata was not preserved")
	}
}

func TestEnsureOpenAIPrefix(t *testing.T) {
	if EnsureOpenAIPrefix("gpt-4o-mini") != "openai/gpt-4o-mini" {
		t.Fatal("missing openai prefix")
	}
	if EnsureOpenAIPrefix("openai/gpt-4o-mini") != "openai/gpt-4o-mini" {
		t.Fatal("duplicated openai prefix")
	}
}
