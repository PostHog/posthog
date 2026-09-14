package validation

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

type Suggestion struct {
	Label    string `json:"label"`
	Distance int    `json:"distance"`
}

type Diagnostic struct {
	Code        string       `json:"code"`
	Message     string       `json:"message"`
	Start       int          `json:"start"`
	End         int          `json:"end"`
	Suggestions []Suggestion `json:"suggestions,omitempty"`
}

type Result struct {
	Valid          bool         `json:"valid"`
	Diagnostics    []Diagnostic `json:"diagnostics"`
	TableNames     []string     `json:"tableNames"`
	DurationMicros int64        `json:"durationMicros"`
}

type tableBinding struct {
	name  string
	table catalog.Table
}

type queryScope struct {
	query    *clickhouse.SelectQuery
	parent   *queryScope
	bindings map[string]tableBinding
}

var tableReferencePattern = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)`)

func Validate(schema *catalog.Catalog, query string) Result {
	started := time.Now()
	if err := querylimits.Validate(query); err != nil {
		return result([]Diagnostic{{Code: "query_limit", Message: err.Error(), Start: 0, End: len(query)}}, nil, started)
	}
	parserQuery, originalTableNames := normalizeHogQLTableReferences(query)
	statements, err := clickhouse.NewParser(parserQuery).ParseStmts()
	if err != nil {
		return result([]Diagnostic{{
			Code: "syntax_error", Message: err.Error(), Start: 0, End: len(query),
		}}, nil, started)
	}

	tablesByName := make(map[string]catalog.Table, len(schema.Tables))
	for name, table := range schema.Tables {
		tablesByName[strings.ToLower(name)] = table
	}

	var diagnostics []Diagnostic
	var referencedTableNames []string
	seenTableNames := map[string]bool{}
	for _, statement := range statements {
		scopes := queryScopes(statement)
		ignoredIdents := map[*clickhouse.Ident]bool{}
		clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
			switch typed := node.(type) {
			case *clickhouse.TableExpr:
				name, alias, start, end, ok := tableReference(typed)
				if !ok {
					return true
				}
				if original, exists := originalTableNames[strings.ToLower(name)]; exists {
					name = original
				}
				lowerName := strings.ToLower(name)
				if !seenTableNames[lowerName] {
					referencedTableNames = append(referencedTableNames, name)
					seenTableNames[lowerName] = true
				}
				table, exists := tablesByName[strings.ToLower(name)]
				if !exists {
					if len(diagnostics) < querylimits.MaxDiagnostics {
						diagnostics = append(diagnostics, Diagnostic{
							Code: "unknown_table", Message: fmt.Sprintf("Unknown table %q", name), Start: start, End: end,
							Suggestions: closest(name, tableNames(schema), 5),
						})
					}
					return true
				}
				binding := tableBinding{name: name, table: table}
				scope := innermostScope(scopes, start, end)
				if scope == nil {
					return true
				}
				scope.bindings[strings.ToLower(name)] = binding
				if alias != "" {
					scope.bindings[strings.ToLower(alias)] = binding
				}
			case *clickhouse.TableIdentifier:
				ignoredIdents[typed.Database] = true
				ignoredIdents[typed.Table] = true
			case *clickhouse.FunctionExpr:
				ignoredIdents[typed.Name] = true
			case *clickhouse.SelectItem:
				ignoredIdents[typed.Alias] = true
			case *clickhouse.AliasExpr:
				if alias, ok := typed.Alias.(*clickhouse.Ident); ok {
					ignoredIdents[alias] = true
				}
			}
			return true
		})
		seen := map[string]bool{}
		clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
			switch typed := node.(type) {
			case *clickhouse.Path:
				for _, field := range typed.Fields {
					ignoredIdents[field] = true
				}
				if len(typed.Fields) < 2 {
					return true
				}
				bindings := visibleBindings(innermostScope(scopes, int(node.Pos()), int(node.End())))
				if len(bindings) == 0 {
					return true
				}
				parts := make([]string, len(typed.Fields))
				for index, field := range typed.Fields {
					parts[index] = field.Name
				}
				bindingNames := make(map[string]string, len(bindings))
				for name, binding := range bindings {
					bindingNames[name] = binding.name
				}
				if namespace, ok := propertyresolver.Resolve(parts, bindingNames); ok {
					validateProperty(&diagnostics, seen, schema.Properties[namespace], typed.Fields[len(typed.Fields)-1])
					return true
				}
				if binding, ok := bindings[strings.ToLower(typed.Fields[0].Name)]; ok {
					validateField(&diagnostics, seen, binding.table, typed.Fields[1])
				}
			case *clickhouse.Ident:
				if ignoredIdents[typed] {
					return true
				}
				bindings := visibleBindings(innermostScope(scopes, int(node.Pos()), int(node.End())))
				if len(bindings) > 0 {
					validateUnqualifiedField(&diagnostics, seen, bindings, typed)
				}
			}
			return true
		})
	}
	return result(diagnostics, referencedTableNames, started)
}

func queryScopes(statement clickhouse.Expr) []*queryScope {
	var scopes []*queryScope
	clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
		if query, ok := node.(*clickhouse.SelectQuery); ok {
			scopes = append(scopes, &queryScope{query: query, bindings: map[string]tableBinding{}})
		}
		return true
	})
	for _, scope := range scopes {
		for _, candidate := range scopes {
			if scope == candidate || span(candidate.query) <= span(scope.query) || !contains(candidate.query, int(scope.query.Pos()), int(scope.query.End())) {
				continue
			}
			if scope.parent == nil || span(candidate.query) < span(scope.parent.query) {
				scope.parent = candidate
			}
		}
	}
	return scopes
}

func innermostScope(scopes []*queryScope, start, end int) *queryScope {
	var found *queryScope
	for _, scope := range scopes {
		if contains(scope.query, start, end) && (found == nil || span(scope.query) < span(found.query)) {
			found = scope
		}
	}
	return found
}

func contains(query *clickhouse.SelectQuery, start, end int) bool {
	return int(query.Pos()) <= start && end <= int(query.End())
}

func span(query *clickhouse.SelectQuery) int {
	return int(query.End() - query.Pos())
}

func visibleBindings(scope *queryScope) map[string]tableBinding {
	bindings := map[string]tableBinding{}
	for current := scope; current != nil; current = current.parent {
		for name, binding := range current.bindings {
			if _, exists := bindings[name]; !exists {
				bindings[name] = binding
			}
		}
	}
	return bindings
}

func validateProperty(diagnostics *[]Diagnostic, seen map[string]bool, properties []catalog.Property, ident *clickhouse.Ident) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics {
		return
	}
	for _, property := range properties {
		if strings.EqualFold(property.Name, ident.Name) {
			return
		}
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	names := make([]string, len(properties))
	for index, property := range properties {
		names[index] = property.Name
	}
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_property", Message: fmt.Sprintf("Unknown property %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, names, 5),
	})
}

func normalizeHogQLTableReferences(query string) (string, map[string]string) {
	normalized := []byte(query)
	originalNames := map[string]string{}
	for _, indexes := range tableReferencePattern.FindAllStringSubmatchIndex(query, -1) {
		start, end := indexes[2], indexes[3]
		name := query[start:end]
		firstDot := strings.IndexByte(name, '.')
		if firstDot == -1 || !strings.Contains(name[firstDot+1:], ".") {
			continue
		}
		for index := start + firstDot + 1; index < end; index++ {
			if normalized[index] == '.' {
				normalized[index] = '_'
			}
		}
		originalNames[strings.ToLower(string(normalized[start:end]))] = name
	}
	return string(normalized), originalNames
}

func tableReference(expr *clickhouse.TableExpr) (name, alias string, start, end int, ok bool) {
	node := expr.Expr
	if aliased, isAlias := node.(*clickhouse.AliasExpr); isAlias {
		node = aliased.Expr
		if ident, isIdent := aliased.Alias.(*clickhouse.Ident); isIdent {
			alias = ident.Name
		}
	}
	identifier, isTable := node.(*clickhouse.TableIdentifier)
	if !isTable || identifier.Table == nil {
		return "", "", 0, 0, false
	}
	name = identifier.Table.Name
	if identifier.Database != nil {
		name = identifier.Database.Name + "." + name
	}
	return name, alias, int(identifier.Pos()), int(identifier.End()), true
}

func validateField(diagnostics *[]Diagnostic, seen map[string]bool, table catalog.Table, ident *clickhouse.Ident) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics {
		return
	}
	if hasField(table, ident.Name) {
		return
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_field", Message: fmt.Sprintf("Unknown field %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, fieldNames(table), 5),
	})
}

func validateUnqualifiedField(diagnostics *[]Diagnostic, seen map[string]bool, bindings map[string]tableBinding, ident *clickhouse.Ident) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics {
		return
	}
	uniqueTables := map[string]catalog.Table{}
	for _, binding := range bindings {
		uniqueTables[binding.name] = binding.table
		if hasField(binding.table, ident.Name) {
			return
		}
	}
	candidates := make([]string, 0)
	for _, table := range uniqueTables {
		candidates = append(candidates, fieldNames(table)...)
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_field", Message: fmt.Sprintf("Unknown field %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, candidates, 5),
	})
}

func hasField(table catalog.Table, name string) bool {
	for fieldName := range table.Fields {
		if strings.EqualFold(fieldName, name) {
			return true
		}
	}
	return false
}

func tableNames(schema *catalog.Catalog) []string {
	names := make([]string, 0, len(schema.Tables))
	for name := range schema.Tables {
		names = append(names, name)
	}
	return names
}

func fieldNames(table catalog.Table) []string {
	names := make([]string, 0, len(table.Fields))
	for name := range table.Fields {
		names = append(names, name)
	}
	return names
}

func closest(input string, candidates []string, limit int) []Suggestion {
	if len(input) > querylimits.MaxSuggestionInputBytes {
		return nil
	}
	lowerInput := strings.ToLower(input)
	leftRunes := []rune(lowerInput)
	threshold := min(4, max(2, len(leftRunes)/3))
	unique := map[string]Suggestion{}
	for _, candidate := range candidates {
		if len(candidate) > querylimits.MaxSuggestionInputBytes {
			continue
		}
		lowerCandidate := strings.ToLower(candidate)
		rightRunes := []rune(lowerCandidate)
		lengthDifference := max(len(leftRunes), len(rightRunes)) - min(len(leftRunes), len(rightRunes))
		prefix := strings.HasPrefix(lowerCandidate, lowerInput)
		if lengthDifference > threshold && !prefix {
			continue
		}
		distance := lengthDifference
		if !prefix {
			distance = levenshtein(leftRunes, rightRunes)
		}
		if distance > threshold {
			continue
		}
		key := lowerCandidate
		if existing, ok := unique[key]; !ok || distance < existing.Distance {
			unique[key] = Suggestion{Label: candidate, Distance: distance}
		}
	}
	result := make([]Suggestion, 0, len(unique))
	for _, suggestion := range unique {
		result = append(result, suggestion)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Distance != result[j].Distance {
			return result[i].Distance < result[j].Distance
		}
		return result[i].Label < result[j].Label
	})
	return result[:min(limit, len(result))]
}

func levenshtein(leftRunes, rightRunes []rune) int {
	previous := make([]int, len(rightRunes)+1)
	current := make([]int, len(rightRunes)+1)
	for index := range previous {
		previous[index] = index
	}
	for leftIndex, leftRune := range leftRunes {
		current[0] = leftIndex + 1
		for rightIndex, rightRune := range rightRunes {
			cost := 1
			if leftRune == rightRune {
				cost = 0
			}
			current[rightIndex+1] = min(current[rightIndex]+1, previous[rightIndex+1]+1, previous[rightIndex]+cost)
		}
		previous, current = current, previous
	}
	return previous[len(rightRunes)]
}

func result(diagnostics []Diagnostic, tableNames []string, started time.Time) Result {
	if diagnostics == nil {
		diagnostics = []Diagnostic{}
	}
	if tableNames == nil {
		tableNames = []string{}
	}
	return Result{
		Valid: len(diagnostics) == 0, Diagnostics: diagnostics, TableNames: tableNames,
		DurationMicros: time.Since(started).Microseconds(),
	}
}
