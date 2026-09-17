package completion

import (
	"strings"
	"unicode"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
)

func fieldSuggestions(bindings analysis.Bindings, prefix string) []Suggestion {
	var suggestions []Suggestion
	// HogQL alias precedence is case-sensitive (resolver_utils.lookup_field_by_name).
	aliases := map[string]bool{}
	for alias := range bindings.SelectAliases(prefix) {
		aliases[alias.Name] = true
		if supportedHogQLIdentifier(alias.Name) {
			suggestions = append(suggestions, Suggestion{Label: alias.Name, Kind: "field", Detail: alias.Type, InsertText: suggestionInsertText("field", alias.Name)})
		}
	}
	type candidate struct {
		field     Suggestion
		qualifier string
		key       string
	}
	var candidates []candidate
	counts := map[string]int{}
	qualifiers := map[analysis.Source]string{}
	for source, field := range bindings.Fields(prefix) {
		if aliases[field.Name] || !supportedHogQLIdentifier(field.Name) {
			continue
		}
		qualifier, ok := qualifiers[source]
		if !ok {
			qualifier = quoteHogQLFieldIdentifier(source.Qualifier())
			qualifiers[source] = qualifier
		}
		key := strings.Map(func(r rune) rune {
			first := r
			for next := unicode.SimpleFold(r); next != r; next = unicode.SimpleFold(next) {
				first = min(first, next)
			}
			return first
		}, field.Name)
		counts[key]++
		candidates = append(candidates, candidate{
			field:     Suggestion{Label: field.Name, Kind: "field", Detail: field.Type, InsertText: suggestionInsertText("field", field.Name)},
			qualifier: qualifier, key: key,
		})
	}
	for _, candidate := range candidates {
		field := candidate.field
		if counts[candidate.key] > 1 {
			if !supportedHogQLIdentifier(candidate.qualifier) {
				continue
			}
			field.InsertText = candidate.qualifier + "." + quoteHogQLFieldIdentifier(field.Label)
			field.Detail = strings.TrimSpace(field.Detail + " from " + candidate.qualifier)
		}
		suggestions = append(suggestions, field)
	}
	return suggestions
}
