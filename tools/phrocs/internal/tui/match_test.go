package tui

import "testing"

func TestParseMatchTokens(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		wantLen int
		check   func(t *testing.T, tokens []matchToken)
	}{
		{
			name:    "plain",
			query:   "error",
			wantLen: 1,
			check: func(t *testing.T, toks []matchToken) {
				if toks[0].pattern != "error" || toks[0].negative || toks[0].isRegex {
					t.Errorf("unexpected token: %+v", toks[0])
				}
			},
		},
		{
			name:    "negative",
			query:   "!warning",
			wantLen: 1,
			check: func(t *testing.T, toks []matchToken) {
				if toks[0].pattern != "warning" || !toks[0].negative {
					t.Errorf("unexpected token: %+v", toks[0])
				}
			},
		},
		{
			name:    "regex",
			query:   "re:\\d+",
			wantLen: 1,
			check: func(t *testing.T, toks []matchToken) {
				if !toks[0].isRegex || toks[0].re == nil {
					t.Errorf("expected compiled regex: %+v", toks[0])
				}
			},
		},
		{
			name:    "negative regex",
			query:   "!re:debug",
			wantLen: 1,
			check: func(t *testing.T, toks []matchToken) {
				if !toks[0].negative || !toks[0].isRegex || toks[0].re == nil {
					t.Errorf("unexpected token: %+v", toks[0])
				}
			},
		},
		{
			name:    "multiple negatives",
			query:   "!error !warning !note",
			wantLen: 3,
			check: func(t *testing.T, toks []matchToken) {
				for i, tok := range toks {
					if !tok.negative {
						t.Errorf("token %d should be negative", i)
					}
				}
			},
		},
		{
			name:    "mixed",
			query:   "api !debug re:^\\d{3}",
			wantLen: 3,
			check: func(t *testing.T, toks []matchToken) {
				if toks[0].negative || toks[0].isRegex {
					t.Errorf("token 0 should be plain positive: %+v", toks[0])
				}
				if !toks[1].negative || toks[1].isRegex {
					t.Errorf("token 1 should be plain negative: %+v", toks[1])
				}
				if toks[2].negative || !toks[2].isRegex {
					t.Errorf("token 2 should be regex positive: %+v", toks[2])
				}
			},
		},
		{
			name:    "lone exclamation is skipped",
			query:   "!",
			wantLen: 0,
		},
		{
			name:    "invalid regex leaves nil compiled pattern",
			query:   "re:[invalid",
			wantLen: 1,
			check: func(t *testing.T, toks []matchToken) {
				if toks[0].re != nil {
					t.Error("invalid regex should have nil compiled pattern")
				}
			},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			toks := parseMatchTokens(tc.query)
			if len(toks) != tc.wantLen {
				t.Fatalf("want %d token(s), got %d", tc.wantLen, len(toks))
			}
			if tc.check != nil {
				tc.check(t, toks)
			}
		})
	}
}

func TestLineMatchesTokens(t *testing.T) {
	tests := []struct {
		name  string
		query string
		line  string
		want  bool
	}{
		{"plain positive match", "error", "an error occurred", true},
		{"plain positive miss", "error", "all is well", false},

		{"plain negative match", "!debug", "error: something failed", true},
		{"plain negative exclude", "!debug", "debug: checking cache", false},

		{"multiple negatives match", "!error !warning !note", "info: server started", true},
		{"multiple negatives exclude on warning", "!error !warning !note", "warning: low memory", false},
		{"multiple negatives exclude on note", "!error !warning !note", "note: config loaded", false},

		{"positive and negative match", "api !debug", "api: request received", true},
		{"positive and negative exclude on negative", "api !debug", "api debug: verbose output", false},
		{"positive and negative exclude missing positive", "api !debug", "worker: task complete", false},

		{"regex match", "re:^\\d{3}\\s", "200 OK", true},
		{"regex miss", "re:^\\d{3}\\s", "info: status 200", false},

		{"negative regex match", "!re:^(debug|trace)", "error: something broke", true},
		{"negative regex exclude", "!re:^(debug|trace)", "debug: checking state", false},

		{"plain match is case-insensitive", "ERROR", "Error: something failed", true},
		{"regex match is case-insensitive", "re:error", "ERROR: something", true},

		{"invalid positive regex never matches", "re:[bad", "anything", false},
		{"ansi codes are stripped before matching", "error", "\x1b[31merror\x1b[0m: red text", true},

		// Regex matches on the case-preserved line so users can opt out of
		// case-insensitivity via (?-i) and use Unicode classes meaningfully.
		{"regex with (?-i) override matches only uppercase", "re:(?-i)[A-Z]+", "HELLO world", true},
		{"regex with (?-i) override rejects lowercase", "re:(?-i)[A-Z]+", "hello world", false},
		{"regex on Unicode uppercase class", "re:(?-i)\\p{Lu}", "Hello", true},
		{"regex on Unicode uppercase class rejects all-lowercase", "re:(?-i)\\p{Lu}", "hello", false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			toks := parseMatchTokens(tc.query)
			if got := lineMatchesTokens(tc.line, toks); got != tc.want {
				t.Errorf("lineMatchesTokens(%q, %q) = %v, want %v", tc.line, tc.query, got, tc.want)
			}
		})
	}
}

func TestLineMatchesQuery(t *testing.T) {
	tests := []struct {
		name  string
		query string
		line  string
		want  bool
	}{
		{"empty query matches everything", "", "anything", true},
		{"lone exclamation matches everything (empty token skipped)", "!", "anything", true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := lineMatchesQuery(tc.line, tc.query); got != tc.want {
				t.Errorf("lineMatchesQuery(%q, %q) = %v, want %v", tc.line, tc.query, got, tc.want)
			}
		})
	}
}
