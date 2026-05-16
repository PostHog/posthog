package auth

import "testing"

func TestExtractToken(t *testing.T) {
	tests := []struct {
		name     string
		headers  map[string][]string
		expected string
	}{
		{"bearer", map[string][]string{"Authorization": {"Bearer phx_test"}}, "phx_test"},
		{"lowercase bearer", map[string][]string{"Authorization": {"bearer pha_test"}}, "pha_test"},
		{"api key precedence", map[string][]string{"X-Api-Key": {" phx_key "}, "Authorization": {"Bearer bearer"}}, "phx_key"},
		{"basic rejected", map[string][]string{"Authorization": {"Basic nope"}}, ""},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if got := ExtractToken(test.headers); got != test.expected {
				t.Fatalf("got %q, want %q", got, test.expected)
			}
		})
	}
}

func TestScopeRules(t *testing.T) {
	if !hasRequiredScope([]string{"llm_gateway:read"}, false) {
		t.Fatal("required scope rejected")
	}
	if hasRequiredScope([]string{"*"}, false) {
		t.Fatal("personal wildcard accepted")
	}
	if !hasRequiredScope([]string{"*"}, true) {
		t.Fatal("oauth wildcard rejected")
	}
}

func TestPersonalHashFormat(t *testing.T) {
	got := "sha256$" + sha256Hex("test_key")
	if len(got) != 71 || got[:7] != "sha256$" {
		t.Fatalf("invalid hash format: %s", got)
	}
	if got != "sha256$"+sha256Hex("test_key") {
		t.Fatal("hash is not deterministic")
	}
}
