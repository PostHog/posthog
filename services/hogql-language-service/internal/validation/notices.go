package validation

import (
	"fmt"
	"sort"
	"strings"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/analysis"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/hogqlparser"
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

func (c *noticeCollector) addField(ident hogqlparser.FieldPart, rawType string) {
	if fieldType := displayType(rawType); fieldType != "" {
		c.add(fmt.Sprintf("Field '%s' is of type '%s'", ident.Name, fieldType), ident.Start, ident.End)
	}
}

func (c *noticeCollector) addProperty(ident hogqlparser.FieldPart, namespace string, properties *catalog.Index) {
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
	c.add(fmt.Sprintf("%s property '%s' is of type '%s'", strings.ToUpper(owner[:1])+owner[1:], ident.Name, fieldType), ident.Start, ident.End)
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
		for field := range statement.ColumnFields() {
			if len(collector.notices) >= querylimits.MaxNotices || document.LimitError() != nil {
				break
			}
			collector.addColumnField(schema, statement, field)
		}
		if len(collector.notices) >= querylimits.MaxNotices || document.LimitError() != nil {
			break
		}
	}
	return collector.sorted()
}

func (c *noticeCollector) addColumnField(schema *catalog.PreparedCatalog, statement *analysis.Statement, field analysis.ColumnField) {
	parts := field.Parts
	bindings := statement.BindingsAt(field.Node.Start, field.Node.End)
	if len(parts) == 1 {
		if parts[0].Name == "*" {
			return
		}
		if resolved, ok := bindings.ResolvedSelectAlias(parts[0].Name); ok {
			c.addField(parts[0], resolved.Type)
		} else if _, exists := bindings.SelectAlias(parts[0].Name); !exists {
			if resolved, ok := bindings.ResolvedField(parts[0].Name); ok {
				c.addField(parts[0], resolved.Type)
			}
		}
		return
	}
	names := make([]string, len(parts))
	for index, part := range parts {
		names[index] = part.Name
	}
	target := bindings.Traversal(names[:len(names)-1])
	if target.Explicit {
		if target.Valid && target.PropertyNamespace != "" {
			propertyAt := len(parts) - 1
			if target.HasProperty {
				propertyAt = target.PropertyAt
			}
			c.addProperty(parts[propertyAt], target.PropertyNamespace, schema.Properties(target.PropertyNamespace))
		} else if target.Valid && target.Fields != nil {
			if resolved, ok := target.Fields.Exact(parts[len(parts)-1].Name); ok {
				c.addField(parts[len(parts)-1], resolved.Type)
			}
		}
		return
	}
	if namespace, ok := bindings.PropertyNamespace(names); ok {
		c.addProperty(parts[len(parts)-1], namespace, schema.Properties(namespace))
		return
	}
	if resolved, ok := bindings.UnambiguousRelation(parts[0].Name); ok {
		if entry, ok := resolved.ResolvedField(parts[1].Name); ok {
			c.addField(parts[1], entry.Type)
		}
	}
}
