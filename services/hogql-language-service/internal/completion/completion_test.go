package completion

import (
	"encoding/json"
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
	_, err := Complete(testCatalog(), strings.Repeat("x", 64<<10+1), 0, PositionEncodingUTF8, "")
	if err == nil {
		t.Fatal("oversized query was accepted")
	}
}

func TestUTF16OffsetToByteOffset(t *testing.T) {
	tests := []struct {
		value  string
		offset int
		expect int
	}{
		{value: "SELECT ", offset: 7, expect: 7},
		{value: "SELECT '😀' FROM ", offset: 17, expect: 19},
		{value: "😀", offset: 1, expect: 0},
		{value: "😀", offset: 3, expect: 4},
		{value: "SELECT ", offset: -1, expect: 7},
	}
	for _, test := range tests {
		if actual := utf16OffsetToByteOffset(test.value, test.offset); actual != test.expect {
			t.Errorf("utf16OffsetToByteOffset(%q, %d) = %d, want %d", test.value, test.offset, actual, test.expect)
		}
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
		result, err := Complete(testCatalog(), test.query, test.position, PositionEncodingUTF8, "")
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
	result, err := Complete(testCatalog(), query, len("SELECT s."), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 1 || result.Suggestions[0].Label != "synced_id" {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesTablesAfterFrom(t *testing.T) {
	result, err := Complete(testCatalog(), "SELECT * FROM ord", len("SELECT * FROM ord"), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 1 || result.Suggestions[0].Label != "orders" {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesFieldsForAlias(t *testing.T) {
	query := "SELECT o. FROM orders AS o"
	result, err := Complete(testCatalog(), query, len("SELECT o."), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 2 {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesFieldsForMixedCaseTableReference(t *testing.T) {
	query := "SELECT Orders. FROM Orders"
	result, err := Complete(testCatalog(), query, len("SELECT Orders."), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if !hasSuggestion(result.Suggestions, "order_id") {
		t.Fatalf("suggestions = %#v; parse error = %q", result.Suggestions, result.ParseError)
	}
}

func TestCompletesSQLSyntaxForCursorContext(t *testing.T) {
	tests := []struct {
		name       string
		query      string
		position   int
		label      string
		kind       string
		insertText string
		excluded   string
	}{
		{name: "function in select", query: "SELECT cou FROM orders", position: len("SELECT cou"), label: "count", kind: "function", insertText: "count()"},
		{name: "embedded function in select", query: "SELECT geoD FROM orders", position: len("SELECT geoD"), label: "geoDistance", kind: "function", insertText: "geoDistance()"},
		{name: "function in where", query: "SELECT * FROM orders WHERE coa", position: len("SELECT * FROM orders WHERE coa"), label: "coalesce", kind: "function", insertText: "coalesce()"},
		{name: "operator after field", query: "SELECT * FROM orders WHERE amount ", position: len("SELECT * FROM orders WHERE amount "), label: "=", kind: "operator", insertText: "=", excluded: "AND"},
		{name: "boolean after predicate", query: "SELECT * FROM orders WHERE amount > 0 ", position: len("SELECT * FROM orders WHERE amount > 0 "), label: "AND", kind: "keyword", insertText: "AND", excluded: "="},
		{name: "field after boolean", query: "SELECT * FROM orders WHERE amount > 0 AND ", position: len("SELECT * FROM orders WHERE amount > 0 AND "), label: "amount", kind: "field"},
		{name: "field after select comma", query: "SELECT amount,  FROM orders", position: len("SELECT amount, "), label: "amount", kind: "field", excluded: "orders"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			result, err := Complete(testCatalog(), test.query, test.position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			suggestion, ok := findSuggestion(result.Suggestions, test.label)
			if !ok || suggestion.Kind != test.kind || suggestion.InsertText != test.insertText {
				t.Fatalf("suggestion %q = %#v; all suggestions = %#v; parse error = %q", test.label, suggestion, result.Suggestions, result.ParseError)
			}
			if test.excluded != "" && hasSuggestion(result.Suggestions, test.excluded) {
				t.Fatalf("unexpected suggestion %q in %#v", test.excluded, result.Suggestions)
			}
		})
	}
}

func TestCompletionReturnsNoSuggestionsInsideStringOrComment(t *testing.T) {
	for _, query := range []string{
		"SELECT * FROM orders WHERE order_id = 'cou",
		"SELECT * FROM orders -- cou",
		"SELECT * FROM orders /* cou",
	} {
		result, err := Complete(testCatalog(), query, len(query), PositionEncodingUTF8, "")
		if err != nil {
			t.Fatal(err)
		}
		if len(result.Suggestions) != 0 {
			t.Fatalf("query %q returned %#v", query, result.Suggestions)
		}
	}
}

func TestCompletionPagesWithoutSkippingOrRepeatingTables(t *testing.T) {
	schema := &catalog.Catalog{Tables: map[string]catalog.Table{}}
	for index := 0; index < 30; index++ {
		name := fmt.Sprintf("table_%02d", index)
		schema.Tables[name] = catalog.Table{Name: name, Type: "data_warehouse", Fields: map[string]catalog.Field{}}
	}
	query := "SELECT * FROM table_"
	first, err := Complete(schema, query, len(query), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Suggestions) != PageSize || first.NextCursor == "" {
		t.Fatalf("first page has %d suggestions and cursor %q", len(first.Suggestions), first.NextCursor)
	}
	if first.Total != 30 {
		t.Fatalf("total = %d", first.Total)
	}
	second, err := Complete(schema, query, len(query), PositionEncodingUTF8, first.NextCursor)
	if err != nil {
		t.Fatal(err)
	}
	if len(second.Suggestions) != 5 || second.NextCursor != "" {
		t.Fatalf("second page has %d suggestions and cursor %q", len(second.Suggestions), second.NextCursor)
	}
	if first.Suggestions[24].Label != "table_24" || second.Suggestions[0].Label != "table_25" {
		t.Fatalf("page boundary is %q then %q", first.Suggestions[24].Label, second.Suggestions[0].Label)
	}
	if _, err := Complete(schema, query, len(query), PositionEncodingUTF8, "not-a-cursor"); err == nil {
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

func findSuggestion(suggestions []Suggestion, label string) (Suggestion, bool) {
	for _, suggestion := range suggestions {
		if suggestion.Label == label {
			return suggestion, true
		}
	}
	return Suggestion{}, false
}

func BenchmarkCompleteContextualCatalog(b *testing.B) {
	schema := &catalog.Catalog{Tables: make(map[string]catalog.Table, 1024)}
	for tableIndex := 0; tableIndex < 1024; tableIndex++ {
		fields := make(map[string]catalog.Field, 25)
		for fieldIndex := 0; fieldIndex < 25; fieldIndex++ {
			name := fmt.Sprintf("column_%02d", fieldIndex)
			fields[name] = catalog.Field{Name: name, Type: "String"}
		}
		name := fmt.Sprintf("table_%04d", tableIndex)
		schema.Tables[name] = catalog.Table{Name: name, Type: "data_warehouse", Fields: fields}
	}
	for _, benchmark := range []struct {
		name     string
		query    string
		position int
	}{
		{name: "operator", query: "SELECT * FROM table_0500 WHERE column_10 ", position: len("SELECT * FROM table_0500 WHERE column_10 ")},
		{name: "function prefix", query: "SELECT countD FROM table_0500", position: len("SELECT countD")},
	} {
		b.Run(benchmark.name, func(b *testing.B) {
			result, err := Complete(schema, benchmark.query, benchmark.position, PositionEncodingUTF8, "")
			if err != nil {
				b.Fatal(err)
			}
			payload, err := json.Marshal(result)
			if err != nil {
				b.Fatal(err)
			}
			b.ResetTimer()
			b.ReportMetric(float64(len(payload)), "response-B")
			for range b.N {
				if _, err := Complete(schema, benchmark.query, benchmark.position, PositionEncodingUTF8, ""); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
