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
)

type Suggestion struct {
	Label  string `json:"label"`
	Kind   string `json:"kind"`
	Detail string `json:"detail,omitempty"`
}

type Result struct {
	Suggestions []Suggestion `json:"suggestions"`
	Total       int          `json:"total"`
	NextCursor  string       `json:"nextCursor,omitempty"`
	ParseError  string       `json:"parseError,omitempty"`
}

const PageSize = 25

var keywords = []string{"SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "LIMIT", "JOIN", "AS"}
var tableReference = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)(?:\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*))?`)

func Complete(schema *catalog.Catalog, query string, position int, cursor string) (Result, error) {
	if err := querylimits.Validate(query); err != nil {
		return Result{}, err
	}
	offset, err := decodeCursor(cursor)
	if err != nil {
		return Result{}, err
	}
	if position < 0 || position > len(query) {
		position = len(query)
	}
	prefix, qualifier, start := cursorWord(query[:position])
	if len(prefix) > querylimits.MaxSuggestionInputBytes {
		return Result{Suggestions: []Suggestion{}}, nil
	}
	lowerPrefix := strings.ToLower(prefix)
	repaired := query[:start] + "__posthog_cursor__" + query[position:]
	bindings, parseErr := tableBindings(repaired)
	tablesByLowerName := tableNamesByLowerName(schema)
	for binding, tableName := range bindings {
		if canonicalName, ok := tablesByLowerName[strings.ToLower(tableName)]; ok {
			bindings[binding] = canonicalName
		}
	}
	for binding, tableName := range fallbackBindings(repaired, tablesByLowerName) {
		bindings[binding] = tableName
	}

	var suggestions []Suggestion
	if namespace, propertyPrefix, ok := propertyContext(query[:position], bindings); ok {
		lowerPropertyPrefix := strings.ToLower(propertyPrefix)
		for _, property := range schema.Properties[namespace] {
			if hasLowerPrefix(property.Name, lowerPropertyPrefix) {
				suggestions = append(suggestions, Suggestion{Label: property.Name, Kind: "property", Detail: property.ValueType})
			}
		}
	} else if qualifier != "" {
		if tableName, ok := bindings[strings.ToLower(qualifier)]; ok {
			suggestions = appendFields(suggestions, schema.Tables[tableName], lowerPrefix)
		}
	} else if expectsTable(query[:start]) {
		for name, table := range schema.Tables {
			if hasLowerPrefix(name, lowerPrefix) {
				suggestions = append(suggestions, Suggestion{Label: name, Kind: "table", Detail: table.Type})
			}
		}
	} else {
		seen := map[string]bool{}
		for _, tableName := range bindings {
			if seen[tableName] {
				continue
			}
			seen[tableName] = true
			suggestions = appendFields(suggestions, schema.Tables[tableName], lowerPrefix)
		}
		for _, keyword := range keywords {
			if hasLowerPrefix(keyword, lowerPrefix) {
				suggestions = append(suggestions, Suggestion{Label: keyword, Kind: "keyword"})
			}
		}
	}
	sort.Slice(suggestions, func(i, j int) bool {
		if suggestions[i].Kind != suggestions[j].Kind {
			return suggestions[i].Kind < suggestions[j].Kind
		}
		return suggestions[i].Label < suggestions[j].Label
	})
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
func fallbackBindings(query string, tablesByLowerName map[string]string) map[string]string {
	bindings := map[string]string{}
	for _, match := range tableReference.FindAllStringSubmatch(query, -1) {
		tableName, ok := tablesByLowerName[strings.ToLower(match[1])]
		if !ok {
			continue
		}
		bindings[strings.ToLower(tableName)] = tableName
		if match[2] != "" && !strings.EqualFold(match[2], "FINAL") {
			bindings[strings.ToLower(match[2])] = tableName
		}
	}
	return bindings
}

func tableNamesByLowerName(schema *catalog.Catalog) map[string]string {
	tables := make(map[string]string, len(schema.Tables))
	for name := range schema.Tables {
		tables[strings.ToLower(name)] = name
	}
	return tables
}

func appendFields(out []Suggestion, table catalog.Table, lowerPrefix string) []Suggestion {
	for name, field := range table.Fields {
		if hasLowerPrefix(name, lowerPrefix) {
			out = append(out, Suggestion{Label: name, Kind: "field", Detail: field.Type})
		}
	}
	return out
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

func expectsTable(input string) bool {
	words := strings.Fields(strings.ToUpper(input))
	if len(words) == 0 {
		return false
	}
	last := words[len(words)-1]
	return last == "FROM" || last == "JOIN" || strings.HasSuffix(strings.TrimSpace(input), ",")
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
