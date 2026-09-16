package analysis

import (
	"iter"
	"slices"
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
	document := &Document{budget: projectionBudget{remaining: querylimits.MaxCTEProjectedFields}}
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

func (d *Document) ProjectionLimitExceeded() bool {
	return d.budget.exceeded
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
		name, alias, start, end, ok := tableReference(expr)
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
		}
		table, exists := s.schema.Table(name)
		s.tables = append(s.tables, TableReference{Name: name, Start: start, End: end, Known: exists})
		if exists {
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

func (s *Statement) BindingsAt(start, end int) Bindings {
	scope := innermostScope(s.scopes, start, end)
	if scope == nil {
		return Bindings{}
	}
	if scope.visible == nil {
		scope.visible = visibleBindings(scope)
	}
	return Bindings{relations: scope.visible}
}

func (b Bindings) Len() int {
	return len(b.relations)
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

func (b Bindings) PropertyNamespace(parts []string) (string, bool) {
	names := make(map[string]string, len(b.relations))
	for name, relation := range b.relations {
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
