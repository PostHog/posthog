package analysis

import (
	"iter"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/hogqlparser"
)

// ColumnField is a Field that refers to a column, a property, or a SELECT alias.
type ColumnField struct {
	Node  *hogqlparser.Node
	Parts []hogqlparser.FieldPart
}

// ColumnFields yields column references in source order. It skips Fields that name something other than a
// column: the table of a JoinExpr, the name inside a {placeholder}, a lambda argument, an ARRAY JOIN alias, and a
// scalar CTE such as `WITH 1 AS one`. The resolver binds the last three before it looks at table columns.
func (s *Statement) ColumnFields() iter.Seq[ColumnField] {
	return func(yield func(ColumnField) bool) {
		localNames := s.localNames()
		var visit func(node *hogqlparser.Node, lambdaArguments map[string]bool) bool
		visit = func(node *hogqlparser.Node, lambdaArguments map[string]bool) bool {
			switch {
			case node.Is("Placeholder"):
				return true
			case node.Is("Lambda"):
				scoped := make(map[string]bool, len(lambdaArguments)+1)
				for name := range lambdaArguments {
					scoped[name] = true
				}
				for _, argument := range node.Strings("args") {
					scoped[argument] = true
				}
				lambdaArguments = scoped
			case node.Is("JoinExpr"):
				for _, child := range node.Nodes() {
					if child == node.Child("table") && child.Is("Field") {
						continue
					}
					if !visit(child, lambdaArguments) {
						return false
					}
				}
				return true
			case node.Is("Field"):
				chain := node.Chain()
				if len(chain) == 0 || lambdaArguments[chain[0]] || localNames[chain[0]] {
					return true
				}
				return yield(ColumnField{Node: node, Parts: node.FieldParts(s.query)})
			}
			for _, child := range node.Nodes() {
				if !visit(child, lambdaArguments) {
					return false
				}
			}
			return true
		}
		visit(s.expr, nil)
	}
}

// localNames collects ARRAY JOIN aliases and scalar CTE names across the statement. Treating them as visible
// everywhere can hide a diagnostic in another scope, but it never reports a valid query as invalid.
func (s *Statement) localNames() map[string]bool {
	names := map[string]bool{}
	s.expr.Walk(func(node *hogqlparser.Node) bool {
		if !node.Is("SelectQuery") {
			return true
		}
		for _, item := range node.Children("array_join_list") {
			if item.Is("Alias") {
				names[item.Text("alias")] = true
			}
		}
		for _, cte := range node.Children("ctes") {
			if cte.Text("cte_type") == "column" {
				names[cte.Text("name")] = true
			}
		}
		return true
	})
	return names
}
