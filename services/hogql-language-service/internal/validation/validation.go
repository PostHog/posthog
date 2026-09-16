package validation

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/textposition"
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
	table *catalog.PreparedTable
	cte   *cteBinding
}

type cteBinding struct {
	name       string
	query      *clickhouse.SelectQuery
	scope      *queryScope
	budget     *projectionBudget
	fields     []catalog.Entry
	fieldsDone bool
	resolving  bool
}

type projectionBudget struct {
	remaining int
	exceeded  bool
}

type queryScope struct {
	query    *clickhouse.SelectQuery
	parent   *queryScope
	bindings map[string]tableBinding
	ctes     []*cteBinding
	cteRoot  bool
}

var tableReferencePattern = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)`)

func Validate(schema *catalog.PreparedCatalog, query string) Result {
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

	var diagnostics []Diagnostic
	var referencedTableNames []string
	seenTableNames := map[string]bool{}
	budget := projectionBudget{remaining: querylimits.MaxCTEProjectedFields}
	for _, statement := range statements {
		scopes := queryScopes(statement, &budget)
		ignoredIdents := map[*clickhouse.Ident]bool{}
		clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
			switch typed := node.(type) {
			case *clickhouse.TableExpr:
				name, alias, start, end, ok := tableReference(typed)
				if !ok {
					return true
				}
				scope := innermostScope(scopes, start, end)
				if scope == nil {
					return true
				}
				if cte := resolveCTE(scope, name, start); cte != nil {
					addBinding(scope, name, alias, tableBinding{name: cte.name, cte: cte})
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
				table, exists := schema.Table(name)
				if !exists {
					if len(diagnostics) < querylimits.MaxDiagnostics {
						diagnostics = append(diagnostics, Diagnostic{
							Code: "unknown_table", Message: fmt.Sprintf("Unknown table %q", name), Start: start, End: end,
							Suggestions: closest(name, schema.Tables().Entries(), 5),
						})
					}
					return true
				}
				binding := tableBinding{name: name, table: table}
				addBinding(scope, name, alias, binding)
			case *clickhouse.TableIdentifier:
				ignoredIdents[typed.Database] = true
				ignoredIdents[typed.Table] = true
			case *clickhouse.CTEStmt:
				if ident, ok := typed.Expr.(*clickhouse.Ident); ok {
					ignoredIdents[ident] = true
				}
			case *clickhouse.FunctionExpr:
				ignoredIdents[typed.Name] = true
			case *clickhouse.IntervalExpr:
				ignoredIdents[typed.Unit] = true
			case *clickhouse.IntervalFrom:
				ignoredIdents[typed.Interval] = true
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
			case *clickhouse.NestedIdentifier:
				if typed.DotIdent == nil {
					return true
				}
				ignoredIdents[typed.DotIdent] = true
				bindings := visibleBindings(innermostScope(scopes, int(node.Pos()), int(node.End())))
				if binding, ok := bindings[strings.ToLower(typed.Ident.Name)]; ok {
					ignoredIdents[typed.Ident] = true
					if typed.DotIdent.Name != "*" {
						validateField(&diagnostics, seen, binding, typed.DotIdent, &budget)
					}
				}
			case *clickhouse.Path:
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
					for _, field := range typed.Fields {
						ignoredIdents[field] = true
					}
					validateProperty(&diagnostics, seen, schema.Properties(namespace), typed.Fields[len(typed.Fields)-1])
					return true
				}
				if binding, ok := bindings[strings.ToLower(typed.Fields[0].Name)]; ok {
					for _, field := range typed.Fields {
						ignoredIdents[field] = true
					}
					validateField(&diagnostics, seen, binding, typed.Fields[1], &budget)
				} else {
					for _, field := range typed.Fields[1:] {
						ignoredIdents[field] = true
					}
				}
			case *clickhouse.Ident:
				if ignoredIdents[typed] || typed.Name == "*" {
					return true
				}
				bindings := visibleBindings(innermostScope(scopes, int(node.Pos()), int(node.End())))
				if len(bindings) > 0 {
					validateUnqualifiedField(&diagnostics, seen, bindings, typed, &budget)
				}
			}
			return true
		})
		if budget.exceeded {
			break
		}
	}
	if budget.exceeded && len(diagnostics) < querylimits.MaxDiagnostics {
		diagnostics = append(diagnostics, Diagnostic{
			Code: "query_limit", Message: querylimits.ErrCTEProjectionTooLarge.Error(), Start: 0, End: len(query),
		})
	}
	return result(diagnostics, referencedTableNames, started)
}

func ValidateWithEncoding(schema *catalog.PreparedCatalog, query string, encoding textposition.Encoding) (Result, error) {
	if !encoding.Valid() {
		return Result{}, fmt.Errorf("unsupported position encoding %q", encoding)
	}
	result := Validate(schema, query)
	for index := range result.Diagnostics {
		start, err := textposition.FromByteOffset(query, result.Diagnostics[index].Start, encoding)
		if err != nil {
			return Result{}, err
		}
		end, err := textposition.FromByteOffset(query, result.Diagnostics[index].End, encoding)
		if err != nil {
			return Result{}, err
		}
		result.Diagnostics[index].Start = start
		result.Diagnostics[index].End = end
	}
	return result, nil
}

func queryScopes(statement clickhouse.Expr, budget *projectionBudget) []*queryScope {
	var scopes []*queryScope
	byQuery := map[*clickhouse.SelectQuery]*queryScope{}
	clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
		if query, ok := node.(*clickhouse.SelectQuery); ok {
			scope := &queryScope{query: query, bindings: map[string]tableBinding{}}
			scopes = append(scopes, scope)
			byQuery[query] = scope
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
	for _, scope := range scopes {
		if scope.query.With == nil {
			continue
		}
		for _, statement := range scope.query.With.CTEs {
			name, nameOK := statement.Expr.(*clickhouse.Ident)
			query, queryOK := statement.Alias.(*clickhouse.SelectQuery)
			if !nameOK || !queryOK {
				continue
			}
			cte := &cteBinding{name: name.Name, query: query, scope: byQuery[query], budget: budget}
			if cte.scope != nil {
				cte.scope.cteRoot = true
			}
			scope.ctes = append(scope.ctes, cte)
		}
	}
	return scopes
}

func addBinding(scope *queryScope, name, alias string, binding tableBinding) {
	scope.bindings[strings.ToLower(name)] = binding
	if alias != "" {
		scope.bindings[strings.ToLower(alias)] = binding
	}
}

func resolveCTE(scope *queryScope, name string, position int) *cteBinding {
	for current := scope; current != nil; current = current.parent {
		limit := len(current.ctes)
		for index, cte := range current.ctes {
			if contains(cte.query, position, position) {
				limit = index
				break
			}
		}
		for index := limit - 1; index >= 0; index-- {
			if strings.EqualFold(current.ctes[index].name, name) {
				return current.ctes[index]
			}
		}
	}
	return nil
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
		if current.cteRoot {
			break
		}
	}
	return bindings
}

func validateProperty(diagnostics *[]Diagnostic, seen map[string]bool, properties *catalog.Index, ident *clickhouse.Ident) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics {
		return
	}
	if _, ok := properties.Exact(ident.Name); ok {
		return
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_property", Message: fmt.Sprintf("Unknown property %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, properties.Entries(), 5),
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

func validateField(diagnostics *[]Diagnostic, seen map[string]bool, binding tableBinding, ident *clickhouse.Ident, budget *projectionBudget) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics || budget.exceeded {
		return
	}
	if _, ok := bindingField(binding, ident.Name); ok {
		return
	}
	if budget.exceeded {
		return
	}
	key := fmt.Sprintf("%d:%d", ident.Pos(), ident.End())
	if seen[key] {
		return
	}
	seen[key] = true
	*diagnostics = append(*diagnostics, Diagnostic{
		Code: "unknown_field", Message: fmt.Sprintf("Unknown field %q", ident.Name), Start: int(ident.Pos()), End: int(ident.End()),
		Suggestions: closest(ident.Name, bindingFields(binding), 5),
	})
}

func validateUnqualifiedField(diagnostics *[]Diagnostic, seen map[string]bool, bindings map[string]tableBinding, ident *clickhouse.Ident, budget *projectionBudget) {
	if len(*diagnostics) >= querylimits.MaxDiagnostics || budget.exceeded {
		return
	}
	uniqueTables := map[string]tableBinding{}
	for _, binding := range bindings {
		uniqueTables[binding.name] = binding
		if _, ok := bindingField(binding, ident.Name); ok {
			return
		}
		if budget.exceeded {
			return
		}
	}
	candidates := make([]catalog.Entry, 0)
	for _, binding := range uniqueTables {
		candidates = append(candidates, bindingFields(binding)...)
		if budget.exceeded {
			return
		}
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

func bindingField(binding tableBinding, name string) (catalog.Entry, bool) {
	if binding.table != nil {
		return binding.table.Fields.Exact(name)
	}
	for _, field := range bindingFields(binding) {
		if strings.EqualFold(field.Name, name) {
			return field, true
		}
	}
	return catalog.Entry{}, false
}

func bindingFields(binding tableBinding) []catalog.Entry {
	if binding.table != nil {
		return binding.table.Fields.Entries()
	}
	if binding.cte == nil {
		return nil
	}
	return binding.cte.projectedFields()
}

func (c *cteBinding) projectedFields() []catalog.Entry {
	if c.fieldsDone || c.resolving || c.scope == nil || c.budget.exceeded {
		return c.fields
	}
	c.resolving = true
	for _, item := range c.query.SelectItems {
		if item.Alias != nil {
			c.appendField(catalog.Entry{Name: item.Alias.Name, Type: projectedType(c.scope, item.Expr)})
			if c.budget.exceeded {
				break
			}
			continue
		}
		switch expr := item.Expr.(type) {
		case *clickhouse.Ident:
			if expr.Name == "*" {
				c.appendWildcardFields(c.scope, "")
			} else {
				c.appendField(catalog.Entry{Name: expr.Name, Type: projectedType(c.scope, expr)})
			}
		case *clickhouse.Path:
			if len(expr.Fields) > 0 {
				c.appendField(catalog.Entry{Name: expr.Fields[len(expr.Fields)-1].Name, Type: projectedType(c.scope, expr)})
			}
		case *clickhouse.NestedIdentifier:
			if expr.DotIdent != nil && expr.DotIdent.Name == "*" {
				c.appendWildcardFields(c.scope, expr.Ident.Name)
			} else if expr.DotIdent != nil {
				c.appendField(catalog.Entry{Name: expr.DotIdent.Name, Type: projectedType(c.scope, expr)})
			} else {
				c.appendField(catalog.Entry{Name: expr.Ident.Name, Type: projectedType(c.scope, expr)})
			}
		default:
			c.appendField(catalog.Entry{Name: item.Expr.String()})
		}
		if c.budget.exceeded {
			break
		}
	}
	c.resolving = false
	c.fieldsDone = true
	return c.fields
}

func (c *cteBinding) appendField(field catalog.Entry) {
	if c.budget.take(1) == 1 {
		c.fields = append(c.fields, field)
	}
}

func (c *cteBinding) appendFields(fields []catalog.Entry) {
	count := c.budget.take(len(fields))
	c.fields = append(c.fields, fields[:count]...)
}

func (c *cteBinding) appendWildcardFields(scope *queryScope, qualifier string) {
	bindings := visibleBindings(scope)
	if qualifier != "" {
		c.appendFields(bindingFields(bindings[strings.ToLower(qualifier)]))
		return
	}
	seen := map[string]bool{}
	for _, binding := range bindings {
		if seen[binding.name] {
			continue
		}
		seen[binding.name] = true
		c.appendFields(bindingFields(binding))
		if c.budget.exceeded {
			return
		}
	}
}

func (b *projectionBudget) take(count int) int {
	if count <= b.remaining {
		b.remaining -= count
		return count
	}
	taken := b.remaining
	b.remaining = 0
	b.exceeded = true
	return taken
}

func projectedType(scope *queryScope, expr clickhouse.Expr) string {
	bindings := visibleBindings(scope)
	switch typed := expr.(type) {
	case *clickhouse.Ident:
		for _, binding := range bindings {
			if field, ok := bindingField(binding, typed.Name); ok {
				return field.Type
			}
		}
	case *clickhouse.Path:
		if len(typed.Fields) >= 2 {
			if binding, ok := bindings[strings.ToLower(typed.Fields[0].Name)]; ok {
				if field, exists := bindingField(binding, typed.Fields[1].Name); exists {
					return field.Type
				}
			}
		}
	case *clickhouse.NestedIdentifier:
		if typed.DotIdent != nil {
			if binding, ok := bindings[strings.ToLower(typed.Ident.Name)]; ok {
				if field, exists := bindingField(binding, typed.DotIdent.Name); exists {
					return field.Type
				}
			}
		}
	}
	return ""
}

func closest(input string, candidates []catalog.Entry, limit int) []Suggestion {
	if len(input) > querylimits.MaxSuggestionInputBytes {
		return nil
	}
	lowerInput := strings.ToLower(input)
	leftLength := utf8.RuneCountInString(lowerInput)
	threshold := min(4, max(2, leftLength/3))
	best := make([]Suggestion, 0, limit)
	workspace := levenshteinWorkspace{}
	for _, candidate := range candidates {
		if len(candidate.Name) > querylimits.MaxSuggestionInputBytes {
			continue
		}
		lowerCandidate := strings.ToLower(candidate.Name)
		rightLength := utf8.RuneCountInString(lowerCandidate)
		lengthDifference := max(leftLength, rightLength) - min(leftLength, rightLength)
		prefix := strings.HasPrefix(lowerCandidate, lowerInput)
		if lengthDifference > threshold && !prefix {
			continue
		}
		distance := lengthDifference
		if !prefix {
			distance = workspace.distance(lowerInput, lowerCandidate, threshold)
		}
		if distance > threshold {
			continue
		}
		suggestion := Suggestion{Label: candidate.Name, Distance: distance}
		duplicate := false
		for _, existing := range best {
			if strings.EqualFold(existing.Label, suggestion.Label) {
				duplicate = true
				break
			}
		}
		if duplicate {
			continue
		}
		if len(best) < limit {
			best = append(best, suggestion)
			sortSuggestions(best)
		} else if suggestionLess(suggestion, best[len(best)-1]) {
			best[len(best)-1] = suggestion
			sortSuggestions(best)
		}
	}
	return best
}

func sortSuggestions(suggestions []Suggestion) {
	sort.Slice(suggestions, func(left, right int) bool {
		return suggestionLess(suggestions[left], suggestions[right])
	})
}

func suggestionLess(left, right Suggestion) bool {
	if left.Distance != right.Distance {
		return left.Distance < right.Distance
	}
	return left.Label < right.Label
}

type levenshteinWorkspace struct {
	previous []int
	current  []int
}

func (w *levenshteinWorkspace) distance(left, right string, limit int) int {
	if isASCII(left) && isASCII(right) {
		for len(left) > 0 && len(right) > 0 && left[0] == right[0] {
			left = left[1:]
			right = right[1:]
		}
		for len(left) > 0 && len(right) > 0 && left[len(left)-1] == right[len(right)-1] {
			left = left[:len(left)-1]
			right = right[:len(right)-1]
		}
		return w.distanceASCII(left, right, limit)
	}
	leftRunes := []rune(left)
	rightRunes := []rune(right)
	for len(leftRunes) > 0 && len(rightRunes) > 0 && leftRunes[0] == rightRunes[0] {
		leftRunes = leftRunes[1:]
		rightRunes = rightRunes[1:]
	}
	for len(leftRunes) > 0 && len(rightRunes) > 0 && leftRunes[len(leftRunes)-1] == rightRunes[len(rightRunes)-1] {
		leftRunes = leftRunes[:len(leftRunes)-1]
		rightRunes = rightRunes[:len(rightRunes)-1]
	}
	return w.distanceRunes(leftRunes, rightRunes, limit)
}

func (w *levenshteinWorkspace) distanceASCII(left, right string, limit int) int {
	w.resize(len(right) + 1)
	for index := range len(right) + 1 {
		w.previous[index] = index
	}
	for leftIndex := range len(left) {
		w.current[0] = leftIndex + 1
		rowMinimum := w.current[0]
		for rightIndex := range len(right) {
			cost := 1
			if left[leftIndex] == right[rightIndex] {
				cost = 0
			}
			w.current[rightIndex+1] = min(w.current[rightIndex]+1, w.previous[rightIndex+1]+1, w.previous[rightIndex]+cost)
			rowMinimum = min(rowMinimum, w.current[rightIndex+1])
		}
		if rowMinimum > limit {
			return limit + 1
		}
		w.previous, w.current = w.current, w.previous
	}
	return w.previous[len(right)]
}

func (w *levenshteinWorkspace) distanceRunes(left, right []rune, limit int) int {
	w.resize(len(right) + 1)
	for index := range len(right) + 1 {
		w.previous[index] = index
	}
	for leftIndex, leftRune := range left {
		w.current[0] = leftIndex + 1
		rowMinimum := w.current[0]
		for rightIndex, rightRune := range right {
			cost := 1
			if leftRune == rightRune {
				cost = 0
			}
			w.current[rightIndex+1] = min(w.current[rightIndex]+1, w.previous[rightIndex+1]+1, w.previous[rightIndex]+cost)
			rowMinimum = min(rowMinimum, w.current[rightIndex+1])
		}
		if rowMinimum > limit {
			return limit + 1
		}
		w.previous, w.current = w.current, w.previous
	}
	return w.previous[len(right)]
}

func (w *levenshteinWorkspace) resize(size int) {
	if cap(w.previous) < size {
		w.previous = make([]int, size)
		w.current = make([]int, size)
		return
	}
	w.previous = w.previous[:size]
	w.current = w.current[:size]
}

func isASCII(value string) bool {
	for index := range len(value) {
		if value[index] >= utf8.RuneSelf {
			return false
		}
	}
	return true
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
