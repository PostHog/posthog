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
	completionModeBetweenSeparator
	completionModePredicateContinuation
	completionModePostExpression
	completionModeStatementStart
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
	if len(tokens) == 0 || tokens[len(tokens)-1].text == ";" && depth == 0 {
		return completionModeStatementStart
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
	caseDepth := 0
	for index, token := range tokens {
		if token.kind == sqlTokenLeftParen && token.depth == depth-1 {
			start = index + 1
			betweenPending = false
			caseDepth = 0
			continue
		}
		if token.depth != depth || token.kind != sqlTokenWord {
			continue
		}
		switch token.text {
		case "CASE":
			caseDepth++
		case "END":
			if caseDepth > 0 {
				caseDepth--
			}
		case "BETWEEN":
			if caseDepth == 0 {
				betweenPending = true
			}
		case "AND":
			if caseDepth > 0 {
				continue
			}
			if betweenPending {
				betweenPending = false
				continue
			}
			start = index + 1
		case "OR":
			if caseDepth == 0 {
				start = index + 1
				betweenPending = false
			}
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
		if betweenPending && segment[comparisonIndex].text == "BETWEEN" {
			if betweenLowerBoundComplete(segment[comparisonIndex+1:], depth) {
				return completionModeBetweenSeparator
			}
			return completionModeExpression
		}
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

func betweenLowerBoundComplete(tokens []sqlToken, depth int) bool {
	hasExpressionToken := false
	openCases := 0
	lastExpressionIndex := -1
	pendingIntervals := make([]int, depth+1)
	for index := range pendingIntervals {
		pendingIntervals[index] = -1
	}
	for index, token := range tokens {
		if token.depth < depth {
			break
		}
		for len(pendingIntervals) > token.depth+1 {
			if pendingIntervals[len(pendingIntervals)-1] >= 0 {
				return false
			}
			pendingIntervals = pendingIntervals[:len(pendingIntervals)-1]
		}
		for len(pendingIntervals) <= token.depth {
			pendingIntervals = append(pendingIntervals, -1)
		}
		if token.kind == sqlTokenWord {
			switch token.text {
			case "CASE":
				openCases++
			case "END":
				if openCases > 0 {
					openCases--
				}
			case "INTERVAL":
				pendingIntervals[token.depth] = index
			default:
				if isIntervalUnit(token.text) && lastExpressionIndex > pendingIntervals[token.depth] {
					pendingIntervals[token.depth] = -1
				}
			}
		}
		if token.text != "NOT" {
			hasExpressionToken = true
		}
		if token.kind == sqlTokenWord || token.kind == sqlTokenValue {
			lastExpressionIndex = index
		}
	}
	for _, intervalIndex := range pendingIntervals {
		if intervalIndex >= 0 {
			return false
		}
	}
	return hasExpressionToken && openCases == 0
}

func isIntervalUnit(value string) bool {
	switch value {
	case "MILLISECOND", "SECOND", "MINUTE", "HOUR", "DAY", "WEEK", "MONTH", "QUARTER", "YEAR":
		return true
	}
	return false
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
		r, size := utf8.DecodeRuneInString(input[index:])
		if unicode.IsSpace(r) {
			index += size
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
