package validation

import (
	"strings"
	"testing"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

func schema() *catalog.Catalog {
	return &catalog.Catalog{Tables: map[string]catalog.Table{
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
		"events":  {Name: "events", Type: "posthog", Fields: map[string]catalog.Field{"properties": {Name: "properties", Type: "json"}}},
		"persons": {Name: "persons", Type: "posthog", Fields: map[string]catalog.Field{"properties": {Name: "properties", Type: "json"}}},
	}, Properties: map[string][]catalog.Property{
		"event":   {{Name: "$geo_city", ValueType: "String"}},
		"person":  {{Name: "$geo_country", ValueType: "String"}},
		"session": {{Name: "$entry_current_url", ValueType: "String"}},
		"group:0": {{Name: "industry", ValueType: "String"}},
	}}
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
	result := Validate(schema(), "SELECT sum(o.amount), o.order_id FROM warehouse_orders AS o WHERE o.amount > 0")
	if !result.Valid || len(result.Diagnostics) != 0 {
		t.Fatalf("result = %#v", result)
	}
	if len(result.TableNames) != 1 || result.TableNames[0] != "warehouse_orders" {
		t.Fatalf("table names = %#v", result.TableNames)
	}
}

func TestValidateAcceptsHogQLQualifiedTable(t *testing.T) {
	result := Validate(schema(), "SELECT o.synced_id FROM postgres.synced.orders AS o")
	if !result.Valid || len(result.Diagnostics) != 0 {
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
