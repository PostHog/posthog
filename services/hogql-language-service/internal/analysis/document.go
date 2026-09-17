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
	originalTableNames map[string]string
	budget             *projectionBudget
	scopes             []*queryScope
	tables             []TableReference
	analyzed           bool
}

type TableReference struct {
	Name       string
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
	return nil
}

func (s *Statement) analyze() {
	if s.analyzed {
		return
	}
	s.analyzed = true
	s.scopes = queryScopes(s.expr, s.budget)
	clickhouse.Walk(s.expr, func(node clickhouse.Expr) bool {
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
		if cte := resolveCTE(scope, name, start); cte != nil {
			addBinding(scope, name, alias, Relation{name: cte.name, cte: cte})
			return true
		}
		if original, exists := s.originalTableNames[strings.ToLower(name)]; exists {
			name = original
			implicitAlias = strings.ReplaceAll(original, ".", "__")
		}
		table, exists := s.schema.Table(name)
		s.tables = append(s.tables, TableReference{Name: name, Start: start, End: end, Known: exists})
		if exists {
			if alias == "" && implicitAlias != name {
				// HogQL registers multi-part table paths under a double-underscore alias.
				alias = implicitAlias
			}
			addBinding(scope, name, alias, Relation{name: name, table: table})
		}
		return true
	})
}

// Walk borrows parser nodes for validation; callers must not mutate them or retain them across requests.
func (s *Statement) Walk(visit func(clickhouse.Expr) bool) {
	clickhouse.Walk(s.expr, visit)
}

func (s *Statement) Tables() iter.Seq[TableReference] {
	return slices.Values(s.tables)
}

func (s *Statement) ContainsPosition(position int) bool {
	return int(s.expr.Pos()) <= position && position <= int(s.expr.End())
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
				folded := foldedFieldName(name)
				if seen[folded] {
					continue
				}
				seen[folded] = true
				if strings.HasPrefix(folded, prefix) && !yield(catalog.Entry{Name: name, Type: "CTE"}) {
					return
				}
			}
		}
	}
}

func (b Bindings) Relation(name string) (Relation, bool) {
	relation, ok := b.relations[strings.ToLower(name)]
	return relation, ok
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
		if _, bound := b.Relation(parts[0]); !bound && resolveCTE(b.scope, parts[0], b.position) != nil {
			return "", false
		}
	}
	names := make(map[string]string, len(b.relations))
	for name, relation := range b.relations {
		if relation.cte != nil {
			if len(parts) > 2 && strings.EqualFold(parts[0], name) {
				return "", false
			}
			if len(parts) == 2 {
				if _, hasProperties := relation.Field("properties"); hasProperties || relation.cte.budget.exceeded || relation.cte.budget.lookupExceeded {
					return "", false
				}
			}
			continue
		}
		names[name] = relation.name
	}
	return propertyresolver.Resolve(parts, names)
}

func (r Relation) Name() string {
	return r.name
}

func (r Relation) Field(name string) (catalog.Entry, bool) {
	return bindingField(r, name)
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
