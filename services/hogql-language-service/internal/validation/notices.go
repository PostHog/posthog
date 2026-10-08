package validation

import (
	"fmt"
	"sort"
	"strings"

	clickhouse "github.com/orian/clickhouse-sql-parser/parser"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

type Notice struct {
	Message string `json:"message"`
	Start   int    `json:"start"`
	End     int    `json:"end"`
}

type noticeCollector struct {
	query   string
	notices []Notice
	seen    map[[2]int]bool
}

func newNoticeCollector(query string) *noticeCollector {
	return &noticeCollector{query: query, seen: make(map[[2]int]bool)}
}

func (c *noticeCollector) add(message string, start, end int) {
	if start < 0 || end > len(c.query) || start >= end {
		return
	}
	if start > 0 && end < len(c.query) && (c.query[start-1] == '`' && c.query[end] == '`' || c.query[start-1] == '"' && c.query[end] == '"') {
		start--
		end++
	}
	if len(c.notices) >= querylimits.MaxNotices || c.seen[[2]int{start, end}] {
		return
	}
	c.seen[[2]int{start, end}] = true
	c.notices = append(c.notices, Notice{Message: message, Start: start, End: end})
}

func displayType(raw string) string {
	switch strings.ToLower(raw) {
	case "string":
		return "String"
	case "integer", "int":
		return "Integer"
	case "float", "numeric":
		return "Float"
	case "boolean", "bool":
		return "Boolean"
	case "datetime":
		return "DateTime"
	case "date":
		return "Date"
	case "uuid":
		return "UUID"
	case "json":
		return "JSON"
	case "array":
		return "Array"
	case "tuple":
		return "Tuple"
	case "decimal":
		return "Decimal"
	default:
		return ""
	}
}

func (c *noticeCollector) addField(ident *clickhouse.Ident, rawType string) {
	if fieldType := displayType(rawType); fieldType != "" {
		c.add(fmt.Sprintf("Field '%s' is of type '%s'", ident.Name, fieldType), int(ident.Pos()), int(ident.End()))
	}
}

func (c *noticeCollector) addProperty(ident *clickhouse.Ident, namespace string, properties *catalog.Index) {
	field, ok := properties.Exact(ident.Name)
	if !ok {
		return
	}
	fieldType := displayType(field.Type)
	if fieldType == "" {
		return
	}
	owner := namespace
	if strings.HasPrefix(owner, "group:") {
		owner = "group"
	}
	c.add(fmt.Sprintf("%s property '%s' is of type '%s'", strings.ToUpper(owner[:1])+owner[1:], ident.Name, fieldType), int(ident.Pos()), int(ident.End()))
}

func (c *noticeCollector) sorted() []Notice {
	sort.Slice(c.notices, func(i, j int) bool {
		if c.notices[i].Start != c.notices[j].Start {
			return c.notices[i].Start < c.notices[j].Start
		}
		return c.notices[i].End < c.notices[j].End
	})
	return c.notices
}

func collectNotices(schema *catalog.PreparedCatalog, document *analysis.Document, query string) []Notice {
	if document.LimitError() != nil {
		return nil
	}
	collector := newNoticeCollector(query)
	for statement := range document.Statements() {
		for table := range statement.ResolvedTables() {
			message := fmt.Sprintf("Table '%s'", table.Name)
			if table.CTE {
				message = fmt.Sprintf("Table '%s' is a common table expression", table.Name)
			} else if table.Canonical != table.Name {
				message = fmt.Sprintf("Table '%s' refers to '%s'", table.Name, table.Canonical)
			}
			collector.add(message, table.Start, table.End)
		}
		ignoredIdents := ignoredIdentifierNodes(statement)
		statement.Walk(func(node clickhouse.Expr) bool {
			if len(collector.notices) >= querylimits.MaxNotices || document.LimitError() != nil {
				return false
			}
			switch typed := node.(type) {
			case *clickhouse.NestedIdentifier:
				if typed.DotIdent == nil {
					return true
				}
				ignoredIdents[typed.Ident] = true
				ignoredIdents[typed.DotIdent] = true
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				if resolved, ok := bindings.UnambiguousRelation(typed.Ident.Name); ok {
					if field, ok := resolved.ResolvedField(typed.DotIdent.Name); ok {
						collector.addField(typed.DotIdent, field.Type)
					}
				}
			case *clickhouse.Path:
				if len(typed.Fields) < 2 {
					return true
				}
				for _, field := range typed.Fields {
					ignoredIdents[field] = true
				}
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				parts := make([]string, len(typed.Fields))
				for index, field := range typed.Fields {
					parts[index] = field.Name
				}
				target := bindings.Traversal(parts[:len(parts)-1])
				if target.Explicit {
					if target.Valid && target.PropertyNamespace != "" {
						propertyAt := len(typed.Fields) - 1
						if target.HasProperty {
							propertyAt = target.PropertyAt
						}
						collector.addProperty(typed.Fields[propertyAt], target.PropertyNamespace, schema.Properties(target.PropertyNamespace))
					} else if target.Valid && target.Fields != nil {
						if field, ok := target.Fields.Exact(typed.Fields[len(typed.Fields)-1].Name); ok {
							collector.addField(typed.Fields[len(typed.Fields)-1], field.Type)
						}
					}
					return true
				}
				if namespace, ok := bindings.PropertyNamespace(parts); ok {
					collector.addProperty(typed.Fields[len(typed.Fields)-1], namespace, schema.Properties(namespace))
					return true
				}
				if resolved, ok := bindings.UnambiguousRelation(typed.Fields[0].Name); ok {
					if field, ok := resolved.ResolvedField(typed.Fields[1].Name); ok {
						collector.addField(typed.Fields[1], field.Type)
					}
				}
			case *clickhouse.Ident:
				if ignoredIdents[typed] || typed.Name == "*" || analysis.IsBooleanLiteral(typed) {
					return true
				}
				bindings := statement.BindingsAt(int(node.Pos()), int(node.End()))
				if field, ok := bindings.ResolvedSelectAlias(typed.Name); ok {
					collector.addField(typed, field.Type)
				} else if _, exists := bindings.SelectAlias(typed.Name); !exists {
					if field, ok := bindings.ResolvedField(typed.Name); ok {
						collector.addField(typed, field.Type)
					}
				}
			}
			return true
		})
		if len(collector.notices) >= querylimits.MaxNotices || document.LimitError() != nil {
			break
		}
	}
	return collector.sorted()
}
