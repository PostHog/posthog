package analysis

import (
	"regexp"
	"strings"
	"unicode"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
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
	fields     []projectedField
	entries    []catalog.Entry
	fieldIndex map[string]projectedField
	fieldsDone bool
	resolving  bool
}

type projectedField struct {
	entry             catalog.Entry
	propertyNamespace string
	ambiguous         bool
}

type projectionBudget struct {
	remaining       int
	exceeded        bool
	lookupRemaining int
	lookupExceeded  bool
}

type queryScope struct {
	query              *clickhouse.SelectQuery
	parent             *queryScope
	bindings           map[string]Relation
	sources            []Source
	visible            map[string]Relation
	unique             []Relation
	budget             *projectionBudget
	ctes               []*cteBinding
	cteRoot            bool
	aliases            map[string]selectAlias
	propertyNamespaces map[string]propertyNamespace
	sourceNames        map[string]int
	duplicateSources   []Source
}

type propertyNamespace struct {
	name    string
	ok      bool
	matched bool
}

var tableReferencePattern = regexp.MustCompile(`(?i)\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.$]*)`)

func queryScopes(statement clickhouse.Expr, budget *projectionBudget) []*queryScope {
	var scopes []*queryScope
	byQuery := map[*clickhouse.SelectQuery]*queryScope{}
	walkIncludingExcept(statement, func(node clickhouse.Expr) bool {
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
		if scope.parent != nil && (scope.parent.query.UnionAll == scope.query || scope.parent.query.UnionDistinct == scope.query || scope.parent.query.Except == scope.query) {
			scope.cteRoot = true
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

func walkIncludingExcept(expr clickhouse.Expr, visit func(clickhouse.Expr) bool) {
	var exceptBranches []*clickhouse.SelectQuery
	seenExcept := map[*clickhouse.SelectQuery]bool{}
	wrapper := func(node clickhouse.Expr) bool {
		walkChildren := visit(node)
		if query, ok := node.(*clickhouse.SelectQuery); ok && walkChildren && query.Except != nil && !seenExcept[query.Except] {
			seenExcept[query.Except] = true
			exceptBranches = append(exceptBranches, query.Except)
		}
		return walkChildren
	}
	clickhouse.Walk(expr, wrapper)
	for len(exceptBranches) > 0 {
		branch := exceptBranches[0]
		exceptBranches = exceptBranches[1:]
		clickhouse.Walk(branch, wrapper)
	}
}

func addBinding(scope *queryScope, name, alias string, binding Relation, start, end int) {
	scope.bindings[name] = binding
	source := Source{name: name, relation: binding, start: start, end: end}
	if alias != "" {
		scope.bindings[alias] = binding
		source.name = alias
	}
	scope.sources = append(scope.sources, source)
	if scope.sourceNames == nil {
		scope.sourceNames = map[string]int{}
	}
	scope.sourceNames[source.name]++
	if scope.sourceNames[source.name] == 2 && len(scope.duplicateSources) < querylimits.MaxDiagnostics {
		scope.duplicateSources = append(scope.duplicateSources, source)
	}
}

func (s *queryScope) hasDuplicateSource(name string) bool {
	for current := s; current != nil; current = current.parent {
		if !s.budget.lookup(len(name) + 1) {
			return true
		}
		if count, visible := current.sourceNames[name]; visible {
			return count > 1
		}
		if current.cteRoot {
			break
		}
	}
	return false
}

func (s *queryScope) visibleCTEs(position int) []*cteBinding {
	for index, cte := range s.ctes {
		if contains(cte.query, position, position) {
			return s.ctes[:index]
		}
	}
	return s.ctes
}

func resolveCTE(scope *queryScope, name string, position int) *cteBinding {
	for current := scope; current != nil; current = current.parent {
		ctes := current.visibleCTEs(position)
		for index := len(ctes) - 1; index >= 0; index-- {
			if ctes[index].name == name {
				return ctes[index]
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

func (s *queryScope) provenanceSources(name string) []Relation {
	if s == nil {
		return nil
	}
	var sources []Relation
	seen := map[string]bool{}
	for current := s; current != nil; current = current.parent {
		currentNames := map[string]bool{}
		for _, source := range current.sources {
			if !s.budget.lookup(len(name) + 1) {
				return nil
			}
			key := source.name
			if seen[key] {
				continue
			}
			currentNames[key] = true
			sources = append(sources, source.relation)
		}
		for key := range currentNames {
			seen[key] = true
		}
		if current.cteRoot {
			break
		}
	}
	return sources
}

func (s *queryScope) unqualifiedPropertyNamespace(name string) (string, bool, bool) {
	if s == nil {
		return "", false, false
	}
	key := foldedFieldName(name)
	if namespace, ok := s.propertyNamespaces[key]; ok {
		return namespace.name, namespace.ok, namespace.matched
	}
	if s.propertyNamespaces == nil {
		s.propertyNamespaces = map[string]propertyNamespace{}
	}
	resolved := propertyNamespace{}
	matches := 0
	for _, binding := range s.provenanceSources(name) {
		if _, ok := bindingField(binding, name); !ok {
			continue
		}
		matches++
		resolved.matched = true
		if matches > 1 {
			resolved = propertyNamespace{matched: true}
			break
		}
		resolved.name, resolved.ok = bindingPropertyNamespace(binding, name)
	}
	if matches != 1 {
		resolved = propertyNamespace{matched: matches > 0}
	}
	s.propertyNamespaces[key] = resolved
	return resolved.name, resolved.ok, resolved.matched
}

func normalizeHogQLTableReferences(query string) (string, map[int]string) {
	normalized := []byte(query)
	originalNames := map[int]string{}
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
		originalNames[start] = name
	}
	return string(normalized), originalNames
}

func tableReference(expr *clickhouse.TableExpr) (name, alias, implicitAlias string, start, end int, ok bool) {
	node := expr.Expr
	if aliased, isAlias := node.(*clickhouse.AliasExpr); isAlias {
		node = aliased.Expr
		if ident, isIdent := aliased.Alias.(*clickhouse.Ident); isIdent {
			alias = ident.Name
		}
	}
	identifier, isTable := node.(*clickhouse.TableIdentifier)
	if !isTable || identifier.Table == nil {
		return "", "", "", 0, 0, false
	}
	name = identifier.Table.Name
	implicitAlias = name
	if identifier.Database != nil {
		name = identifier.Database.Name + "." + name
		implicitAlias = identifier.Database.Name + "__" + identifier.Table.Name
	}
	return name, alias, implicitAlias, int(identifier.Pos()), int(identifier.End()), true
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
			addBinding(inner.parent, alias, "", Relation{name: alias, cte: derived}, int(expr.Pos()), int(expr.End()))
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
		c.fieldIndex = make(map[string]projectedField, len(fields))
		for _, field := range fields {
			if !c.budget.lookup(len(field.entry.Name) + 1) {
				return catalog.Entry{}, false
			}
			key := foldedFieldName(field.entry.Name)
			if existing, exists := c.fieldIndex[key]; !exists {
				c.fieldIndex[key] = field
			} else {
				existing.propertyNamespace = ""
				existing.ambiguous = true
				c.fieldIndex[key] = existing
			}
		}
	}
	field, ok := c.fieldIndex[foldedFieldName(name)]
	return field.entry, ok
}

func bindingPropertyNamespace(binding Relation, name string) (string, bool) {
	if binding.table != nil {
		if _, ok := binding.table.Fields.Exact(name); !ok {
			return "", false
		}
		return propertyresolver.Resolve([]string{binding.table.Name, name, "property"}, nil)
	}
	if binding.cte == nil {
		return "", false
	}
	c := binding.cte
	_ = c.projectedFields()
	if !c.fieldsDone || !c.budget.lookup(len(name)+1) {
		return "", false
	}
	if c.fieldIndex == nil {
		_, _ = bindingField(binding, name)
	}
	if c.budget.exceeded || c.budget.lookupExceeded {
		return "", false
	}
	field, ok := c.fieldIndex[foldedFieldName(name)]
	return field.propertyNamespace, ok && !field.ambiguous && field.propertyNamespace != ""
}

func bindingFields(binding Relation) []catalog.Entry {
	if binding.table != nil {
		return binding.table.Fields.Entries()
	}
	if binding.cte == nil {
		return nil
	}
	projected := binding.cte.projectedFields()
	if binding.cte.entries == nil && len(projected) > 0 {
		binding.cte.entries = make([]catalog.Entry, 0, len(projected))
		for _, field := range projected {
			binding.cte.entries = append(binding.cte.entries, field.entry)
		}
	}
	return binding.cte.entries
}

func (c *cteBinding) projectedFields() []projectedField {
	if c.fieldsDone || c.resolving || c.scope == nil || c.budget.exceeded || c.budget.lookupExceeded {
		return c.fields
	}
	c.resolving = true
	for _, item := range c.query.SelectItems {
		if item.Alias != nil {
			namespace, _ := projectedPropertyNamespace(c.scope, item.Expr, int(item.Expr.Pos()))
			c.appendField(projectedField{entry: catalog.Entry{Name: item.Alias.Name, Type: projectedType(c.scope, item.Expr)}, propertyNamespace: namespace})
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
				namespace, _ := projectedPropertyNamespace(c.scope, expr, int(expr.Pos()))
				c.appendField(projectedField{entry: catalog.Entry{Name: expr.Name, Type: projectedType(c.scope, expr)}, propertyNamespace: namespace})
			}
		case *clickhouse.Path:
			if len(expr.Fields) > 0 {
				namespace, _ := projectedPropertyNamespace(c.scope, expr, int(expr.Pos()))
				c.appendField(projectedField{entry: catalog.Entry{Name: expr.Fields[len(expr.Fields)-1].Name, Type: projectedType(c.scope, expr)}, propertyNamespace: namespace})
			}
		case *clickhouse.NestedIdentifier:
			if expr.DotIdent != nil && expr.DotIdent.Name == "*" {
				c.appendWildcardFields(c.scope, expr.Ident.Name)
			} else if expr.DotIdent != nil {
				namespace, _ := projectedPropertyNamespace(c.scope, expr, int(expr.Pos()))
				c.appendField(projectedField{entry: catalog.Entry{Name: expr.DotIdent.Name, Type: projectedType(c.scope, expr)}, propertyNamespace: namespace})
			} else {
				namespace, _ := projectedPropertyNamespace(c.scope, expr, int(expr.Pos()))
				c.appendField(projectedField{entry: catalog.Entry{Name: expr.Ident.Name, Type: projectedType(c.scope, expr)}, propertyNamespace: namespace})
			}
		default:
			c.appendField(projectedField{entry: catalog.Entry{Name: item.Expr.String()}})
		}
		if c.budget.exceeded || c.budget.lookupExceeded {
			break
		}
	}
	c.resolving = false
	c.fieldsDone = true
	return c.fields
}

func (c *cteBinding) appendField(field projectedField) {
	if c.budget.take(1) == 1 {
		c.fields = append(c.fields, field)
	}
}

func (c *cteBinding) appendFields(fields []projectedField) {
	count := c.budget.take(len(fields))
	c.fields = append(c.fields, fields[:count]...)
}

func (c *cteBinding) appendWildcardFields(scope *queryScope, qualifier string) {
	bindings := visibleBindings(scope)
	if qualifier != "" {
		c.appendBindingFields(bindings[qualifier], scope.hasDuplicateSource(qualifier))
		return
	}
	seen := map[string]bool{}
	for current := scope; current != nil; current = current.parent {
		for _, source := range current.sources {
			key := source.name
			if current != scope && seen[key] {
				continue
			}
			seen[key] = true
			c.appendBindingFields(source.relation, false)
			if c.budget.exceeded {
				return
			}
		}
		if current.cteRoot {
			break
		}
	}
}

func (c *cteBinding) appendBindingFields(binding Relation, suppressProvenance bool) {
	if binding.table != nil {
		fields := binding.table.Fields.Entries()
		count := c.budget.take(len(fields))
		for _, field := range fields[:count] {
			namespace, _ := bindingPropertyNamespace(binding, field.Name)
			if suppressProvenance {
				namespace = ""
			}
			c.fields = append(c.fields, projectedField{entry: field, propertyNamespace: namespace})
		}
		return
	}
	if binding.cte != nil {
		fields := binding.cte.projectedFields()
		if !suppressProvenance {
			c.appendFields(fields)
			return
		}
		count := c.budget.take(len(fields))
		for _, field := range fields[:count] {
			field.propertyNamespace = ""
			c.fields = append(c.fields, field)
		}
	}
}

func projectedPropertyNamespace(scope *queryScope, expr clickhouse.Expr, position int) (string, bool) {
	bindings := visibleBindings(scope)
	switch typed := expr.(type) {
	case *clickhouse.Ident:
		if IsBooleanLiteral(typed) {
			return "", false
		}
		if alias, ok := (Bindings{scope: scope, position: position}).selectAlias(typed.Name); ok {
			return alias.propertyNamespace, alias.propertyNamespace != ""
		}
		namespace, ok, _ := scope.unqualifiedPropertyNamespace(typed.Name)
		return namespace, ok
	case *clickhouse.Path:
		if len(typed.Fields) == 2 {
			if scope.hasDuplicateSource(typed.Fields[0].Name) {
				return "", false
			}
			if binding, ok := bindings[typed.Fields[0].Name]; ok {
				return bindingPropertyNamespace(binding, typed.Fields[1].Name)
			}
		}
	case *clickhouse.NestedIdentifier:
		if typed.DotIdent != nil {
			if scope.hasDuplicateSource(typed.Ident.Name) {
				return "", false
			}
			if binding, ok := bindings[typed.Ident.Name]; ok {
				return bindingPropertyNamespace(binding, typed.DotIdent.Name)
			}
		}
	}
	return "", false
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
		if IsBooleanLiteral(typed) {
			return "boolean"
		}
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
			if binding, ok := bindings[typed.Fields[0].Name]; ok {
				if field, exists := bindingField(binding, typed.Fields[1].Name); exists {
					return field.Type
				}
			}
		}
	case *clickhouse.NestedIdentifier:
		if typed.DotIdent != nil {
			if binding, ok := bindings[typed.Ident.Name]; ok {
				if field, exists := bindingField(binding, typed.DotIdent.Name); exists {
					return field.Type
				}
			}
		}
	}
	return ""
}
