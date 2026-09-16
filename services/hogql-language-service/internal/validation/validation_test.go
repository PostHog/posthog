package validation

import (
	"fmt"
	"strings"
	"testing"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
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
	result := Validate(schema(), "SELECT o.amuont FROM warehouse_orders AS o")
	if result.Valid || len(result.Diagnostics) != 1 {
		t.Fatalf("result = %#v", result)
	}
	diagnostic := result.Diagnostics[0]
	if diagnostic.Code != "unknown_field" || len(diagnostic.Suggestions) == 0 || diagnostic.Suggestions[0].Label != "amount" || diagnostic.Suggestions[0].Distance != 2 {
		t.Fatalf("diagnostic = %#v", diagnostic)
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
	result := Validate(schema(), "WITH x AS (SELECT event AS kind FROM events) SELECT x.timestamp FROM x")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_field" {
		t.Fatalf("result = %#v", result)
	}
	if len(result.TableNames) != 1 || result.TableNames[0] != "events" {
		t.Fatalf("table names = %#v", result.TableNames)
	}
}

func TestValidateRejectsUnknownQualifiedFields(t *testing.T) {
	for _, query := range []string{
		"SELECT missing.event FROM events",
		"SELECT missing.properties.value FROM events",
		"SELECT missing.* FROM events",
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
	}
	for _, test := range tests {
		result := Validate(schema(), test.query)
		if result.Valid || len(result.Diagnostics) != 1 {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
		diagnostic := result.Diagnostics[0]
		if diagnostic.Code != "unknown_property" || len(diagnostic.Suggestions) == 0 || diagnostic.Suggestions[0].Label != test.suggestion {
			t.Fatalf("query %q returned %#v", test.query, diagnostic)
		}
	}
}
