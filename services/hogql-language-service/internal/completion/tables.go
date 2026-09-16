package completion

import (
	"slices"
	"strings"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

func tableResult(schema *catalog.PreparedCatalog, bindings analysis.Bindings, prefix string, offset int, parseErr error) Result {
	ctes := slices.Collect(bindings.CTENames(prefix))
	if len(ctes) == 0 {
		return indexedResult(slices.Values(schema.Tables().Prefix(prefix)), "table", offset, parseErr)
	}
	slices.SortFunc(ctes, func(left, right catalog.Entry) int {
		return strings.Compare(strings.ToLower(left.Name), strings.ToLower(right.Name))
	})
	cteNames := map[string]bool{}
	shadowed := map[string]bool{}
	for _, cte := range ctes {
		cteNames[cte.Name] = true
		if table, ok := schema.Table(cte.Name); ok {
			shadowed[table.Name] = true
		}
	}
	entries := func(yield func(catalog.Entry) bool) {
		for _, cte := range ctes {
			if !yield(cte) {
				return
			}
		}
		for _, table := range schema.Tables().Prefix(prefix) {
			if !shadowed[table.Name] && !yield(table) {
				return
			}
		}
	}
	result := indexedResult(entries, "table", offset, parseErr)
	for index := range result.Suggestions {
		suggestion := &result.Suggestions[index]
		if cteNames[suggestion.Label] {
			// A dotted CTE name is one identifier, unlike a qualified catalog table name.
			suggestion.InsertText = suggestionInsertText("field", suggestion.Label)
			suggestion.SortText = "0-" + strings.ToLower(suggestion.Label)
		}
	}
	return result
}
