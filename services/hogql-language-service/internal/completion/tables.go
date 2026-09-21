package completion

import (
	"iter"
	"slices"
	"strings"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

func tableResult(schema *catalog.PreparedCatalog, bindings analysis.Bindings, prefix, namespace string, offset int, parseErr error) Result {
	ctes := slices.Collect(bindings.CTENames(prefix))
	if len(ctes) == 0 {
		result := indexedResult(tableEntries(schema, prefix, namespace, nil), "table", offset, parseErr)
		setTablePathInsertText(&result, namespace)
		return result
	}
	slices.SortFunc(ctes, func(left, right catalog.Entry) int {
		if comparison := strings.Compare(strings.ToLower(left.Name), strings.ToLower(right.Name)); comparison != 0 {
			return comparison
		}
		return strings.Compare(left.Name, right.Name)
	})
	cteNames := map[string]bool{}
	shadowed := map[string]bool{}
	for _, cte := range ctes {
		cteNames[cte.Name] = true
		shadowed[cte.Name] = true
	}
	entries := func(yield func(catalog.Entry) bool) {
		if namespace == "" {
			for _, cte := range ctes {
				if !yield(cte) {
					return
				}
			}
		}
		for table := range tableEntries(schema, prefix, namespace, shadowed) {
			if !yield(table) {
				return
			}
		}
	}
	result := indexedResult(entries, "table", offset, parseErr)
	setTablePathInsertText(&result, namespace)
	if namespace != "" {
		return result
	}
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

func tableEntries(schema *catalog.PreparedCatalog, prefix, namespace string, excluded map[string]bool) iter.Seq[catalog.Entry] {
	var entries []catalog.Entry
	if namespace != "" {
		entries = schema.TableSuggestionsMatching(prefix, excluded, func(entry catalog.Entry) bool {
			return strings.HasPrefix(entry.Name, namespace) && supportedUnquotedTablePath(strings.TrimPrefix(entry.Name, namespace))
		})
	} else {
		entries = schema.TableSuggestions(prefix, excluded)
	}
	return func(yield func(catalog.Entry) bool) {
		for _, entry := range entries {
			if !yield(entry) {
				return
			}
		}
	}
}

func supportedUnquotedTablePath(path string) bool {
	for component := range strings.SplitSeq(path, ".") {
		if !simpleHogQLIdentifier.MatchString(component) || isQuotedHogQLKeyword(component) {
			return false
		}
	}
	return true
}

func isQuotedHogQLKeyword(name string) bool {
	folded := name
	for index := 0; index < len(name); index++ {
		if name[index] >= 'A' && name[index] <= 'Z' {
			folded = strings.ToLower(name)
			break
		}
	}
	_, exists := quotedHogQLKeywordsFolded[folded]
	return exists
}

func setTablePathInsertText(result *Result, namespace string) {
	if namespace == "" {
		return
	}
	for index := range result.Suggestions {
		result.Suggestions[index].InsertText = quoteHogQLTablePath(strings.TrimPrefix(result.Suggestions[index].Label, namespace))
	}
}
