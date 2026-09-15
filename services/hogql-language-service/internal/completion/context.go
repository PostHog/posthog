package completion

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

type completionMode uint8

const (
	completionModeGeneral completionMode = iota
	completionModeNone
	completionModeTable
	completionModeExpression
	completionModeComparison
	completionModePredicateContinuation
	completionModePostExpression
)

type sqlTokenKind uint8

const (
	sqlTokenWord sqlTokenKind = iota
	sqlTokenValue
	sqlTokenOperator
	sqlTokenLeftParen
	sqlTokenRightParen
	sqlTokenComma
)

type sqlToken struct {
	text  string
	kind  sqlTokenKind
	depth int
}

func analyzeCursorContext(input string) completionMode {
	tokens, depth, incomplete := scanSQLTokens(input)
	if incomplete {
		return completionModeNone
	}
	clauseIndex, clause := activeClause(tokens, depth)
	switch clause {
	case "FROM", "JOIN":
		if clauseIndex == len(tokens)-1 || lastTokenAtDepth(tokens[clauseIndex+1:], depth).kind == sqlTokenComma {
			return completionModeTable
		}
	case "SELECT", "GROUP BY", "ORDER BY":
		return completionModeExpression
	case "WHERE", "PREWHERE", "HAVING", "ON":
		return predicateMode(tokens[clauseIndex+1:], depth)
	}
	return completionModeGeneral
}

func activeClause(tokens []sqlToken, depth int) (int, string) {
	for index := len(tokens) - 1; index >= 0; index-- {
		token := tokens[index]
		if token.depth > depth || token.kind != sqlTokenWord {
			continue
		}
		switch token.text {
		case "WHERE", "PREWHERE", "HAVING", "ON", "FROM", "JOIN", "SELECT", "LIMIT":
			return index, token.text
		case "BY":
			if index > 0 && tokens[index-1].depth == token.depth && (tokens[index-1].text == "GROUP" || tokens[index-1].text == "ORDER") {
				return index, tokens[index-1].text + " BY"
			}
		}
	}
	return -1, ""
}

func predicateMode(tokens []sqlToken, depth int) completionMode {
	start := 0
	betweenPending := false
	for index, token := range tokens {
		if token.kind == sqlTokenLeftParen && token.depth == depth-1 {
			start = index + 1
			betweenPending = false
			continue
		}
		if token.depth != depth || token.kind != sqlTokenWord {
			continue
		}
		if token.text == "BETWEEN" {
			betweenPending = true
			continue
		}
		if token.text == "AND" && betweenPending {
			betweenPending = false
			continue
		}
		if token.text == "AND" || token.text == "OR" {
			start = index + 1
			betweenPending = false
		}
	}
	segment := tokens[start:]
	last := lastTokenAtDepth(segment, depth)
	if last.text == "" || last.text == "AND" || last.text == "OR" || last.kind == sqlTokenComma || last.kind == sqlTokenLeftParen {
		return completionModeExpression
	}
	if last.kind == sqlTokenOperator {
		return completionModeExpression
	}
	comparisonIndex := -1
	for index, token := range segment {
		if token.depth == depth && isComparisonToken(token) {
			comparisonIndex = index
			break
		}
	}
	if comparisonIndex >= 0 {
		for _, token := range segment[comparisonIndex+1:] {
			if token.depth <= depth && token.text != "NOT" {
				return completionModePredicateContinuation
			}
		}
		return completionModeExpression
	}
	if last.kind == sqlTokenRightParen || last.kind == sqlTokenValue {
		return completionModePostExpression
	}
	return completionModeComparison
}

func lastTokenAtDepth(tokens []sqlToken, depth int) sqlToken {
	for index := len(tokens) - 1; index >= 0; index-- {
		if tokens[index].depth <= depth {
			return tokens[index]
		}
	}
	return sqlToken{}
}

func isComparisonToken(token sqlToken) bool {
	if token.kind == sqlTokenOperator {
		switch token.text {
		case "=", "==", "!=", "<>", "<", "<=", ">", ">=", "<=>":
			return true
		}
	}
	if token.kind != sqlTokenWord {
		return false
	}
	switch token.text {
	case "LIKE", "ILIKE", "IN", "IS", "BETWEEN", "REGEXP":
		return true
	}
	return false
}

func scanSQLTokens(input string) ([]sqlToken, int, bool) {
	var tokens []sqlToken
	depth := 0
	for index := 0; index < len(input); {
		character := input[index]
		if unicode.IsSpace(rune(character)) {
			index++
			continue
		}
		if character == '-' && index+1 < len(input) && input[index+1] == '-' {
			end := strings.IndexByte(input[index+2:], '\n')
			if end < 0 {
				return tokens, depth, true
			}
			index += end + 3
			continue
		}
		if character == '/' && index+1 < len(input) && input[index+1] == '*' {
			end := strings.Index(input[index+2:], "*/")
			if end < 0 {
				return tokens, depth, true
			}
			index += end + 4
			continue
		}
		if character == '\'' || character == '"' || character == '`' {
			end := quotedTokenEnd(input, index, character)
			if end < 0 {
				return tokens, depth, true
			}
			kind := sqlTokenValue
			if character != '\'' {
				kind = sqlTokenWord
			}
			tokens = append(tokens, sqlToken{text: strings.ToUpper(input[index:end]), kind: kind, depth: depth})
			index = end
			continue
		}
		if isSQLIdentifierStart(input[index:]) {
			end := index
			for end < len(input) {
				r, size := utf8.DecodeRuneInString(input[end:])
				if !unicode.IsLetter(r) && !unicode.IsDigit(r) && r != '_' && r != '$' {
					break
				}
				end += size
			}
			tokens = append(tokens, sqlToken{text: strings.ToUpper(input[index:end]), kind: sqlTokenWord, depth: depth})
			index = end
			continue
		}
		if character >= '0' && character <= '9' {
			end := index + 1
			for end < len(input) && ((input[end] >= '0' && input[end] <= '9') || input[end] == '.') {
				end++
			}
			tokens = append(tokens, sqlToken{text: input[index:end], kind: sqlTokenValue, depth: depth})
			index = end
			continue
		}
		switch character {
		case '(':
			tokens = append(tokens, sqlToken{text: "(", kind: sqlTokenLeftParen, depth: depth})
			depth++
			index++
		case ')':
			if depth > 0 {
				depth--
			}
			tokens = append(tokens, sqlToken{text: ")", kind: sqlTokenRightParen, depth: depth})
			index++
		case ',':
			tokens = append(tokens, sqlToken{text: ",", kind: sqlTokenComma, depth: depth})
			index++
		default:
			end := operatorEnd(input, index)
			tokens = append(tokens, sqlToken{text: strings.ToUpper(input[index:end]), kind: sqlTokenOperator, depth: depth})
			index = end
		}
	}
	return tokens, depth, false
}

func quotedTokenEnd(input string, start int, quote byte) int {
	for index := start + 1; index < len(input); index++ {
		if input[index] == '\\' {
			index++
			continue
		}
		if input[index] != quote {
			continue
		}
		if index+1 < len(input) && input[index+1] == quote {
			index++
			continue
		}
		return index + 1
	}
	return -1
}

func isSQLIdentifierStart(input string) bool {
	r, _ := utf8.DecodeRuneInString(input)
	return unicode.IsLetter(r) || r == '_' || r == '$'
}

func operatorEnd(input string, start int) int {
	for _, width := range []int{3, 2} {
		if start+width > len(input) {
			continue
		}
		switch input[start : start+width] {
		case "<=>", "!=", "<=", ">=", "==", "<>", "||", "->", "::":
			return start + width
		}
	}
	return start + 1
}
