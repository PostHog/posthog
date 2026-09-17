package completion

import (
	"fmt"
	"strings"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

func cursorBindings(schema *catalog.PreparedCatalog, query string, position int, qualifier string) (*analysis.Document, analysis.Bindings, analysis.Relation, error) {
	document, parseErr := analysis.Analyze(schema, query)
	if parseErr != nil {
		parseErr = fmt.Errorf("parse incomplete SQL: %w", parseErr)
		if recovered := recoverSingleSelect(query); recovered != "" {
			document, _ = analysis.Analyze(schema, recovered)
			position = len("SELECT ")
		}
	}
	if document != nil {
		for statement := range document.Statements() {
			if statement.ContainsPosition(position) {
				bindings := statement.BindingsAt(position, position)
				relation, _ := statement.RelationAt(qualifier, position)
				return document, bindings, relation, parseErr
			}
		}
	}
	return document, analysis.Bindings{}, analysis.Relation{}, parseErr
}

// Incomplete predicates can retain a parsed FROM clause only when no other query scope exists.
func recoverSingleSelect(query string) string {
	tokens, _, incomplete := scanSQLTokens(query)
	if incomplete {
		return ""
	}
	selects := 0
	from := -1
	end := len(tokens)
	for index, token := range tokens {
		if token.text == ";" || token.text == "WITH" {
			return ""
		}
		if token.kind != sqlTokenWord {
			continue
		}
		if token.text == "SELECT" {
			selects++
			if token.depth != 0 || selects > 1 {
				return ""
			}
		}
		if token.depth == 0 {
			if token.text == "FROM" && from == -1 {
				from = index
			}
			switch token.text {
			case "WHERE", "PREWHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "SETTINGS":
				if from >= 0 && end == len(tokens) {
					end = index
				}
			}
		}
	}
	if selects != 1 || from < 0 {
		return ""
	}
	var recovered strings.Builder
	recovered.WriteString("SELECT * ")
	for _, token := range tokens[from:end] {
		recovered.WriteString(token.text)
		recovered.WriteByte(' ')
	}
	return recovered.String()
}
