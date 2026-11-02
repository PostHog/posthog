package analysis

import (
	"iter"
	"strings"

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
	for _, item := range s.query.Children("select") {
		if !s.budget.lookup(1) {
			break
		}
		if !item.Is("Alias") {
			continue
		}
		name := item.Text("alias")
		if !s.budget.lookup(len(name) + 1) {
			break
		}
		if existing, exists := s.aliases[name]; exists {
			if existing.ambiguousAt == 0 {
				existing.ambiguousAt = item.End
				s.aliases[name] = existing
			}
			continue
		}
		// HogQL resolves each expression before registering its alias (Resolver.visit_alias).
		expr := item.Child("expr")
		field := catalog.Entry{Name: name, Type: projectedType(s, expr)}
		namespace, _ := projectedPropertyNamespace(s, expr, expr.Start)
		s.aliases[name] = selectAlias{field: field, propertyNamespace: namespace, end: item.End}
	}
	return s.aliases
}

// Clauses that the resolver visits after SELECT, so their expressions can refer to SELECT aliases.
var clausesAfterSelect = []string{"where", "prewhere", "group_by", "having", "order_by", "window_exprs", "limit_by", "limit", "offset", "qualify"}

func (b Bindings) aliasCutoff() int {
	if b.scope == nil {
		return -1
	}
	s := b.scope
	if s.clauseSpans == nil {
		s.clauseSpans = make(map[string][2]int)
		for _, clause := range append([]string{"select"}, clausesAfterSelect...) {
			start, end := -1, -1
			for _, node := range s.query.Children(clause) {
				if node.Start < 0 {
					continue
				}
				if start < 0 || node.Start < start {
					start = node.Start
				}
				end = max(end, node.End)
			}
			s.clauseSpans[clause] = [2]int{start, end}
		}
	}
	contains := func(clause string) bool {
		span := s.clauseSpans[clause]
		return span[0] >= 0 && span[0] <= b.position && b.position <= span[1]
	}
	if contains("select") {
		return b.position
	}
	for _, clause := range clausesAfterSelect {
		if contains(clause) {
			return s.query.End
		}
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
