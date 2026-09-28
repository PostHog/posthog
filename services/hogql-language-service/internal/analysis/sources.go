package analysis

import (
	"iter"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

type Source struct {
	name     string
	relation Relation
	start    int
	end      int
}

func (s Source) Qualifier() string {
	return s.name
}

func (s Source) Start() int { return s.start }

func (s Source) End() int { return s.end }

func (b Bindings) sources() iter.Seq[Source] {
	return func(yield func(Source) bool) {
		seen := map[string]bool{}
		for scope := b.scope; scope != nil; scope = scope.parent {
			for index := len(scope.sources) - 1; index >= 0; index-- {
				source := scope.sources[index]
				if !scope.budget.lookup(len(source.name) + 1) {
					return
				}
				name := source.name
				if seen[name] {
					continue
				}
				seen[name] = true
				if relation, ok := b.Relation(name); ok && relation == source.relation && !yield(source) {
					return
				}
			}
			if scope.cteRoot {
				break
			}
		}
	}
}

func (b Bindings) Fields(prefix string) iter.Seq2[Source, catalog.Entry] {
	return func(yield func(Source, catalog.Entry) bool) {
		// Self-joins share field indexes but need a suggestion for each visible source.
		prefixes := map[Relation]iter.Seq[catalog.Entry]{}
		for source := range b.sources() {
			fields, ok := prefixes[source.relation]
			if !ok {
				fields = source.relation.Prefix(prefix)
				prefixes[source.relation] = fields
			}
			for field := range fields {
				if !b.scope.budget.lookup(len(field.Name)+len(source.name)+1) || !yield(source, field) {
					return
				}
			}
		}
	}
}
