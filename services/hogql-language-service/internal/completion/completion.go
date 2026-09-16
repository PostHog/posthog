package completion

import (
	"encoding/base64"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
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
var tableReference = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?`)
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
	bindings, parseErr := tableBindings(repaired)
	for binding, tableName := range bindings {
		if table, ok := schema.Table(tableName); ok {
			bindings[binding] = table.Name
		}
	}
	for binding, tableName := range fallbackBindings(repaired, schema) {
		bindings[binding] = tableName
	}

	var suggestions []Suggestion
	if namespace, propertyPrefix, ok := propertyContext(query[:position], bindings); ok {
		return indexedResult(schema.Properties(namespace).Prefix(propertyPrefix), "property", offset, parseErr), nil
	} else if qualifier != "" {
		if tableName, ok := bindings[strings.ToLower(qualifier)]; ok {
			if table, exists := schema.Table(tableName); exists {
				return indexedResult(table.Fields.Prefix(lowerPrefix), "field", offset, parseErr), nil
			}
		}
		return indexedResult(nil, "field", offset, parseErr), nil
	} else if mode == completionModeTable {
		return indexedResult(schema.Tables().Prefix(lowerPrefix), "table", offset, parseErr), nil
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
		seen := map[string]bool{}
		for _, tableName := range bindings {
			if seen[tableName] {
				continue
			}
			seen[tableName] = true
			if table, ok := schema.Table(tableName); ok {
				suggestions = appendFields(suggestions, table, lowerPrefix)
			}
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

func indexedResult(entries []catalog.Entry, kind string, offset int, parseErr error) Result {
	result := Result{Total: len(entries)}
	if offset > len(entries) {
		offset = len(entries)
	}
	end := min(offset+PageSize, len(entries))
	result.Suggestions = make([]Suggestion, end-offset)
	rank := strconv.Itoa(suggestionRank(kind)) + "-"
	for index, entry := range entries[offset:end] {
		result.Suggestions[index] = Suggestion{
			Label: entry.Name, Kind: kind, Detail: entry.Type, InsertText: suggestionInsertText(kind, entry.Name), SortText: rank + strings.ToLower(entry.Name),
		}
	}
	if end < len(entries) {
		result.NextCursor = encodeCursor(end)
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

func propertyContext(input string, bindings map[string]string) (string, string, bool) {
	start := len(input)
	for start > 0 {
		character := input[start-1]
		if character != '.' && character != '$' && !isIdentifier(rune(character)) {
			break
		}
		start--
	}
	parts := strings.Split(input[start:], ".")
	if len(parts) < 2 {
		return "", "", false
	}
	namespace, ok := propertyresolver.Resolve(parts, bindings)
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

// The ClickHouse grammar accepts database.table while HogQL warehouse names may have more segments.
// Keep parser-derived bindings as the primary path and fill that syntax gap until the grammar supports it.
func fallbackBindings(query string, schema *catalog.PreparedCatalog) map[string]string {
	bindings := map[string]string{}
	for _, match := range tableReference.FindAllStringSubmatch(query, -1) {
		table, ok := schema.Table(match[1])
		if !ok {
			continue
		}
		bindings[strings.ToLower(table.Name)] = table.Name
		if match[2] != "" && !strings.EqualFold(match[2], "FINAL") {
			bindings[strings.ToLower(match[2])] = table.Name
		}
	}
	return bindings
}

func appendFields(out []Suggestion, table *catalog.PreparedTable, lowerPrefix string) []Suggestion {
	for _, field := range table.Fields.Prefix(lowerPrefix) {
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
			parts[index] = quoteHogQLIdentifier(parts[index])
		}
		insertText = strings.Join(parts, ".")
	}
	if insertText == name {
		return ""
	}
	return insertText
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
	for start > 0 && isIdentifier(rune(input[start-1])) {
		start--
	}
	prefix = input[start:]
	if start > 0 && input[start-1] == '.' {
		qualifierEnd := start - 1
		qualifierStart := qualifierEnd
		for qualifierStart > 0 && isIdentifier(rune(input[qualifierStart-1])) {
			qualifierStart--
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

func tableBindings(query string) (map[string]string, error) {
	statements, err := clickhouse.NewParser(query).ParseStmts()
	if err != nil {
		return map[string]string{}, fmt.Errorf("parse incomplete SQL: %w", err)
	}
	bindings := map[string]string{}
	for _, statement := range statements {
		clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
			tableExpr, ok := node.(*clickhouse.TableExpr)
			if !ok {
				return true
			}
			tableNode := tableExpr.Expr
			var aliasName string
			if aliased, ok := tableNode.(*clickhouse.AliasExpr); ok {
				tableNode = aliased.Expr
				if alias, ok := aliased.Alias.(*clickhouse.Ident); ok {
					aliasName = alias.Name
				}
			}
			identifier, ok := tableNode.(*clickhouse.TableIdentifier)
			if !ok || identifier.Table == nil {
				return true
			}
			name := identifier.Table.Name
			if identifier.Database != nil {
				name = identifier.Database.Name + "." + name
			}
			bindings[strings.ToLower(name)] = name
			if aliasName != "" {
				bindings[strings.ToLower(aliasName)] = name
			}
			return false
		})
	}
	return bindings, nil
}
