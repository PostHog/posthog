package analysis

import (
	"iter"
	"strings"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

type selectAlias struct {
	field             catalog.Entry
	propertyNamespace string
	end               int
	ambiguousAt       int
}

func (s *queryScope) selectAliases() map[string]selectAlias {
	if s.aliases != nil {
		return s.aliases
	}
	s.aliases = map[string]selectAlias{}
	for _, item := range s.query.SelectItems {
		if !s.budget.lookup(1) {
			break
		}
		if item.Alias == nil {
			continue
		}
		name := item.Alias.Name
		if !s.budget.lookup(len(name) + 1) {
			break
		}
		if existing, exists := s.aliases[name]; exists {
			if existing.ambiguousAt == 0 {
				existing.ambiguousAt = int(item.End())
				s.aliases[name] = existing
			}
			continue
		}
		// HogQL resolves each expression before registering its alias (Resolver.visit_alias).
		field := catalog.Entry{Name: name, Type: projectedType(s, item.Expr)}
		namespace, _ := projectedPropertyNamespace(s, item.Expr, int(item.Expr.Pos()))
		s.aliases[name] = selectAlias{field: field, propertyNamespace: namespace, end: int(item.End())}
	}
	return s.aliases
}

func (b Bindings) aliasCutoff() int {
	if b.scope == nil {
		return -1
	}
	q := b.scope.query
	items := q.SelectItems
	if len(items) > 0 && int(items[0].Pos()) <= b.position && b.position <= int(items[len(items)-1].End()) {
		return b.position
	}
	containsPosition := func(expr clickhouse.Expr) bool {
		return int(expr.Pos()) <= b.position && b.position <= int(expr.End())
	}
	// Resolver.visit_select_query resolves FROM/JOIN before SELECT, then these clauses.
	if q.Where != nil && containsPosition(q.Where) ||
		q.Prewhere != nil && containsPosition(q.Prewhere) ||
		q.GroupBy != nil && containsPosition(q.GroupBy) ||
		q.Having != nil && containsPosition(q.Having) ||
		q.OrderBy != nil && containsPosition(q.OrderBy) ||
		q.Window != nil && containsPosition(q.Window) ||
		q.LimitBy != nil && containsPosition(q.LimitBy) ||
		q.Limit != nil && containsPosition(q.Limit) {
		return int(q.End())
	}
	return -1
}

func (b Bindings) SelectAlias(name string) (catalog.Entry, bool) {
	alias, ok := b.selectAlias(name)
	return alias.field, ok
}

func (b Bindings) ResolvedSelectAlias(name string) (catalog.Entry, bool) {
	alias, ok := b.selectAlias(name)
	return alias.field, ok && (alias.ambiguousAt == 0 || alias.ambiguousAt > b.aliasCutoff())
}

func (b Bindings) selectAlias(name string) (selectAlias, bool) {
	cutoff := b.aliasCutoff()
	if cutoff < 0 || !b.scope.budget.lookup(len(name)+1) {
		return selectAlias{}, false
	}
	alias, ok := b.scope.selectAliases()[name]
	if ok && alias.ambiguousAt != 0 && alias.ambiguousAt <= cutoff {
		alias.propertyNamespace = ""
	}
	return alias, ok && alias.end <= cutoff
}

func (b Bindings) SelectAliases(prefix string) iter.Seq[catalog.Entry] {
	return func(yield func(catalog.Entry) bool) {
		cutoff := b.aliasCutoff()
		if cutoff < 0 {
			return
		}
		for _, alias := range b.scope.selectAliases() {
			if !b.scope.budget.lookup(len(alias.field.Name) + 1) {
				return
			}
			if alias.end <= cutoff && strings.HasPrefix(strings.ToLower(alias.field.Name), prefix) && !yield(alias.field) {
				return
			}
		}
	}
}
