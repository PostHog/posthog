package analysis

import (
	"iter"
	"slices"
	"sort"
	"strings"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

// A Document belongs to one request. Lazy projections share its budget and must not run concurrently.
type Document struct {
	statements []*Statement
	budget     projectionBudget
}

type Statement struct {
	expr               clickhouse.Expr
	schema             *catalog.PreparedCatalog
	originalTableNames map[int]string
	budget             *projectionBudget
	scopes             []*queryScope
	tables             []TableReference
	resolvedTables     []TableReference
	analyzed           bool
}

type TableReference struct {
	Name       string
	Canonical  string
	CTE        bool
	Start, End int
	Known      bool
}

type Bindings struct {
	relations map[string]Relation
	scope     *queryScope
	position  int
}

func Analyze(schema *catalog.PreparedCatalog, query string) (*Document, error) {
	if err := querylimits.Validate(query); err != nil {
		return nil, err
	}
	parserQuery, originalTableNames := normalizeHogQLTableReferences(query)
	statements, err := clickhouse.NewParser(parserQuery).ParseStmts()
	if err != nil {
		return nil, err
	}
	document := &Document{budget: projectionBudget{
		remaining: querylimits.MaxCTEProjectedFields, lookupRemaining: querylimits.MaxFieldLookupWork,
	}}
	for _, expr := range statements {
		document.statements = append(document.statements, &Statement{
			expr: expr, schema: schema, originalTableNames: originalTableNames, budget: &document.budget,
		})
	}
	return document, nil
}

func (d *Document) Statements() iter.Seq[*Statement] {
	return func(yield func(*Statement) bool) {
		for _, statement := range d.statements {
			// Validation stops between statements when projection work exhausts the request budget.
			statement.analyze()
			if !yield(statement) {
				return
			}
		}
	}
}

func (d *Document) LimitError() error {
	if d.budget.exceeded {
		return querylimits.ErrCTEProjectionTooLarge
	}
	if d.budget.lookupExceeded {
		return querylimits.ErrFieldLookupTooLarge
	}
	if d.budget.relationExceeded {
		return querylimits.ErrRelationTraversalTooDeep
	}
	return nil
}

func (s *Statement) analyze() {
	if s.analyzed {
		return
	}
	s.analyzed = true
	s.scopes = queryScopes(s.expr, s.budget)
	bindTables := func(node clickhouse.Expr) bool {
		expr, ok := node.(*clickhouse.TableExpr)
		if !ok {
			return true
		}
		if bindSubquery(expr, s.scopes, s.budget) {
			return true
		}
		name, alias, implicitAlias, start, end, ok := tableReference(expr)
		if !ok {
			return true
		}
		scope := innermostScope(s.scopes, start, end)
		if scope == nil {
			return true
		}
		if original, exists := s.originalTableNames[start]; exists {
			name = original
			implicitAlias = strings.ReplaceAll(original, ".", "__")
		}
		if cte := resolveCTE(scope, name, start); cte != nil {
			addBinding(scope, name, alias, Relation{name: cte.name, cte: cte}, start, end)
			s.resolvedTables = append(s.resolvedTables, TableReference{Name: name, Canonical: cte.name, CTE: true, Start: start, End: end, Known: true})
			return true
		}
		table, exists := s.schema.Table(name)
		s.tables = append(s.tables, TableReference{Name: name, Start: start, End: end, Known: exists})
		if exists {
			s.resolvedTables = append(s.resolvedTables, TableReference{Name: name, Canonical: table.Name, Start: start, End: end, Known: true})
			if alias == "" && implicitAlias != name {
				// HogQL registers multi-part table paths under a double-underscore alias.
				alias = implicitAlias
			}
			addBinding(scope, name, alias, Relation{name: name, table: table}, start, end)
		}
		return true
	}
	walkIncludingExcept(s.expr, bindTables)
}

// Walk borrows parser nodes for validation; callers must not mutate them or retain them across requests.
func (s *Statement) Walk(visit func(clickhouse.Expr) bool) {
	walkIncludingExcept(s.expr, visit)
}

func (s *Statement) Tables() iter.Seq[TableReference] {
	return slices.Values(s.tables)
}

func (s *Statement) ResolvedTables() iter.Seq[TableReference] {
	return slices.Values(s.resolvedTables)
}

func (s *Statement) DuplicateSources() iter.Seq[Source] {
	return func(yield func(Source) bool) {
		for _, scope := range s.scopes {
			for _, source := range scope.duplicateSources {
				if !yield(source) {
					return
				}
			}
		}
	}
}

func (s *Statement) ContainsPosition(position int) bool {
	if int(s.expr.Pos()) <= position && position <= int(s.expr.End()) {
		return true
	}
	for _, scope := range s.scopes {
		if contains(scope.query, position, position) {
			return true
		}
	}
	return false
}

func (s *Statement) BindingsAt(start, end int) Bindings {
	scope := innermostScope(s.scopes, start, end)
	if scope == nil {
		return Bindings{}
	}
	if scope.visible == nil {
		scope.visible = visibleBindings(scope)
	}
	return Bindings{relations: scope.visible, scope: scope, position: start}
}

// Qualified completion can refer to a visible CTE before the user has typed FROM.
func (s *Statement) RelationAt(name string, position int) (Relation, bool) {
	if relation, ok := s.BindingsAt(position, position).Relation(name); ok {
		return relation, true
	}
	if cte := resolveCTE(innermostScope(s.scopes, position, position), name, position); cte != nil {
		return Relation{name: cte.name, cte: cte}, true
	}
	return Relation{}, false
}

func (b Bindings) Len() int {
	return len(b.relations)
}

func (b Bindings) CTENames(prefix string) iter.Seq[catalog.Entry] {
	return func(yield func(catalog.Entry) bool) {
		seen := map[string]bool{}
		prefix = foldedFieldName(prefix)
		for scope := b.scope; scope != nil; scope = scope.parent {
			ctes := scope.visibleCTEs(b.position)
			for index := len(ctes) - 1; index >= 0; index-- {
				name := ctes[index].name
				if !scope.budget.lookup(len(name) + 1) {
					return
				}
				if seen[name] {
					continue
				}
				seen[name] = true
				if strings.HasPrefix(foldedFieldName(name), prefix) && !yield(catalog.Entry{Name: name, Type: "CTE"}) {
					return
				}
			}
		}
	}
}

func (b Bindings) Relation(name string) (Relation, bool) {
	relation, ok := b.relations[name]
	return relation, ok
}

func (b Bindings) UnambiguousRelation(name string) (Relation, bool) {
	relation, ok := b.Relation(name)
	return relation, ok && b.scope != nil && !b.scope.hasDuplicateSource(name)
}

func (b Bindings) ResolvedField(name string) (catalog.Entry, bool) {
	if b.scope == nil {
		return catalog.Entry{}, false
	}
	var found catalog.Entry
	matches := 0
	for source := range b.sources() {
		if b.scope.hasDuplicateSource(source.name) {
			return catalog.Entry{}, false
		}
		if _, ok := source.relation.Field(name); ok {
			matches++
			field, resolved := source.relation.ResolvedField(name)
			if !resolved {
				return catalog.Entry{}, false
			}
			found = field
		}
	}
	return found, matches == 1 && !b.scope.budget.lookupExceeded
}

func (b Bindings) All() iter.Seq2[string, Relation] {
	return func(yield func(string, Relation) bool) {
		for name, relation := range b.relations {
			if !yield(name, relation) {
				return
			}
		}
	}
}

func (b Bindings) UniqueRelations() iter.Seq[Relation] {
	if b.scope == nil {
		return slices.Values([]Relation(nil))
	}
	return slices.Values(b.scope.uniqueBindings())
}

func (b Bindings) PropertyNamespace(parts []string) (string, bool) {
	if len(parts) < 2 {
		return "", false
	}
	if target := b.Traversal(parts[:len(parts)-1]); target.Explicit {
		return target.PropertyNamespace, target.Valid && target.PropertyNamespace != "" && !target.HasProperty
	}
	if len(parts) > 2 && b.scope.hasDuplicateSource(parts[0]) {
		return "", false
	}
	if len(parts) >= 2 {
		ownerParts := parts[:len(parts)-1]
		if len(ownerParts) == 1 {
			if alias, ok := b.selectAlias(ownerParts[0]); ok {
				return alias.propertyNamespace, alias.propertyNamespace != ""
			}
			_, qualified := b.Relation(ownerParts[0])
			if !qualified && resolveCTE(b.scope, ownerParts[0], b.position) == nil {
				namespace, ok, matched := b.scope.unqualifiedPropertyNamespace(ownerParts[0])
				if ok {
					return namespace, true
				}
				if matched {
					return "", false
				}
			}
		}
		if len(ownerParts) == 2 {
			if relation, ok := b.Relation(ownerParts[0]); ok {
				return bindingPropertyNamespace(relation, ownerParts[1])
			}
		}
	}
	if len(parts) >= 2 {
		_, bound := b.Relation(parts[0])
		if _, shadowed := b.SelectAlias(parts[0]); shadowed {
			if len(parts) == 2 || !bound {
				return "", false
			}
		}
	}
	if len(parts) > 2 {
		if _, bound := b.Relation(parts[0]); !bound {
			if resolveCTE(b.scope, parts[0], b.position) != nil || len(parts) > 3 {
				return "", false
			}
		}
	}
	names := make(map[string]string, len(b.relations))
	for name, relation := range b.relations {
		if relation.cte != nil {
			if len(parts) > 2 && parts[0] == name {
				return "", false
			}
			if len(parts) == 2 {
				if _, hasProperties := relation.Field("properties"); hasProperties || relation.cte.budget.exceeded || relation.cte.budget.lookupExceeded {
					return "", false
				}
			}
			continue
		}
		names[name] = relation.table.Name
	}
	return propertyresolver.Resolve(parts, names)
}

type TraversalTarget struct {
	Fields            *catalog.PreparedFields
	PropertyNamespace string
	Explicit          bool
	Valid             bool
	Failed            bool
	FailureAt         int
	HasProperty       bool
	PropertyAt        int
}

func (b Bindings) Traversal(parts []string) TraversalTarget {
	if len(parts) == 0 || b.scope == nil {
		return TraversalTarget{}
	}
	var fields *catalog.PreparedFields
	var relationView *catalog.PreparedRelation
	index := 0
	if relation, ok := b.Relation(parts[0]); ok {
		if b.scope.hasDuplicateSource(parts[0]) {
			return TraversalTarget{Explicit: true}
		}
		if relation.table == nil {
			return TraversalTarget{}
		}
		fields = &relation.table.Fields
		index = 1
	} else {
		matches := 0
		annotated := 0
		for source := range b.sources() {
			if _, ok := source.relation.Field(parts[0]); !ok {
				continue
			}
			matches++
			if b.scope.hasDuplicateSource(source.name) {
				return TraversalTarget{Explicit: true}
			}
			if source.relation.table != nil {
				if _, ok := source.relation.table.Fields.Traversal(parts[0]); ok {
					fields = &source.relation.table.Fields
					annotated++
				}
			}
		}
		if annotated == 0 {
			return TraversalTarget{}
		}
		if alias, ok := b.selectAlias(parts[0]); ok {
			if len(parts) == 1 && alias.propertyNamespace != "" {
				return TraversalTarget{PropertyNamespace: alias.propertyNamespace, Explicit: true, Valid: true}
			}
			return TraversalTarget{Explicit: true}
		}
		if matches != 1 || annotated != 1 {
			return TraversalTarget{Explicit: true}
		}
	}
	hops := 0
	explicit := false
	for ; index < len(parts); index++ {
		if !b.scope.budget.lookup(len(parts[index]) + 1) {
			return TraversalTarget{Explicit: explicit}
		}
		entry, ok := fields.Exact(parts[index])
		if !ok {
			return TraversalTarget{Fields: fields, Explicit: explicit, Failed: explicit, FailureAt: index}
		}
		var traversal catalog.FieldTraversal
		if relationView != nil {
			traversal, ok = relationView.Traversal(parts[index])
		} else {
			traversal, ok = fields.Traversal(parts[index])
		}
		if !ok {
			if explicit && strings.EqualFold(entry.Type, "JSON") {
				return TraversalTarget{Explicit: true}
			}
			return TraversalTarget{Fields: fields, Explicit: explicit, Failed: explicit, FailureAt: index + 1}
		}
		explicit = true
		if traversal.PropertyNamespace != "" {
			if index != len(parts)-1 {
				return TraversalTarget{
					PropertyNamespace: traversal.PropertyNamespace,
					Explicit:          true,
					Valid:             true,
					HasProperty:       true,
					PropertyAt:        index + 1,
				}
			}
			return TraversalTarget{PropertyNamespace: traversal.PropertyNamespace, Explicit: true, Valid: true}
		}
		hops++
		if hops > querylimits.MaxRelationTraversalHops {
			b.scope.budget.relationExceeded = true
			return TraversalTarget{Explicit: true}
		}
		if traversal.Relation == nil {
			return TraversalTarget{Explicit: true}
		}
		relationView = traversal.Relation
		fields = traversal.Relation.Fields
	}
	return TraversalTarget{Fields: fields, Explicit: explicit, Valid: fields != nil}
}

func (r Relation) Name() string {
	return r.name
}

func (r Relation) Field(name string) (catalog.Entry, bool) {
	return bindingField(r, name)
}

func (r Relation) ResolvedField(name string) (catalog.Entry, bool) {
	field, ok := bindingField(r, name)
	if !ok || r.cte == nil {
		return field, ok
	}
	projected, exists := r.cte.fieldIndex[foldedFieldName(name)]
	return field, exists && !projected.ambiguous
}

// Fields yields values without copying catalog indexes or exposing their backing slices.
func (r Relation) Fields() iter.Seq[catalog.Entry] {
	return slices.Values(bindingFields(r))
}

// Physical prefixes borrow the catalog index; derived projections have a request-wide size bound.
func (r Relation) Prefix(prefix string) iter.Seq[catalog.Entry] {
	if r.table != nil {
		return slices.Values(r.table.Fields.Prefix(prefix))
	}
	var fields []catalog.Entry
	seen := map[string]bool{}
	for field := range r.Fields() {
		name := strings.ToLower(field.Name)
		if strings.HasPrefix(name, prefix) && !seen[name] {
			fields = append(fields, field)
			seen[name] = true
		}
	}
	sort.Slice(fields, func(i, j int) bool { return strings.ToLower(fields[i].Name) < strings.ToLower(fields[j].Name) })
	return slices.Values(fields)
}
