package tui

import "testing"

func TestParseMatchTokens_plain(t *testing.T) {
	tokens := parseMatchTokens("error")
	if len(tokens) != 1 {
		t.Fatalf("want 1 token, got %d", len(tokens))
	}
	if tokens[0].pattern != "error" || tokens[0].negative || tokens[0].isRegex {
		t.Errorf("unexpected token: %+v", tokens[0])
	}
}

func TestParseMatchTokens_negative(t *testing.T) {
	tokens := parseMatchTokens("!warning")
	if len(tokens) != 1 {
		t.Fatalf("want 1 token, got %d", len(tokens))
	}
	if tokens[0].pattern != "warning" || !tokens[0].negative {
		t.Errorf("unexpected token: %+v", tokens[0])
	}
}

func TestParseMatchTokens_regex(t *testing.T) {
	tokens := parseMatchTokens("re:\\d+")
	if len(tokens) != 1 {
		t.Fatalf("want 1 token, got %d", len(tokens))
	}
	if !tokens[0].isRegex || tokens[0].re == nil {
		t.Errorf("expected compiled regex: %+v", tokens[0])
	}
}

func TestParseMatchTokens_negativeRegex(t *testing.T) {
	tokens := parseMatchTokens("!re:debug")
	if len(tokens) != 1 {
		t.Fatalf("want 1 token, got %d", len(tokens))
	}
	if !tokens[0].negative || !tokens[0].isRegex || tokens[0].re == nil {
		t.Errorf("unexpected token: %+v", tokens[0])
	}
}

func TestParseMatchTokens_multiple(t *testing.T) {
	tokens := parseMatchTokens("!error !warning !note")
	if len(tokens) != 3 {
		t.Fatalf("want 3 tokens, got %d", len(tokens))
	}
	for i, tok := range tokens {
		if !tok.negative {
			t.Errorf("token %d should be negative", i)
		}
	}
}

func TestParseMatchTokens_mixed(t *testing.T) {
	tokens := parseMatchTokens("api !debug re:^\\d{3}")
	if len(tokens) != 3 {
		t.Fatalf("want 3 tokens, got %d", len(tokens))
	}
	if tokens[0].negative || tokens[0].isRegex {
		t.Errorf("token 0 should be plain positive: %+v", tokens[0])
	}
	if !tokens[1].negative || tokens[1].isRegex {
		t.Errorf("token 1 should be plain negative: %+v", tokens[1])
	}
	if tokens[2].negative || !tokens[2].isRegex {
		t.Errorf("token 2 should be regex positive: %+v", tokens[2])
	}
}

func TestParseMatchTokens_skipEmpty(t *testing.T) {
	tokens := parseMatchTokens("!")
	if len(tokens) != 0 {
		t.Errorf("lone '!' should produce no tokens, got %d", len(tokens))
	}
}

func TestParseMatchTokens_invalidRegex(t *testing.T) {
	tokens := parseMatchTokens("re:[invalid")
	if len(tokens) != 1 {
		t.Fatalf("want 1 token, got %d", len(tokens))
	}
	if tokens[0].re != nil {
		t.Error("invalid regex should have nil compiled pattern")
	}
}

func TestLineMatchesTokens_plainPositive(t *testing.T) {
	tokens := parseMatchTokens("error")
	if !lineMatchesTokens("an error occurred", tokens) {
		t.Error("should match line containing 'error'")
	}
	if lineMatchesTokens("all is well", tokens) {
		t.Error("should not match line without 'error'")
	}
}

func TestLineMatchesTokens_plainNegative(t *testing.T) {
	tokens := parseMatchTokens("!debug")
	if !lineMatchesTokens("error: something failed", tokens) {
		t.Error("should match line without 'debug'")
	}
	if lineMatchesTokens("debug: checking cache", tokens) {
		t.Error("should exclude line containing 'debug'")
	}
}

func TestLineMatchesTokens_multipleNegative(t *testing.T) {
	tokens := parseMatchTokens("!error !warning !note")
	if !lineMatchesTokens("info: server started", tokens) {
		t.Error("should match line without any excluded terms")
	}
	if lineMatchesTokens("warning: low memory", tokens) {
		t.Error("should exclude line with 'warning'")
	}
	if lineMatchesTokens("note: config loaded", tokens) {
		t.Error("should exclude line with 'note'")
	}
}

func TestLineMatchesTokens_positiveAndNegative(t *testing.T) {
	tokens := parseMatchTokens("api !debug")
	if !lineMatchesTokens("api: request received", tokens) {
		t.Error("should match: has 'api', no 'debug'")
	}
	if lineMatchesTokens("api debug: verbose output", tokens) {
		t.Error("should exclude: has both 'api' and 'debug'")
	}
	if lineMatchesTokens("worker: task complete", tokens) {
		t.Error("should exclude: missing 'api'")
	}
}

func TestLineMatchesTokens_regex(t *testing.T) {
	tokens := parseMatchTokens("re:^\\d{3}\\s")
	if !lineMatchesTokens("200 OK", tokens) {
		t.Error("should match line starting with 3 digits")
	}
	if lineMatchesTokens("info: status 200", tokens) {
		t.Error("should not match: digits not at start")
	}
}

func TestLineMatchesTokens_negativeRegex(t *testing.T) {
	tokens := parseMatchTokens("!re:^(debug|trace)")
	if !lineMatchesTokens("error: something broke", tokens) {
		t.Error("should match: doesn't start with debug or trace")
	}
	if lineMatchesTokens("debug: checking state", tokens) {
		t.Error("should exclude: starts with debug")
	}
}

func TestLineMatchesTokens_caseInsensitive(t *testing.T) {
	tokens := parseMatchTokens("ERROR")
	if !lineMatchesTokens("Error: something failed", tokens) {
		t.Error("plain matching should be case-insensitive")
	}
}

func TestLineMatchesTokens_regexCaseInsensitive(t *testing.T) {
	tokens := parseMatchTokens("re:error")
	if !lineMatchesTokens("ERROR: something", tokens) {
		t.Error("regex matching should be case-insensitive")
	}
}

func TestLineMatchesTokens_invalidRegexNoMatch(t *testing.T) {
	tokens := parseMatchTokens("re:[bad")
	if lineMatchesTokens("anything", tokens) {
		t.Error("invalid positive regex should not match")
	}
}

func TestLineMatchesTokens_ansiStripped(t *testing.T) {
	tokens := parseMatchTokens("error")
	if !lineMatchesTokens("\x1b[31merror\x1b[0m: red text", tokens) {
		t.Error("should match after stripping ANSI codes")
	}
}

func TestLineMatchesQuery_empty(t *testing.T) {
	if !lineMatchesQuery("anything", "") {
		t.Error("empty query should match everything")
	}
}

func TestLineMatchesQuery_loneExclamation(t *testing.T) {
	if !lineMatchesQuery("anything", "!") {
		t.Error("lone '!' query should match everything (empty token skipped)")
	}
}
