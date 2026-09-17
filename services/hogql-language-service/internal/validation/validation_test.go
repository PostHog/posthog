package validation

import (
	"fmt"
	"strings"
	"testing"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

func schema() *catalog.PreparedCatalog {
	return catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"warehouse_orders": {Name: "warehouse_orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"order_id": {Name: "order_id", Type: "string"},
			"amount":   {Name: "amount", Type: "float"},
		}},
		"warehouse_people": {Name: "warehouse_people", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"person_id": {Name: "person_id", Type: "string"},
		}},
		"postgres.synced.orders": {Name: "postgres.synced.orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"synced_id": {Name: "synced_id", Type: "string"},
		}},
		"events": {Name: "events", Type: "posthog", Fields: map[string]catalog.Field{
			"event":      {Name: "event", Type: "string"},
			"properties": {Name: "properties", Type: "json"},
			"timestamp":  {Name: "timestamp", Type: "datetime"},
			"uuid":       {Name: "uuid", Type: "uuid"},
		}},
		"persons": {Name: "persons", Type: "posthog", Fields: map[string]catalog.Field{"properties": {Name: "properties", Type: "json"}}},
	}, Properties: map[string][]catalog.Property{
		"event":   {{Name: "$geo_city", ValueType: "String"}, {Name: "café", ValueType: "String"}},
		"person":  {{Name: "$geo_country", ValueType: "String"}},
		"session": {{Name: "$entry_current_url", ValueType: "String"}},
		"group:0": {{Name: "industry", ValueType: "String"}},
	}})
}

func TestValidateDoesNotShareBindingsAcrossStatements(t *testing.T) {
	result := Validate(schema(), "SELECT person_id FROM warehouse_orders; SELECT person_id FROM warehouse_people")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateDoesNotShareBindingsAcrossNestedQueries(t *testing.T) {
	result := Validate(schema(), "SELECT person_id FROM warehouse_orders WHERE order_id IN (SELECT person_id FROM warehouse_people)")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateNestedAliasShadowsOuterAlias(t *testing.T) {
	result := Validate(schema(), "SELECT o.person_id FROM warehouse_orders AS o WHERE order_id IN (SELECT o.person_id FROM warehouse_people AS o)")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateAllJoinedTables(t *testing.T) {
	result := Validate(schema(), "SELECT o.order_id, p.person_id FROM warehouse_orders AS o JOIN warehouse_people AS p ON o.order_id = p.person_id")
	if !result.Valid {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateRejectsQueriesOutsideResourceLimits(t *testing.T) {
	result := Validate(schema(), strings.Repeat("x", 64<<10+1))
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "query_limit" {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateCapsDiagnostics(t *testing.T) {
	fields := make([]string, 150)
	for index := range fields {
		fields[index] = "missing_" + strings.Repeat("x", index%10) + string(rune('a'+index%26))
	}
	result := Validate(schema(), "SELECT "+strings.Join(fields, ", ")+" FROM warehouse_orders")
	if len(result.Diagnostics) != 25 {
		t.Fatalf("diagnostics = %d", len(result.Diagnostics))
	}
}

func TestValidateUnknownTableSuggestsVisibleMatch(t *testing.T) {
	result := Validate(schema(), "SELECT order_id FROM warehose_orders")
	if result.Valid || len(result.Diagnostics) != 1 {
		t.Fatalf("result = %#v", result)
	}
	diagnostic := result.Diagnostics[0]
	if diagnostic.Code != "unknown_table" || len(diagnostic.Suggestions) == 0 || diagnostic.Suggestions[0].Label != "warehouse_orders" {
		t.Fatalf("diagnostic = %#v", diagnostic)
	}
}

func TestValidateUnknownAliasedFieldSuggestsVisibleMatch(t *testing.T) {
	for _, test := range []struct{ query, suggestion string }{
		{"SELECT o.amuont FROM warehouse_orders AS o", "amount"},
		{"SELECT amount AS total FROM warehouse_orders ORDER BY totla", "total"},
	} {
		result := Validate(schema(), test.query)
		if result.Valid || len(result.Diagnostics) != 1 {
			t.Fatalf("query %q: result = %#v", test.query, result)
		}
		diagnostic := result.Diagnostics[0]
		if diagnostic.Code != "unknown_field" || len(diagnostic.Suggestions) == 0 || diagnostic.Suggestions[0].Label != test.suggestion || diagnostic.Suggestions[0].Distance != 2 {
			t.Fatalf("query %q: diagnostic = %#v", test.query, diagnostic)
		}
	}
}

func TestValidateAcceptsKnownFieldsAndFunctions(t *testing.T) {
	for _, test := range []struct {
		query     string
		tableName string
	}{
		{query: "SELECT sum(o.amount), o.order_id FROM warehouse_orders AS o WHERE o.amount > 0", tableName: "warehouse_orders"},
		{query: "SELECT uuid FROM events WHERE event = '$pageview' AND timestamp > now() - interval 1 month", tableName: "events"},
		{query: "SELECT extract(month FROM timestamp) FROM events", tableName: "events"},
		{query: "SELECT properties.$GEO_CITY FROM events", tableName: "events"},
		{query: "SELECT s.kind FROM (SELECT event AS kind FROM events) AS s", tableName: "events"},
		{query: "WITH t AS (SELECT event AS `Σ` FROM events) SELECT t.`ς` FROM t", tableName: "events"},
		{query: "WITH t AS (SELECT event AS kind FROM events) SELECT s.kind FROM (SELECT * FROM t) AS s", tableName: "events"},
		{query: "SELECT amount AS total, total AS subtotal FROM warehouse_orders PREWHERE subtotal > 0 WHERE total > 0 GROUP BY total, subtotal HAVING total > 1 ORDER BY subtotal", tableName: "warehouse_orders"},
		{query: "SELECT event AS kind FROM events WHERE uuid IN (SELECT uuid AS kind FROM events WHERE kind != '') ORDER BY kind", tableName: "events"},
		{query: "SELECT s.subtotal FROM (SELECT amount AS total, total AS subtotal FROM warehouse_orders) AS s", tableName: "warehouse_orders"},
		{query: "SELECT amount AS amount FROM warehouse_orders ORDER BY amount", tableName: "warehouse_orders"},
	} {
		result := Validate(schema(), test.query)
		if !result.Valid || len(result.Diagnostics) != 0 {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
		if len(result.TableNames) != 1 || result.TableNames[0] != test.tableName {
			t.Fatalf("query %q returned table names %#v", test.query, result.TableNames)
		}
	}
}

func TestValidateAcceptsHogQLQualifiedTable(t *testing.T) {
	result := Validate(schema(), "SELECT o.synced_id FROM postgres.synced.orders AS o")
	if !result.Valid || len(result.Diagnostics) != 0 {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidateDuplicateTableNames(t *testing.T) {
	for _, test := range []struct {
		name, query, qualifier string
		valid                  bool
	}{
		{name: "unaliased", query: "SELECT events.properties FROM events JOIN events ON 1 = 1", qualifier: "events"},
		{name: "duplicate alias", query: "SELECT e.properties FROM events AS e JOIN persons AS e ON 1 = 1", qualifier: "e"},
		{name: "derived property", query: "WITH t AS (SELECT events.properties FROM events JOIN events ON 1 = 1) SELECT t.properties.$geo_cty FROM t", qualifier: "events"},
		{name: "distinct aliases", query: "SELECT e.properties FROM events AS e JOIN events AS other ON 1 = 1", valid: true},
		{name: "case-sensitive aliases", query: "SELECT e.properties FROM events AS e JOIN events AS E ON 1 = 1", valid: true},
		{name: "nested reuse", query: "SELECT e.properties FROM events AS e WHERE uuid IN (SELECT properties FROM persons AS e)", valid: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			result := Validate(schema(), test.query)
			if test.valid {
				if !result.Valid || len(result.Diagnostics) != 0 {
					t.Fatalf("result = %#v", result)
				}
				return
			}
			if result.Valid || len(result.Diagnostics) != 1 {
				t.Fatalf("result = %#v", result)
			}
			diagnostic := result.Diagnostics[0]
			if diagnostic.Code != "duplicate_table" || diagnostic.Message != fmt.Sprintf("Table name %q is used more than once. Use a distinct alias for each table.", test.qualifier) {
				t.Fatalf("diagnostic = %#v", diagnostic)
			}
			secondJoin := strings.Index(test.query, " JOIN ") + len(" JOIN ")
			if diagnostic.Start != secondJoin || diagnostic.End <= diagnostic.Start {
				t.Fatalf("diagnostic span = %d:%d, want start %d", diagnostic.Start, diagnostic.End, secondJoin)
			}
		})
	}
}

func TestValidateCommonTableExpressions(t *testing.T) {
	tests := []struct {
		name       string
		query      string
		tableNames []string
	}{
		{
			name:       "basic",
			query:      "WITH x AS (SELECT event FROM events) SELECT * FROM x",
			tableNames: []string{"events"},
		},
		{
			name:       "projected alias",
			query:      "WITH x AS (SELECT event AS kind FROM events) SELECT x.kind FROM x",
			tableNames: []string{"events"},
		},
		{
			name:       "wildcard projection",
			query:      "WITH x AS (SELECT * FROM events) SELECT x.uuid FROM x",
			tableNames: []string{"events"},
		},
		{
			name:       "qualified wildcard projection",
			query:      "WITH x AS (SELECT e.* FROM events AS e) SELECT x.uuid FROM x",
			tableNames: []string{"events"},
		},
		{
			name:       "chained",
			query:      "WITH x AS (SELECT event AS kind FROM events), y AS (SELECT kind FROM x) SELECT y.kind FROM y",
			tableNames: []string{"events"},
		},
		{
			name:       "shadows physical table",
			query:      "WITH events AS (SELECT person_id FROM warehouse_people) SELECT events.person_id FROM events",
			tableNames: []string{"warehouse_people"},
		},
		{
			name:       "definition does not reference itself",
			query:      "WITH events AS (SELECT event FROM events) SELECT events.event FROM events",
			tableNames: []string{"events"},
		},
		{
			name:       "nested definition shadows outer definition",
			query:      "WITH x AS (SELECT event AS outer_field FROM events), y AS (WITH x AS (SELECT person_id AS inner_field FROM warehouse_people) SELECT inner_field FROM x) SELECT y.inner_field FROM y",
			tableNames: []string{"events", "warehouse_people"},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			result := Validate(schema(), test.query)
			if !result.Valid || len(result.Diagnostics) != 0 {
				t.Fatalf("result = %#v", result)
			}
			if strings.Join(result.TableNames, ",") != strings.Join(test.tableNames, ",") {
				t.Fatalf("table names = %#v", result.TableNames)
			}
		})
	}
}

func TestValidateRejectsUnknownCommonTableExpressionField(t *testing.T) {
	for _, query := range []string{
		"WITH x AS (SELECT event AS kind FROM events) SELECT x.timestamp FROM x",
		"SELECT x.timestamp FROM (SELECT event AS kind FROM events) AS x",
		"SELECT timestamp FROM (SELECT event AS kind FROM events) AS x",
	} {
		result := Validate(schema(), query)
		if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
			t.Fatalf("query %q: result = %#v", query, result)
		}
		if len(result.TableNames) != 1 || result.TableNames[0] != "events" {
			t.Fatalf("table names = %#v", result.TableNames)
		}
	}
}

func TestValidateRejectsUnknownFields(t *testing.T) {
	for _, query := range []string{
		"SELECT missing.event FROM events",
		"SELECT missing.properties.value FROM events",
		"SELECT missing.* FROM events",
		"SELECT total, amount AS total FROM warehouse_orders",
		"SELECT total AS total FROM warehouse_orders",
		"SELECT amount AS total FROM warehouse_orders JOIN events ON total = 1",
		"SELECT amount AS total FROM warehouse_orders WHERE order_id IN (SELECT total FROM events)",
		"SELECT total FROM warehouse_orders WHERE order_id IN (SELECT event AS total FROM events)",
		"SELECT amount AS total FROM warehouse_orders; SELECT total FROM events",
		"SELECT amount AS total FROM warehouse_orders UNION ALL SELECT total FROM warehouse_orders",
		"WITH t AS (SELECT total FROM warehouse_orders) SELECT amount AS total FROM warehouse_orders",
		"SELECT event AS kind FROM events ORDER BY events.kind",
		"SELECT amount AS Total FROM warehouse_orders ORDER BY total",
	} {
		result := Validate(schema(), query)
		if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
			t.Fatalf("query %q returned %#v", query, result)
		}
	}
}

func TestValidateBoundsCommonTableExpressionProjectionExpansion(t *testing.T) {
	ctes := []string{"c0 AS (SELECT * FROM events)"}
	for index := 1; index < 14; index++ {
		ctes = append(ctes, fmt.Sprintf(
			"c%d AS (SELECT left_side.*, right_side.* FROM c%d AS left_side JOIN c%d AS right_side ON 1 = 1)",
			index, index-1, index-1,
		))
	}
	withinBudget := "WITH " + strings.Join(ctes[:12], ", ") + " SELECT event FROM c11"
	for _, test := range []struct {
		name, query string
		valid       bool
	}{
		{name: "single statement within budget", query: withinBudget, valid: true},
		{name: "single statement exceeds budget", query: "WITH " + strings.Join(ctes, ", ") + " SELECT missing FROM c13"},
		{name: "shared budget stops before later statements", query: withinBudget + "; " + withinBudget + "; SELECT person_id FROM warehouse_people"},
	} {
		t.Run(test.name, func(t *testing.T) {
			result := Validate(schema(), test.query)
			if result.Valid != test.valid {
				t.Fatalf("result = %#v", result)
			}
			if !test.valid && (len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "query_limit") {
				t.Fatalf("result = %#v", result)
			}
			if strings.Join(result.TableNames, ",") != "events" {
				t.Fatalf("table names = %#v", result.TableNames)
			}
		})
	}
}

func TestValidateBoundsFieldLookupWork(t *testing.T) {
	ctes := make([]string, 128)
	from := "c0"
	for index := range ctes {
		ctes[index] = fmt.Sprintf("c%d AS (SELECT event FROM events)", index)
		if index > 0 {
			from += fmt.Sprintf(" JOIN c%d ON 1 = 1", index)
		}
	}
	ctes = append(ctes, "result AS (SELECT "+strings.Repeat("unknown", 1500)+", c0.event FROM "+from+")")
	query := "WITH " + strings.Join(ctes, ", ") + " SELECT result.event FROM result"
	result := Validate(schema(), query)
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "query_limit" || result.Diagnostics[0].Message != querylimits.ErrFieldLookupTooLarge.Error() {
		t.Fatalf("result = %#v", result)
	}
}

func TestValidatePropertiesAcrossGenericNamespaces(t *testing.T) {
	tests := []struct {
		query      string
		suggestion string
	}{
		{query: "SELECT e.properties.$geo_cty FROM events AS e", suggestion: "$geo_city"},
		{query: "SELECT persons.properties.$geo_contry FROM persons", suggestion: "$geo_country"},
		{query: "SELECT session.properties.$entry_curent_url FROM events", suggestion: "$entry_current_url"},
		{query: "SELECT group_0.properties.indstry FROM events", suggestion: "industry"},
		{query: "SELECT properties.cafe FROM events", suggestion: "café"},
		{query: "WITH t AS (SELECT 1 AS x) SELECT properties.$geo_cty FROM events JOIN t ON 1 = 1", suggestion: "$geo_city"},
		{query: "SELECT properties.$geo_cty FROM events JOIN (SELECT 1 AS x) AS t ON 1 = 1", suggestion: "$geo_city"},
		{query: "WITH t AS (SELECT properties AS attrs FROM events) SELECT properties.$geo_cty FROM events JOIN t ON 1 = 1", suggestion: "$geo_city"},
		{query: "WITH recent AS (SELECT properties FROM events) SELECT recent.properties.$geo_cty FROM recent", suggestion: "$geo_city"},
		{query: "WITH recent AS (SELECT properties FROM events) SELECT properties.$geo_cty FROM recent", suggestion: "$geo_city"},
		{query: "SELECT recent.properties.$geo_cty FROM (SELECT properties FROM events) AS recent", suggestion: "$geo_city"},
		{query: "WITH recent AS (SELECT properties AS props FROM events) SELECT recent.props.$geo_cty FROM recent", suggestion: "$geo_city"},
		{query: "WITH recent AS (SELECT properties AS props FROM events) SELECT props.$geo_cty FROM recent", suggestion: "$geo_city"},
		{query: "WITH a AS (SELECT properties FROM persons), events AS (SELECT * FROM a) SELECT events.properties.$geo_contry FROM events", suggestion: "$geo_country"},
		{query: "SELECT properties AS props, props AS attrs, attrs.$geo_cty FROM events", suggestion: "$geo_city"},
		{query: "SELECT properties AS props, uuid AS props, props.$geo_cty FROM events", suggestion: ""},
		{query: "SELECT properties FROM events EXCEPT SELECT properties.$geo_contry FROM persons", suggestion: "$geo_country"},
	}
	for _, test := range tests {
		result := Validate(schema(), test.query)
		if test.suggestion == "" {
			if !result.Valid || len(result.Diagnostics) != 0 {
				t.Fatalf("query %q returned %#v", test.query, result)
			}
			continue
		}
		if result.Valid || len(result.Diagnostics) != 1 {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
		diagnostic := result.Diagnostics[0]
		if diagnostic.Code != "unknown_property" || len(diagnostic.Suggestions) == 0 || diagnostic.Suggestions[0].Label != test.suggestion {
			t.Fatalf("query %q returned %#v", test.query, diagnostic)
		}
	}
}
