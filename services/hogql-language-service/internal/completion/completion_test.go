package completion

import (
	"fmt"
	"strings"
	"testing"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

func testCatalog() *catalog.Catalog {
	return &catalog.Catalog{Tables: map[string]catalog.Table{
		"orders": {Name: "orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"order_id": {Name: "order_id", Type: "string"},
			"amount":   {Name: "amount", Type: "float"},
		}},
		"organizations": {Name: "organizations", Type: "posthog", Fields: map[string]catalog.Field{}},
		"postgres.synced.orders": {Name: "postgres.synced.orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"synced_id": {Name: "synced_id", Type: "string"},
		}},
	}, Properties: map[string][]catalog.Property{
		"event":   {{Name: "$geo_city", ValueType: "String"}, {Name: "$geo_country", ValueType: "String"}},
		"person":  {{Name: "$geo_city", ValueType: "String"}},
		"session": {{Name: "$entry_current_url", ValueType: "String"}},
		"group:0": {{Name: "industry", ValueType: "String"}},
	}}
}

func TestCompletionRejectsQueriesOutsideResourceLimits(t *testing.T) {
	_, err := Complete(testCatalog(), strings.Repeat("x", 64<<10+1), 0, "")
	if err == nil {
		t.Fatal("oversized query was accepted")
	}
}

func TestCompletesPropertiesForGenericNamespaces(t *testing.T) {
	tests := []struct {
		query    string
		position int
		expect   string
	}{
		{query: "SELECT events.properties.$geo FROM events", position: len("SELECT events.properties.$geo"), expect: "$geo_city"},
		{query: "SELECT e.properties.$geo FROM events AS e", position: len("SELECT e.properties.$geo"), expect: "$geo_city"},
		{query: "SELECT properties.$geo FROM persons", position: len("SELECT properties.$geo"), expect: "$geo_city"},
		{query: "SELECT session.properties.$entry FROM events", position: len("SELECT session.properties.$entry"), expect: "$entry_current_url"},
		{query: "SELECT group_0.properties.ind FROM events", position: len("SELECT group_0.properties.ind"), expect: "industry"},
	}
	for _, test := range tests {
		result, err := Complete(testCatalog(), test.query, test.position, "")
		if err != nil {
			t.Fatal(err)
		}
		if len(result.Suggestions) == 0 || result.Suggestions[0].Label != test.expect || result.Suggestions[0].Kind != "property" {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
	}
}

func TestCompletesFieldsForHogQLQualifiedTable(t *testing.T) {
	query := "SELECT s. FROM postgres.synced.orders AS s"
	result, err := Complete(testCatalog(), query, len("SELECT s."), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 1 || result.Suggestions[0].Label != "synced_id" {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesTablesAfterFrom(t *testing.T) {
	result, err := Complete(testCatalog(), "SELECT * FROM ord", len("SELECT * FROM ord"), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 1 || result.Suggestions[0].Label != "orders" {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesFieldsForAlias(t *testing.T) {
	query := "SELECT o. FROM orders AS o"
	result, err := Complete(testCatalog(), query, len("SELECT o."), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 2 {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesFieldsForMixedCaseTableReference(t *testing.T) {
	query := "SELECT Orders. FROM Orders"
	result, err := Complete(testCatalog(), query, len("SELECT Orders."), "")
	if err != nil {
		t.Fatal(err)
	}
	if !hasSuggestion(result.Suggestions, "order_id") {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletionPagesWithoutSkippingOrRepeatingTables(t *testing.T) {
	schema := &catalog.Catalog{Tables: map[string]catalog.Table{}}
	for index := 0; index < 30; index++ {
		name := fmt.Sprintf("table_%02d", index)
		schema.Tables[name] = catalog.Table{Name: name, Type: "data_warehouse", Fields: map[string]catalog.Field{}}
	}
	query := "SELECT * FROM table_"
	first, err := Complete(schema, query, len(query), "")
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Suggestions) != PageSize || first.NextCursor == "" {
		t.Fatalf("first page has %d suggestions and cursor %q", len(first.Suggestions), first.NextCursor)
	}
	if first.Total != 30 {
		t.Fatalf("total = %d", first.Total)
	}
	second, err := Complete(schema, query, len(query), first.NextCursor)
	if err != nil {
		t.Fatal(err)
	}
	if len(second.Suggestions) != 5 || second.NextCursor != "" {
		t.Fatalf("second page has %d suggestions and cursor %q", len(second.Suggestions), second.NextCursor)
	}
	if first.Suggestions[24].Label != "table_24" || second.Suggestions[0].Label != "table_25" {
		t.Fatalf("page boundary is %q then %q", first.Suggestions[24].Label, second.Suggestions[0].Label)
	}
	if _, err := Complete(schema, query, len(query), "not-a-cursor"); err == nil {
		t.Fatal("invalid cursor was accepted")
	}
}

func hasSuggestion(suggestions []Suggestion, label string) bool {
	for _, suggestion := range suggestions {
		if suggestion.Label == label {
			return true
		}
	}
	return false
}
