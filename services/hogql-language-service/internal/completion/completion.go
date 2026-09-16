package completion

import (
	"encoding/base64"
	"fmt"
	"iter"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/textposition"
)

type Suggestion struct {
	Label      string `json:"label"`
	Kind       string `json:"kind"`
	Detail     string `json:"detail,omitempty"`
	InsertText string `json:"insertText,omitempty"`
	SortText   string `json:"sortText,omitempty"`
}

type Result struct {
	Suggestions []Suggestion `json:"suggestions"`
	Total       int          `json:"total"`
	NextCursor  string       `json:"nextCursor,omitempty"`
	ParseError  string       `json:"parseError,omitempty"`
}

const PageSize = 25

type PositionEncoding = textposition.Encoding

const (
	PositionEncodingUTF8  = textposition.UTF8
	PositionEncodingUTF16 = textposition.UTF16
)

var keywords = []string{"SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "JOIN", "AS", "CASE", "NULL", "TRUE", "FALSE", "NOT"}
var betweenSeparator = []string{"AND"}
var predicateContinuations = []string{"AND", "OR", "GROUP BY", "ORDER BY", "LIMIT"}
var comparisonOperators = []string{"=", "!=", "<", "<=", ">", ">=", "LIKE", "ILIKE", "IN", "NOT IN", "IS NULL", "IS NOT NULL", "BETWEEN", "NOT BETWEEN"}
var commonFunctions = []string{"avg", "coalesce", "count", "countDistinct", "countIf", "if", "max", "min", "now", "sum", "sumIf", "toDate", "toDateTime", "uniq", "uniqExact"}
var simpleHogQLIdentifier = regexp.MustCompile(`^[A-Za-z_$][A-Za-z0-9_$]*$`)
var hogQLKeywords = map[string]struct{}{
	"ALL": {}, "AND": {}, "ANTI": {}, "ANY": {}, "ARRAY": {}, "AS": {}, "ASC": {}, "ASCENDING": {}, "ASOF": {},
	"BETWEEN": {}, "BOTH": {}, "BY": {}, "CASE": {}, "CAST": {}, "CATCH": {}, "COHORT": {}, "COLLATE": {}, "COLUMNS": {},
	"CROSS": {}, "CUBE": {}, "CURRENT": {}, "DATE": {}, "DAY": {}, "DESC": {}, "DESCENDING": {}, "DISTINCT": {},
	"ELSE": {}, "END": {}, "EXCEPT": {}, "EXCLUDE": {}, "EXTRACT": {}, "FILL": {}, "FILTER": {}, "FINAL": {},
	"FINALLY": {}, "FIRST": {}, "FN": {}, "FOLLOWING": {}, "FOR": {}, "FROM": {}, "FULL": {}, "FUN": {},
	"GROUP": {}, "GROUPING": {}, "HAVING": {}, "HOUR": {}, "ID": {}, "IF": {}, "INF": {}, "INFINITY": {},
	"IGNORE": {}, "ILIKE": {}, "IN": {}, "INCLUDE": {}, "INNER": {}, "INTERPOLATE": {}, "INTERVAL": {}, "IS": {},
	"INTERSECT": {}, "JOIN": {}, "KEY": {}, "LAMBDA": {}, "LAST": {}, "LEADING": {}, "LEFT": {}, "LET": {},
	"LIKE": {}, "LIMIT": {}, "LOCAL": {}, "MATERIALIZED": {}, "MINUTE": {}, "MONTH": {}, "NAME": {}, "NAN": {},
	"NATURAL": {}, "NOT": {}, "NULL": {}, "NULLS": {}, "OFFSET": {}, "ON": {}, "OR": {},
	"ORDER": {}, "OUTER": {}, "OVER": {}, "PARTITION": {}, "PIVOT": {}, "POSITIONAL": {}, "PRECEDING": {},
	"PREWHERE": {}, "QUALIFY": {}, "QUARTER": {}, "RANGE": {}, "RECURSIVE": {}, "REPLACE": {}, "RETURN": {}, "RIGHT": {},
	"ROLLUP": {}, "ROW": {}, "ROWS": {}, "SAMPLE": {}, "SELECT": {}, "SEMI": {}, "SETS": {}, "SETTINGS": {},
	"SECOND": {}, "STEP": {}, "SUBSTRING": {}, "THEN": {}, "THROW": {}, "TIES": {}, "TIME": {}, "TIMESTAMP": {},
	"TO": {}, "TOP": {}, "TOTALS": {}, "TRAILING": {}, "TRIM": {}, "TRUNCATE": {}, "TRY": {}, "TRY_CAST": {},
	"UNBOUNDED": {}, "UNION": {}, "UNPIVOT": {}, "USING": {}, "VALUES": {}, "WEEK": {}, "WHEN": {},
	"WHERE": {}, "WHILE": {}, "WINDOW": {}, "WITH": {}, "WITHIN": {}, "YEAR": {}, "YYYY": {}, "ZONE": {},
}
var hogQLIdentifierEscaper = strings.NewReplacer(
	"\\", "\\\\",
	"`", "``",
	"\b", "\\b",
	"\f", "\\f",
	"\r", "\\r",
	"\n", "\\n",
	"\t", "\\t",
	"\x00", "\\0",
	"\a", "\\a",
	"\v", "\\v",
)

func Complete(schema *catalog.PreparedCatalog, query string, position int, positionEncoding PositionEncoding, cursor string) (Result, error) {
	if err := querylimits.Validate(query); err != nil {
		return Result{}, err
	}
	offset, err := decodeCursor(cursor)
	if err != nil {
		return Result{}, err
	}
	position, err = textposition.ToByteOffset(query, position, positionEncoding)
	if err != nil {
		return Result{}, err
	}
	prefix, qualifier, start := cursorWord(query[:position])
	if len(prefix) > querylimits.MaxSuggestionInputBytes {
		return Result{Suggestions: []Suggestion{}}, nil
	}
	lowerPrefix := strings.ToLower(prefix)
	mode := analyzeCursorContext(query[:start])
	if mode == completionModeNone {
		return Result{Suggestions: []Suggestion{}}, nil
	}
	repaired := query[:start] + "__posthog_cursor__" + query[position:]
	document, bindings, qualified, parseErr := cursorBindings(schema, repaired, start, qualifier)

	var suggestions []Suggestion
	namespace, propertyPrefix, propertyOK := propertyContext(query[:position], bindings)
	if document != nil && document.LimitError() != nil {
		return Result{}, document.LimitError()
	}
	if propertyOK {
		return indexedResult(slices.Values(schema.Properties(namespace).Prefix(propertyPrefix)), "property", offset, parseErr), nil
	} else if qualifier != "" {
		entries := qualified.Prefix(lowerPrefix)
		if document != nil && document.LimitError() != nil {
			return Result{}, document.LimitError()
		}
		return indexedResult(entries, "field", offset, parseErr), nil
	} else if mode == completionModeTable {
		return indexedResult(slices.Values(schema.Tables().Prefix(lowerPrefix)), "table", offset, parseErr), nil
	} else if mode == completionModeComparison {
		suggestions = appendNamed(suggestions, comparisonOperators, lowerPrefix, "operator", "")
	} else if mode == completionModeBetweenSeparator {
		suggestions = appendNamed(suggestions, betweenSeparator, lowerPrefix, "keyword", "")
	} else if mode == completionModePredicateContinuation {
		suggestions = appendNamed(suggestions, predicateContinuations, lowerPrefix, "keyword", "")
	} else if mode == completionModePostExpression {
		suggestions = appendNamed(suggestions, comparisonOperators, lowerPrefix, "operator", "")
		suggestions = appendNamed(suggestions, predicateContinuations, lowerPrefix, "keyword", "")
	} else {
		seen := map[analysis.Relation]bool{}
		for _, relation := range bindings.All() {
			if seen[relation] {
				continue
			}
			seen[relation] = true
			suggestions = appendFields(suggestions, relation.Prefix(lowerPrefix))
		}
		if document != nil && document.LimitError() != nil {
			return Result{}, document.LimitError()
		}
		if mode == completionModeExpression {
			suggestions = appendFunctions(suggestions, lowerPrefix)
		}
		for _, keyword := range keywords {
			if hasLowerPrefix(keyword, lowerPrefix) {
				suggestions = append(suggestions, Suggestion{Label: keyword, Kind: "keyword"})
			}
		}
	}
	sort.Slice(suggestions, func(i, j int) bool {
		leftRank := suggestionRank(suggestions[i].Kind)
		rightRank := suggestionRank(suggestions[j].Kind)
		if leftRank != rightRank {
			return leftRank < rightRank
		}
		return strings.ToLower(suggestions[i].Label) < strings.ToLower(suggestions[j].Label)
	})
	for index := range suggestions {
		suggestions[index].SortText = strconv.Itoa(suggestionRank(suggestions[index].Kind)) + "-" + strings.ToLower(suggestions[index].Label)
	}
	result := Result{Suggestions: suggestions, Total: len(suggestions)}
	if offset > len(suggestions) {
		offset = len(suggestions)
	}
	end := min(offset+PageSize, len(suggestions))
	result.Suggestions = suggestions[offset:end]
	if end < len(suggestions) {
		result.NextCursor = encodeCursor(end)
	}
	if parseErr != nil {
		result.ParseError = parseErr.Error()
	}
	return result, nil
}

func indexedResult(entries iter.Seq[catalog.Entry], kind string, offset int, parseErr error) Result {
	result := Result{Suggestions: make([]Suggestion, 0, PageSize)}
	rank := strconv.Itoa(suggestionRank(kind)) + "-"
	for entry := range entries {
		if !supportedHogQLIdentifier(entry.Name) {
			continue
		}
		if result.Total >= offset && len(result.Suggestions) < PageSize {
			result.Suggestions = append(result.Suggestions, Suggestion{
				Label: entry.Name, Kind: kind, Detail: entry.Type, InsertText: suggestionInsertText(kind, entry.Name), SortText: rank + strings.ToLower(entry.Name),
			})
		}
		result.Total++
	}
	nextOffset := offset + len(result.Suggestions)
	if nextOffset < result.Total {
		result.NextCursor = encodeCursor(nextOffset)
	}
	if parseErr != nil {
		result.ParseError = parseErr.Error()
	}
	return result
}

func utf16OffsetToByteOffset(value string, offset int) int {
	byteOffset, _ := textposition.ToByteOffset(value, offset, PositionEncodingUTF16)
	return byteOffset
}

func propertyContext(input string, bindings analysis.Bindings) (string, string, bool) {
	start := len(input)
	for start > 0 {
		character, size := utf8.DecodeLastRuneInString(input[:start])
		if character != '.' && !isIdentifier(character) {
			break
		}
		start -= size
	}
	parts := strings.Split(input[start:], ".")
	if len(parts) < 2 {
		return "", "", false
	}
	namespace, ok := bindings.PropertyNamespace(parts)
	return namespace, parts[len(parts)-1], ok
}

func decodeCursor(cursor string) (int, error) {
	if cursor == "" {
		return 0, nil
	}
	decoded, err := base64.RawURLEncoding.DecodeString(cursor)
	if err != nil {
		return 0, fmt.Errorf("invalid cursor")
	}
	offset, err := strconv.Atoi(string(decoded))
	if err != nil || offset < 0 {
		return 0, fmt.Errorf("invalid cursor")
	}
	return offset, nil
}

func encodeCursor(offset int) string {
	return base64.RawURLEncoding.EncodeToString([]byte(strconv.Itoa(offset)))
}

func appendFields(out []Suggestion, fields iter.Seq[catalog.Entry]) []Suggestion {
	for field := range fields {
		if !supportedHogQLIdentifier(field.Name) {
			continue
		}
		out = append(out, Suggestion{Label: field.Name, Kind: "field", Detail: field.Type, InsertText: suggestionInsertText("field", field.Name)})
	}
	return out
}

func suggestionInsertText(kind, name string) string {
	insertText := name
	switch kind {
	case "field", "property":
		insertText = quoteHogQLFieldIdentifier(name)
	case "table":
		parts := strings.Split(name, ".")
		for index := range parts {
			parts[index] = quoteHogQLFieldIdentifier(parts[index])
		}
		insertText = strings.Join(parts, ".")
	}
	if insertText == name {
		return ""
	}
	return insertText
}

func supportedHogQLIdentifier(name string) bool {
	return !strings.Contains(name, "%")
}

func quoteHogQLFieldIdentifier(name string) string {
	if _, keyword := hogQLKeywords[strings.ToUpper(name)]; keyword {
		return "`" + hogQLIdentifierEscaper.Replace(name) + "`"
	}
	return quoteHogQLIdentifier(name)
}

func quoteHogQLIdentifier(name string) string {
	if simpleHogQLIdentifier.MatchString(name) {
		return name
	}
	return "`" + hogQLIdentifierEscaper.Replace(name) + "`"
}

func appendFunctions(out []Suggestion, lowerPrefix string) []Suggestion {
	if lowerPrefix == "" {
		for _, name := range commonFunctions {
			out = append(out, Suggestion{Label: name, Kind: "function", Detail: "HogQL function", InsertText: name + "()"})
		}
		return out
	}
	for _, name := range hogQLFunctions {
		if hasLowerPrefix(name, lowerPrefix) {
			out = append(out, Suggestion{Label: name, Kind: "function", Detail: "HogQL function", InsertText: name + "()"})
		}
	}
	return out
}

func appendNamed(out []Suggestion, values []string, lowerPrefix, kind, detail string) []Suggestion {
	for _, value := range values {
		if hasLowerPrefix(value, lowerPrefix) {
			out = append(out, Suggestion{Label: value, Kind: kind, Detail: detail, InsertText: value})
		}
	}
	return out
}

func suggestionRank(kind string) int {
	switch kind {
	case "field", "property", "table":
		return 1
	case "function":
		return 2
	default:
		return 3
	}
}

func cursorWord(input string) (prefix, qualifier string, start int) {
	start = len(input)
	for start > 0 {
		character, size := utf8.DecodeLastRuneInString(input[:start])
		if !isIdentifier(character) {
			break
		}
		start -= size
	}
	prefix = input[start:]
	if start > 0 && input[start-1] == '.' {
		qualifierEnd := start - 1
		qualifierStart := qualifierEnd
		for qualifierStart > 0 {
			character, size := utf8.DecodeLastRuneInString(input[:qualifierStart])
			if !isIdentifier(character) {
				break
			}
			qualifierStart -= size
		}
		qualifier = input[qualifierStart:qualifierEnd]
	}
	return prefix, qualifier, start
}

func isIdentifier(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' || r == '$'
}

func hasLowerPrefix(value, lowerPrefix string) bool {
	return strings.HasPrefix(strings.ToLower(value), lowerPrefix)
}
