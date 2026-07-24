package tui

import (
	"regexp"
	"strings"

	"github.com/charmbracelet/x/ansi"
)

type matchToken struct {
	pattern  string
	negative bool
	isRegex  bool
	re       *regexp.Regexp // compiled regex; nil if plain or invalid
}

// parseMatchTokens splits a query into space-separated tokens.
// Each token can be:
//
//	"term"       — positive plain substring
//	"!term"      — negative plain substring (exclude matching lines)
//	"re:pattern" — positive regex
//	"!re:pattern"— negative regex
func parseMatchTokens(query string) []matchToken {
	parts := strings.Fields(query)
	tokens := make([]matchToken, 0, len(parts))
	for _, part := range parts {
		var t matchToken
		s := part
		if strings.HasPrefix(s, "!") {
			t.negative = true
			s = s[1:]
		}
		if strings.HasPrefix(s, "re:") {
			t.isRegex = true
			s = s[3:]
			if s != "" {
				if re, err := regexp.Compile("(?i)" + s); err == nil {
					t.re = re
				}
			}
		}
		t.pattern = strings.ToLower(s)
		if t.pattern == "" && !t.isRegex {
			continue // skip empty plain tokens (e.g. lone "!")
		}
		tokens = append(tokens, t)
	}
	return tokens
}

// lineMatchesTokens returns true if the line satisfies all token conditions:
//   - every positive token must match
//   - no negative token may match
//
// Plain tokens match case-insensitively via a lowered copy of the line; regex
// tokens match against the original (ANSI-stripped) line so character classes
// like [A-Z] or Unicode properties like \p{Lu} behave as users expect. Case
// insensitivity for regex is handled by the (?i) flag injected at parse time.
func lineMatchesTokens(line string, tokens []matchToken) bool {
	stripped := ansi.Strip(line)
	strippedLower := strings.ToLower(stripped)
	for _, t := range tokens {
		var matches bool
		if t.isRegex {
			if t.re != nil {
				matches = t.re.MatchString(stripped)
			}
			// invalid regex → no match
		} else {
			matches = strings.Contains(strippedLower, t.pattern)
		}
		if t.negative && matches {
			return false
		}
		if !t.negative && !matches {
			return false
		}
	}
	return true
}

// lineMatchesQuery is a convenience wrapper: parses the query into tokens
// and checks the line against them. For hot paths that call this in a loop,
// prefer parsing once with parseMatchTokens and calling lineMatchesTokens.
func lineMatchesQuery(line, query string) bool {
	if query == "" {
		return true
	}
	tokens := parseMatchTokens(query)
	if len(tokens) == 0 {
		return true
	}
	return lineMatchesTokens(line, tokens)
}
