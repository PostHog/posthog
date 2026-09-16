package analysis

import (
	"regexp"
	"strings"
	"unicode"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

type Relation struct {
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
	fieldIndex map[string]catalog.Entry
	fieldsDone bool
	resolving  bool
}

type projectionBudget struct {
	remaining       int
	exceeded        bool
	lookupRemaining int
	lookupExceeded  bool
}

type queryScope struct {
	query    *clickhouse.SelectQuery
	parent   *queryScope
	bindings map[string]Relation
	visible  map[string]Relation
	unique   []Relation
	budget   *projectionBudget
	ctes     []*cteBinding
	cteRoot  bool
	aliases  map[string]selectAlias
}

var tableReferencePattern = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)`)

func queryScopes(statement clickhouse.Expr, budget *projectionBudget) []*queryScope {
	var scopes []*queryScope
	byQuery := map[*clickhouse.SelectQuery]*queryScope{}
	clickhouse.Walk(statement, func(node clickhouse.Expr) bool {
		if query, ok := node.(*clickhouse.SelectQuery); ok {
			scope := &queryScope{query: query, bindings: map[string]Relation{}, budget: budget}
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

func addBinding(scope *queryScope, name, alias string, binding Relation) {
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

func visibleBindings(scope *queryScope) map[string]Relation {
	if scope.visible != nil {
		return scope.visible
	}
	bindings := map[string]Relation{}
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
	scope.visible = bindings
	return bindings
}

func (s *queryScope) uniqueBindings() []Relation {
	if s.unique != nil {
		return s.unique
	}
	s.unique = make([]Relation, 0)
	seen := map[Relation]bool{}
	for _, relation := range visibleBindings(s) {
		if !s.budget.lookup(1) {
			return nil
		}
		if !seen[relation] {
			seen[relation] = true
			s.unique = append(s.unique, relation)
		}
	}
	return s.unique
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

func bindSubquery(expr *clickhouse.TableExpr, scopes []*queryScope, budget *projectionBudget) bool {
	node := expr.Expr
	var alias string
	if aliased, ok := node.(*clickhouse.AliasExpr); ok {
		node = aliased.Expr
		if ident, ok := aliased.Alias.(*clickhouse.Ident); ok {
			alias = ident.Name
		}
	}
	subquery, ok := node.(*clickhouse.SubQuery)
	if !ok {
		return false
	}
	inner := innermostScope(scopes, int(subquery.Select.Pos()), int(subquery.Select.End()))
	if inner != nil && inner.parent != nil {
		// FROM subqueries do not inherit the containing query's table bindings.
		inner.cteRoot = true
		if alias != "" {
			derived := &cteBinding{name: alias, query: subquery.Select, scope: inner, budget: budget}
			addBinding(inner.parent, alias, "", Relation{name: alias, cte: derived})
		}
	}
	return true
}

func foldedFieldName(name string) string {
	return strings.Map(func(r rune) rune {
		first := r
		for next := unicode.SimpleFold(r); next != r; next = unicode.SimpleFold(next) {
			first = min(first, next)
		}
		return first
	}, name)
}

func bindingField(binding Relation, name string) (catalog.Entry, bool) {
	if binding.table != nil {
		return binding.table.Fields.Exact(name)
	}
	if binding.cte == nil {
		return catalog.Entry{}, false
	}
	c := binding.cte
	fields := c.projectedFields()
	if !c.fieldsDone || !c.budget.lookup(len(name)+1) {
		return catalog.Entry{}, false
	}
	if c.fieldIndex == nil {
		c.fieldIndex = make(map[string]catalog.Entry, len(fields))
		for _, field := range fields {
			if !c.budget.lookup(len(field.Name) + 1) {
				return catalog.Entry{}, false
			}
			key := foldedFieldName(field.Name)
			if _, exists := c.fieldIndex[key]; !exists {
				c.fieldIndex[key] = field
			}
		}
	}
	field, ok := c.fieldIndex[foldedFieldName(name)]
	return field, ok
}

func bindingFields(binding Relation) []catalog.Entry {
	if binding.table != nil {
		return binding.table.Fields.Entries()
	}
	if binding.cte == nil {
		return nil
	}
	return binding.cte.projectedFields()
}

func (c *cteBinding) projectedFields() []catalog.Entry {
	if c.fieldsDone || c.resolving || c.scope == nil || c.budget.exceeded || c.budget.lookupExceeded {
		return c.fields
	}
	c.resolving = true
	for _, item := range c.query.SelectItems {
		if item.Alias != nil {
			c.appendField(catalog.Entry{Name: item.Alias.Name, Type: projectedType(c.scope, item.Expr)})
			if c.budget.exceeded || c.budget.lookupExceeded {
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
		if c.budget.exceeded || c.budget.lookupExceeded {
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
	if b.lookupExceeded || b.exceeded {
		return 0
	}
	if count <= b.remaining {
		b.remaining -= count
		return count
	}
	taken := b.remaining
	b.remaining = 0
	b.exceeded = true
	return taken
}

// Count names as bytes so long identifiers cannot hide expensive work behind one lookup.
func (b *projectionBudget) lookup(work int) bool {
	if b.exceeded || b.lookupExceeded {
		return false
	}
	if work > b.lookupRemaining {
		b.lookupExceeded = true
		return false
	}
	b.lookupRemaining -= work
	return true
}

func projectedType(scope *queryScope, expr clickhouse.Expr) string {
	bindings := visibleBindings(scope)
	switch typed := expr.(type) {
	case *clickhouse.Ident:
		if field, ok := (Bindings{scope: scope, position: int(expr.Pos())}).SelectAlias(typed.Name); ok {
			return field.Type
		}
		for _, binding := range scope.uniqueBindings() {
			if !scope.budget.lookup(len(typed.Name) + 1) {
				return ""
			}
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
