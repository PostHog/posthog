package analysis

import (
	"strings"
	"unicode"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/hogqlparser"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/propertyresolver"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

type Relation struct {
	name  string
	table *catalog.PreparedTable
	cte   *cteBinding
}

type cteBinding struct {
	name string
	// query is the SELECT whose columns the CTE projects. For a set query that is the first branch, because the
	// first branch names the columns. body spans the whole definition, which a CTE cannot reference.
	query      *hogqlparser.Node
	body       *hogqlparser.Node
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
	remaining        int
	exceeded         bool
	lookupRemaining  int
	lookupExceeded   bool
	relationExceeded bool
}

type queryScope struct {
	query              *hogqlparser.Node
	source             string
	parent             *queryScope
	bindings           map[string]Relation
	sources            []Source
	visible            map[string]Relation
	unique             []Relation
	budget             *projectionBudget
	ctes               []*cteBinding
	cteRoot            bool
	aliases            map[string]selectAlias
	clauseSpans        map[string][2]int
	propertyNamespaces map[string]propertyNamespace
	sourceNames        map[string]int
	duplicateSources   []Source
}

type propertyNamespace struct {
	name    string
	ok      bool
	matched bool
}

func queryScopes(statement *hogqlparser.Node, source string, budget *projectionBudget) ([]*queryScope, map[*hogqlparser.Node]*queryScope) {
	var scopes []*queryScope
	byQuery := map[*hogqlparser.Node]*queryScope{}
	statement.Walk(func(node *hogqlparser.Node) bool {
		if node.Is("SelectQuery") && node.Start >= 0 {
			scope := &queryScope{query: node, source: source, bindings: map[string]Relation{}, budget: budget}
			scopes = append(scopes, scope)
			byQuery[node] = scope
		}
		return true
	})
	for _, scope := range scopes {
		for _, candidate := range scopes {
			if scope == candidate || candidate.query.Span() <= scope.query.Span() || !candidate.query.Contains(scope.query.Start, scope.query.End) {
				continue
			}
			if scope.parent == nil || candidate.query.Span() < scope.parent.query.Span() {
				scope.parent = candidate
			}
		}
	}
	for _, scope := range scopes {
		for _, statement := range scope.query.Children("ctes") {
			if statement.Text("cte_type") != "subquery" {
				continue
			}
			body := statement.Child("expr")
			branches := selectBranches(body)
			if len(branches) == 0 {
				continue
			}
			cte := &cteBinding{name: statement.Text("name"), query: branches[0], body: body, scope: byQuery[branches[0]], budget: budget}
			for _, branch := range branches {
				if branchScope := byQuery[branch]; branchScope != nil {
					branchScope.cteRoot = true
				}
			}
			scope.ctes = append(scope.ctes, cte)
		}
	}
	statement.Walk(func(node *hogqlparser.Node) bool {
		if !node.Is("SelectSetQuery") {
			return true
		}
		branches := selectBranches(node)
		if len(branches) < 2 || byQuery[branches[0]] == nil {
			return true
		}
		ctes := byQuery[branches[0]].ctes
		for _, branch := range branches[1:] {
			if scope := byQuery[branch]; scope != nil {
				scope.ctes = append(append([]*cteBinding{}, ctes...), scope.ctes...)
			}
		}
		return true
	})
	return scopes, byQuery
}

func selectBranches(node *hogqlparser.Node) []*hogqlparser.Node {
	switch {
	case node.Is("SelectQuery"):
		return []*hogqlparser.Node{node}
	case node.Is("SelectSetQuery"):
		branches := selectBranches(node.Child("initial_select_query"))
		for _, subsequent := range node.Children("subsequent_select_queries") {
			branches = append(branches, selectBranches(subsequent.Child("select_query"))...)
		}
		return branches
	}
	return nil
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
		if cte.body.Contains(position, position) {
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
		if scope.query.Contains(start, end) && (found == nil || scope.query.Span() < found.query.Span()) {
			found = scope
		}
	}
	return found
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

// tableReference reads a JoinExpr whose table is a name. A table function such as numbers(10) has no catalog
// entry and no columns to check, so it is not a reference.
func tableReference(join *hogqlparser.Node) (name, alias, implicitAlias string, start, end int, ok bool) {
	table := join.Child("table")
	if !table.Is("Field") || join.Has("table_args") || table.Start < 0 {
		return "", "", "", 0, 0, false
	}
	chain := table.Chain()
	if len(chain) == 0 {
		return "", "", "", 0, 0, false
	}
	// HogQL registers multi-part table paths under a double-underscore alias.
	return strings.Join(chain, "."), join.Text("alias"), strings.Join(chain, "__"), table.Start, table.End, true
}

func bindSubquery(join *hogqlparser.Node, byQuery map[*hogqlparser.Node]*queryScope, budget *projectionBudget) bool {
	table := join.Child("table")
	branches := selectBranches(table)
	if len(branches) == 0 {
		return false
	}
	first := byQuery[branches[0]]
	if first == nil || first.parent == nil {
		return true
	}
	// FROM subqueries do not inherit the containing query's table bindings.
	for _, branch := range branches {
		if scope := byQuery[branch]; scope != nil {
			scope.cteRoot = true
		}
	}
	if alias := join.Text("alias"); alias != "" {
		derived := &cteBinding{name: alias, query: branches[0], body: table, scope: first, budget: budget}
		addBinding(first.parent, alias, "", Relation{name: alias, cte: derived}, join.Start, join.End)
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
		if traversal, ok := binding.table.Fields.Traversal(name); ok {
			return traversal.PropertyNamespace, traversal.PropertyNamespace != ""
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
	for _, item := range c.query.Children("select") {
		if item.Is("Alias") {
			expr := item.Child("expr")
			namespace, _ := projectedPropertyNamespace(c.scope, expr, expr.Start)
			c.appendField(projectedField{entry: catalog.Entry{Name: item.Text("alias"), Type: projectedType(c.scope, expr)}, propertyNamespace: namespace})
			if c.budget.exceeded || c.budget.lookupExceeded {
				break
			}
			continue
		}
		chain := item.Chain()
		switch {
		case !item.Is("Field") || len(chain) == 0:
			c.appendField(projectedField{entry: catalog.Entry{Name: item.Source(c.scope.source)}})
		case len(chain) == 1 && chain[0] == "*":
			c.appendWildcardFields(c.scope, "")
		case len(chain) == 2 && chain[1] == "*":
			c.appendWildcardFields(c.scope, chain[0])
		default:
			namespace, _ := projectedPropertyNamespace(c.scope, item, item.Start)
			c.appendField(projectedField{entry: catalog.Entry{Name: chain[len(chain)-1], Type: projectedType(c.scope, item)}, propertyNamespace: namespace})
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

func projectedPropertyNamespace(scope *queryScope, expr *hogqlparser.Node, position int) (string, bool) {
	if !expr.Is("Field") {
		return "", false
	}
	chain := expr.Chain()
	switch len(chain) {
	case 1:
		if alias, ok := (Bindings{scope: scope, position: position}).selectAlias(chain[0]); ok {
			return alias.propertyNamespace, alias.propertyNamespace != ""
		}
		namespace, ok, _ := scope.unqualifiedPropertyNamespace(chain[0])
		return namespace, ok
	case 2:
		if scope.hasDuplicateSource(chain[0]) {
			return "", false
		}
		if binding, ok := visibleBindings(scope)[chain[0]]; ok {
			return bindingPropertyNamespace(binding, chain[1])
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

func projectedType(scope *queryScope, expr *hogqlparser.Node) string {
	if expr.Is("Constant") {
		if _, ok := expr.Bool("value"); ok {
			return "boolean"
		}
	}
	if !expr.Is("Field") {
		return ""
	}
	chain := expr.Chain()
	if len(chain) == 1 {
		if field, ok := (Bindings{scope: scope, position: expr.Start}).SelectAlias(chain[0]); ok {
			return field.Type
		}
		for _, binding := range scope.uniqueBindings() {
			if !scope.budget.lookup(len(chain[0]) + 1) {
				return ""
			}
			if field, ok := bindingField(binding, chain[0]); ok {
				return field.Type
			}
		}
		return ""
	}
	if len(chain) >= 2 {
		if binding, ok := visibleBindings(scope)[chain[0]]; ok {
			if field, exists := bindingField(binding, chain[1]); exists {
				return field.Type
			}
		}
	}
	return ""
}
