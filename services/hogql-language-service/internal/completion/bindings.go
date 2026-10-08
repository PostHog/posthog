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
		if recovered, recoveredPosition, ok := recoverCTEOuterSelect(query, position); ok {
			document, _ = analysis.Analyze(schema, recovered)
			position = recoveredPosition
		} else if recovered := recoverSingleSelect(query); recovered != "" {
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

func recoverCTEOuterSelect(query string, position int) (string, int, bool) {
	tokens, _, incomplete := scanSQLTokens(query)
	if incomplete || len(tokens) == 0 || tokens[0].text != "WITH" || tokens[0].depth != 0 {
		return "", 0, false
	}
	outerSelect := -1
	from := -1
	boundary := -1
	for index, token := range tokens {
		if token.depth == 0 && (token.text == ";" || token.text == "UNION" || token.text == "EXCEPT" || token.text == "INTERSECT") {
			return "", 0, false
		}
		if token.kind != sqlTokenWord {
			continue
		}
		if token.text == "SELECT" {
			if token.depth == 0 {
				if outerSelect >= 0 {
					return "", 0, false
				}
				outerSelect = index
			} else if outerSelect >= 0 {
				return "", 0, false
			}
		}
		if outerSelect < 0 || token.depth != 0 {
			continue
		}
		if token.text == "FROM" && from < 0 {
			from = index
			continue
		}
		if from >= 0 && boundary < 0 {
			switch token.text {
			case "WHERE", "PREWHERE", "GROUP", "HAVING", "ORDER", "LIMIT":
				boundary = index
			}
		}
	}
	if outerSelect < 0 || from < 0 || boundary < 0 || position < tokens[outerSelect].start {
		return "", 0, false
	}
	if !hasCompleteTableCTEs(tokens[:outerSelect]) {
		return "", 0, false
	}

	retainedEnd := tokens[boundary].start
	if position >= tokens[from].start && position < retainedEnd {
		return "", 0, false
	}
	if position < retainedEnd {
		return query[:retainedEnd], position, true
	}
	recovered := query[:retainedEnd]
	if retainedEnd == 0 || !isSQLSpace(query[retainedEnd-1]) {
		recovered += " "
	}
	// Map discarded expressions into the outer predicate so SELECT aliases keep their normal visibility.
	recovered += "WHERE 0"
	return recovered, len(recovered) - 1, true
}

func isSQLSpace(value byte) bool {
	switch value {
	case ' ', '\t', '\r', '\n':
		return true
	}
	return false
}

func hasCompleteTableCTEs(tokens []sqlToken) bool {
	for index := 1; index < len(tokens); {
		if tokens[index].kind != sqlTokenWord || tokens[index].depth != 0 {
			return false
		}
		index++
		if index >= len(tokens) || tokens[index].text != "AS" || tokens[index].depth != 0 {
			return false
		}
		index++
		if index >= len(tokens) || tokens[index].kind != sqlTokenLeftParen || tokens[index].depth != 0 {
			return false
		}
		index++
		for index < len(tokens) && !(tokens[index].kind == sqlTokenRightParen && tokens[index].depth == 0) {
			index++
		}
		if index >= len(tokens) {
			return false
		}
		index++
		if index == len(tokens) {
			return true
		}
		if tokens[index].kind != sqlTokenComma || tokens[index].depth != 0 {
			return false
		}
		index++
	}
	return false
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
		recovered.WriteString(token.raw)
		recovered.WriteByte(' ')
	}
	return recovered.String()
}
