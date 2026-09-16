package completion

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
)

func testCatalog() *catalog.PreparedCatalog {
	return catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"events": {Name: "events", Type: "posthog", Fields: map[string]catalog.Field{
			"uuid": {Name: "uuid", Type: "string"}, "event": {Name: "event", Type: "string"},
			"properties": {Name: "properties", Type: "json"},
		}},
		"persons": {Name: "persons", Type: "posthog", Fields: map[string]catalog.Field{
			"id": {Name: "id", Type: "string"}, "properties": {Name: "properties", Type: "json"},
		}},
		"orders": {Name: "orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"order_id": {Name: "order_id", Type: "string"},
			"amount":   {Name: "amount", Type: "float"},
		}},
		"organizations": {Name: "organizations", Type: "posthog", Fields: map[string]catalog.Field{}},
		"postgres.synced.orders": {Name: "postgres.synced.orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"synced_id": {Name: "synced_id", Type: "string"},
		}},
	}, Properties: map[string][]catalog.Property{
		"event":   {{Name: "$geo_city", ValueType: "String"}, {Name: "$geo_country", ValueType: "String"}, {Name: "$Geo_Region", ValueType: "String"}},
		"person":  {{Name: "$geo_city", ValueType: "String"}},
		"session": {{Name: "$entry_current_url", ValueType: "String"}},
		"group:0": {{Name: "industry", ValueType: "String"}},
	}})
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
		{query: "SELECT properties.$geo_r FROM events", position: len("SELECT properties.$geo_r"), expect: "$Geo_Region"},
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

func TestCompletesScopedProjections(t *testing.T) {
	for _, test := range []struct {
		name, query string
		fields      map[string]string
	}{
		{"cte", "WITH t AS (SELECT order_id, amount AS total FROM orders) SELECT t.| FROM t", map[string]string{"order_id": "string", "total": "float"}},
		{"before from", "WITH t AS (SELECT amount AS total FROM orders) SELECT t.|", map[string]string{"total": "float"}},
		{"unqualified", "WITH t AS (SELECT amount AS total FROM orders) SELECT tot| FROM t", map[string]string{"total": "float"}},
		{"chained", "WITH a AS (SELECT amount AS total FROM orders), b AS (SELECT * FROM a) SELECT b.| FROM b", map[string]string{"total": "float"}},
		{"shadow catalog", "WITH orders AS (SELECT event FROM events) SELECT orders.| FROM orders", map[string]string{"event": "string"}},
		{"nested shadow", "WITH t AS (SELECT amount FROM orders) SELECT * FROM (WITH t AS (SELECT event FROM events) SELECT t.| FROM t) AS s", map[string]string{"event": "string"}},
		{"subquery", "SELECT s.| FROM (SELECT order_id, amount AS total FROM orders) AS s", map[string]string{"order_id": "string", "total": "float"}},
		{"nested subquery", "SELECT s.| FROM (SELECT x.total FROM (SELECT amount AS total FROM orders) AS x) AS s", map[string]string{"total": "float"}},
		{"warehouse", "WITH t AS (SELECT * FROM postgres.synced.orders) SELECT t.| FROM t", map[string]string{"synced_id": "string"}},
		{"no sibling alias", "SELECT x.| FROM (SELECT amount FROM orders AS x) AS s", nil},
		{"no sibling cte", "WITH t AS (SELECT amount FROM orders), u AS (SELECT x.| FROM events) SELECT * FROM orders AS x", nil},
		{"no later cte", "WITH a AS (SELECT b.| FROM orders), b AS (SELECT event FROM events) SELECT * FROM a", nil},
		{"no self cte", "WITH a AS (SELECT a.| FROM orders) SELECT * FROM a", nil},
		{"no sibling statement", "SELECT * FROM orders AS x; SELECT x.| FROM events", nil},
		{"no sibling union", "SELECT * FROM orders AS x UNION ALL SELECT x.| FROM events", nil},
		{"malformed scopes", "WITH t AS (SELECT amount FROM orders AS x) SELECT x.| FROM (", nil},
		{"malformed literal", "SELECT 'FROM orders AS x' WHERE x.| =", nil},
		{"property shadow", "WITH events AS (SELECT amount AS properties FROM orders) SELECT events.properties.| FROM events", nil},
		{"property shadow before from", "WITH events AS (SELECT amount AS properties FROM orders) SELECT events.properties.|", nil},
		{"derived body isolation", "SELECT * FROM orders AS x JOIN (SELECT x.| FROM events) AS s ON 1 = 1", nil},
		{"joined derived sources", "WITH t AS (SELECT event FROM events) SELECT s.| FROM t JOIN (SELECT amount AS total FROM orders) AS s ON 1 = 1", map[string]string{"total": "float"}},
		{"unicode prefix", "WITH t AS (SELECT amount AS `数額` FROM orders) SELECT t.数| FROM t", map[string]string{"数額": "float"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.query, '|')
			query := strings.Replace(test.query, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			fields := map[string]string{}
			for _, suggestion := range result.Suggestions {
				if suggestion.Kind == "field" || suggestion.Kind == "property" {
					fields[suggestion.Label] = suggestion.Detail
				}
			}
			if len(fields) != len(test.fields) {
				t.Fatalf("fields = %#v, want %#v; parse error = %s", fields, test.fields, result.ParseError)
			}
			for name, detail := range test.fields {
				if actual, ok := fields[name]; !ok || actual != detail {
					t.Errorf("field %q = %q (%t), want %q", name, actual, ok, detail)
				}
			}
		})
	}
}

func TestDerivedProjectionPaginationAndLimits(t *testing.T) {
	var items []string
	for index := 0; index < PageSize+2; index++ {
		items = append(items, fmt.Sprintf("amount AS field_%02d", index))
	}
	items = append(items, "amount AS field_00")
	for _, source := range []string{
		"WITH t AS (SELECT " + strings.Join(items, ", ") + " FROM orders) SELECT t.| FROM t",
		"SELECT t.| FROM (SELECT " + strings.Join(items, ", ") + " FROM orders) AS t",
	} {
		position := strings.IndexByte(source, '|')
		query := strings.Replace(source, "|", "", 1)
		cursor := ""
		var fields []string
		for {
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, cursor)
			if err != nil || result.Total != PageSize+2 || len(result.Suggestions) > PageSize {
				t.Fatalf("result = %#v, err = %v", result, err)
			}
			for _, suggestion := range result.Suggestions {
				fields = append(fields, suggestion.Label)
			}
			cursor = result.NextCursor
			if cursor == "" {
				break
			}
			if len(fields) > PageSize+2 {
				t.Fatal("pagination did not terminate")
			}
		}
		if len(fields) != PageSize+2 {
			t.Fatalf("fields = %#v", fields)
		}
		for index, name := range fields {
			if name != fmt.Sprintf("field_%02d", index) {
				t.Fatalf("fields = %#v", fields)
			}
		}
	}

	ctes := []string{"c0 AS (SELECT * FROM orders)"}
	for index := 1; index < 15; index++ {
		ctes = append(ctes, fmt.Sprintf("c%d AS (SELECT a.*, b.* FROM c%d AS a JOIN c%d AS b ON 1 = 1)", index, index-1, index-1))
	}
	for _, projection := range []string{"c14.", ""} {
		prefix := "WITH " + strings.Join(ctes, ", ") + " SELECT " + projection
		_, err := Complete(testCatalog(), prefix+" FROM c14", len(prefix), PositionEncodingUTF8, "")
		if !errors.Is(err, querylimits.ErrCTEProjectionTooLarge) {
			t.Fatalf("projection %q: err = %v", projection, err)
		}
	}
}

func TestCompletionQuotesIdentifierInsertionText(t *testing.T) {
	schema := catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"from":          {Name: "from", Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		"order-items":   {Name: "order-items", Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		"percent%table": {Name: "percent%table", Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		"orders": {Name: "orders", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"billing address": {Name: "billing address", Type: "string"},
			"FROM":            {Name: "FROM", Type: "string"},
			"order-total":     {Name: "order-total", Type: "float"},
			"percent%field":   {Name: "percent%field", Type: "string"},
			"tick`value":      {Name: "tick`value", Type: "string"},
		}},
	}, Properties: map[string][]catalog.Property{}})

	tableResult, err := Complete(schema, "SELECT * FROM order", len("SELECT * FROM order"), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	keywordTableResult, err := Complete(schema, "SELECT * FROM fr", len("SELECT * FROM fr"), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	unsupportedTableResult, err := Complete(schema, "SELECT * FROM percent", len("SELECT * FROM percent"), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	fieldResult, err := Complete(schema, "SELECT o. FROM orders AS o", len("SELECT o."), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}

	for _, test := range []struct {
		result     Result
		label      string
		insertText string
	}{
		{result: tableResult, label: "order-items", insertText: "`order-items`"},
		{result: keywordTableResult, label: "from", insertText: "`from`"},
		{result: fieldResult, label: "billing address", insertText: "`billing address`"},
		{result: fieldResult, label: "FROM", insertText: "`FROM`"},
		{result: fieldResult, label: "order-total", insertText: "`order-total`"},
		{result: fieldResult, label: "tick`value", insertText: "`tick``value`"},
	} {
		suggestion, ok := findSuggestion(test.result.Suggestions, test.label)
		if !ok || suggestion.InsertText != test.insertText {
			t.Fatalf("suggestion %q = %#v, want insert text %q", test.label, suggestion, test.insertText)
		}
	}
	for _, test := range []struct {
		result Result
		label  string
	}{
		{result: fieldResult, label: "percent%field"},
		{result: unsupportedTableResult, label: "percent%table"},
	} {
		if suggestion, ok := findSuggestion(test.result.Suggestions, test.label); ok {
			t.Fatalf("unsupported suggestion %q = %#v", test.label, suggestion)
		}
	}
}

func TestCompletionPaginationSkipsUnsupportedIdentifiers(t *testing.T) {
	tables := make(map[string]catalog.Table, PageSize+2)
	for index := range PageSize + 1 {
		name := fmt.Sprintf("table_%02d", index)
		tables[name] = catalog.Table{Name: name, Type: "data_warehouse", Fields: map[string]catalog.Field{}}
	}
	tables["table_%"] = catalog.Table{Name: "table_%", Type: "data_warehouse", Fields: map[string]catalog.Field{}}
	schema := catalog.Prepare(&catalog.Catalog{Tables: tables, Properties: map[string][]catalog.Property{}})
	query := "SELECT * FROM table_"

	first, err := Complete(schema, query, len(query), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	second, err := Complete(schema, query, len(query), PositionEncodingUTF8, first.NextCursor)
	if err != nil {
		t.Fatal(err)
	}
	if first.Total != PageSize+1 || len(first.Suggestions) != PageSize || first.NextCursor == "" {
		t.Fatalf("first page = %#v", first)
	}
	if second.Total != PageSize+1 || len(second.Suggestions) != 1 || second.NextCursor != "" {
		t.Fatalf("second page = %#v", second)
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
		excluded   []string
		total      int
	}{
		{name: "function in select", query: "SELECT cou FROM orders", position: len("SELECT cou"), label: "count", kind: "function", insertText: "count()"},
		{name: "embedded function in select", query: "SELECT geoD FROM orders", position: len("SELECT geoD"), label: "geoDistance", kind: "function", insertText: "geoDistance()"},
		{name: "function in where", query: "SELECT * FROM orders WHERE coa", position: len("SELECT * FROM orders WHERE coa"), label: "coalesce", kind: "function", insertText: "coalesce()"},
		{name: "operator after field", query: "SELECT * FROM orders WHERE amount ", position: len("SELECT * FROM orders WHERE amount "), label: "=", kind: "operator", insertText: "=", excluded: []string{"AND"}},
		{name: "boolean after predicate", query: "SELECT * FROM orders WHERE amount > 0 ", position: len("SELECT * FROM orders WHERE amount > 0 "), label: "AND", kind: "keyword", insertText: "AND", excluded: []string{"="}},
		{name: "between separator", query: "SELECT * FROM orders WHERE amount BETWEEN 1 ", position: len("SELECT * FROM orders WHERE amount BETWEEN 1 "), label: "AND", kind: "keyword", insertText: "AND", excluded: []string{"OR", "GROUP BY", "ORDER BY", "LIMIT"}, total: 1},
		{name: "between unfinished arithmetic expression", query: "SELECT * FROM orders WHERE amount BETWEEN 1 + cou", position: len("SELECT * FROM orders WHERE amount BETWEEN 1 + cou"), label: "count", kind: "function", insertText: "count()", excluded: []string{"AND"}},
		{name: "between unfinished function call", query: "SELECT * FROM orders WHERE amount BETWEEN toDate(amo", position: len("SELECT * FROM orders WHERE amount BETWEEN toDate(amo"), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between unfinished interval", query: "SELECT * FROM orders WHERE amount BETWEEN INTERVAL ", position: len("SELECT * FROM orders WHERE amount BETWEEN INTERVAL "), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between interval missing unit", query: "SELECT * FROM orders WHERE amount BETWEEN INTERVAL 1 ", position: len("SELECT * FROM orders WHERE amount BETWEEN INTERVAL 1 "), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between complete interval", query: "SELECT * FROM orders WHERE amount BETWEEN INTERVAL 1 DAY ", position: len("SELECT * FROM orders WHERE amount BETWEEN INTERVAL 1 DAY "), label: "AND", kind: "keyword", insertText: "AND", total: 1},
		{name: "between nested interval missing unit", query: "SELECT * FROM orders WHERE amount BETWEEN toDate(INTERVAL 1) ", position: len("SELECT * FROM orders WHERE amount BETWEEN toDate(INTERVAL 1) "), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between complete nested interval", query: "SELECT * FROM orders WHERE amount BETWEEN toDate(INTERVAL 1 DAY) ", position: len("SELECT * FROM orders WHERE amount BETWEEN toDate(INTERVAL 1 DAY) "), label: "AND", kind: "keyword", insertText: "AND", total: 1},
		{name: "between unfinished case", query: "SELECT * FROM orders WHERE amount BETWEEN CASE ", position: len("SELECT * FROM orders WHERE amount BETWEEN CASE "), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between unfinished case conjunction", query: "SELECT * FROM orders WHERE amount BETWEEN CASE WHEN amount > 0 AND amo", position: len("SELECT * FROM orders WHERE amount BETWEEN CASE WHEN amount > 0 AND amo"), label: "amount", kind: "field", excluded: []string{"AND"}},
		{name: "between complete case", query: "SELECT * FROM orders WHERE amount BETWEEN CASE WHEN amount > 0 THEN 1 ELSE 0 END ", position: len("SELECT * FROM orders WHERE amount BETWEEN CASE WHEN amount > 0 THEN 1 ELSE 0 END "), label: "AND", kind: "keyword", insertText: "AND", total: 1},
		{name: "field after boolean", query: "SELECT * FROM orders WHERE amount > 0 AND ", position: len("SELECT * FROM orders WHERE amount > 0 AND "), label: "amount", kind: "field"},
		{name: "field after select comma", query: "SELECT amount,  FROM orders", position: len("SELECT amount, "), label: "amount", kind: "field", excluded: []string{"orders"}},
		{name: "double-quoted clause identifier", query: `SELECT "FROM"  FROM orders`, position: len(`SELECT "FROM" `), label: "count", kind: "function", insertText: "count()", excluded: []string{"orders"}},
		{name: "backtick-quoted clause identifier", query: "SELECT `JOIN`  FROM orders", position: len("SELECT `JOIN` "), label: "count", kind: "function", insertText: "count()", excluded: []string{"orders"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			result, err := Complete(testCatalog(), test.query, test.position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if test.total > 0 && result.Total != test.total {
				t.Fatalf("suggestion total = %d, want %d; suggestions = %#v", result.Total, test.total, result.Suggestions)
			}
			suggestion, ok := findSuggestion(result.Suggestions, test.label)
			if !ok || suggestion.Kind != test.kind || suggestion.InsertText != test.insertText {
				t.Fatalf("suggestion %q = %#v; all suggestions = %#v; parse error = %q", test.label, suggestion, result.Suggestions, result.ParseError)
			}
			for _, excluded := range test.excluded {
				if hasSuggestion(result.Suggestions, excluded) {
					t.Fatalf("unexpected suggestion %q in %#v", excluded, result.Suggestions)
				}
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
	prepared := catalog.Prepare(schema)
	query := "SELECT * FROM table_"
	first, err := Complete(prepared, query, len(query), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Suggestions) != PageSize || first.NextCursor == "" {
		t.Fatalf("first page has %d suggestions and cursor %q", len(first.Suggestions), first.NextCursor)
	}
	if first.Total != 30 {
		t.Fatalf("total = %d", first.Total)
	}
	second, err := Complete(prepared, query, len(query), PositionEncodingUTF8, first.NextCursor)
	if err != nil {
		t.Fatal(err)
	}
	if len(second.Suggestions) != 5 || second.NextCursor != "" {
		t.Fatalf("second page has %d suggestions and cursor %q", len(second.Suggestions), second.NextCursor)
	}
	if first.Suggestions[24].Label != "table_24" || second.Suggestions[0].Label != "table_25" {
		t.Fatalf("page boundary is %q then %q", first.Suggestions[24].Label, second.Suggestions[0].Label)
	}
	if _, err := Complete(prepared, query, len(query), PositionEncodingUTF8, "not-a-cursor"); err == nil {
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

func largeContextualCatalog() *catalog.PreparedCatalog {
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
	return catalog.Prepare(schema)
}

func TestCompleteContextualCatalogStaysWithinLatencyBudget(t *testing.T) {
	if os.Getenv("HOGQL_LANGUAGE_SERVICE_ENFORCE_LATENCY_BUDGET") != "1" {
		t.Skip("latency budget requires the dedicated non-race test environment")
	}

	const sampleCount = 20
	const maxAverage = 5 * time.Millisecond
	const maxStandardDeviation = 5 * time.Millisecond

	schema := largeContextualCatalog()
	intervalPrefix := "SELECT * FROM table_0500 WHERE column_10 BETWEEN "
	intervalQuery := intervalPrefix + strings.Repeat("INTERVAL ", ((16<<10)-len(intervalPrefix)-len("1 DAY "))/len("INTERVAL ")) + "1 DAY "
	for _, test := range []struct {
		name           string
		query          string
		position       int
		callsPerSample int
	}{
		{name: "contextual catalog", query: "SELECT countD FROM table_0500", position: len("SELECT countD"), callsPerSample: 100},
		{name: "adversarial interval expression", query: intervalQuery, position: len(intervalQuery), callsPerSample: 20},
	} {
		t.Run(test.name, func(t *testing.T) {
			for range test.callsPerSample {
				if _, err := Complete(schema, test.query, test.position, PositionEncodingUTF8, ""); err != nil {
					t.Fatal(err)
				}
			}
			durations := make([]float64, sampleCount)
			for sample := range sampleCount {
				startedAt := time.Now()
				for range test.callsPerSample {
					if _, err := Complete(schema, test.query, test.position, PositionEncodingUTF8, ""); err != nil {
						t.Fatal(err)
					}
				}
				durations[sample] = float64(time.Since(startedAt)) / float64(test.callsPerSample)
			}

			var total float64
			for _, duration := range durations {
				total += duration
			}
			average := total / sampleCount
			var squaredDifferences float64
			for _, duration := range durations {
				difference := duration - average
				squaredDifferences += difference * difference
			}
			standardDeviation := math.Sqrt(squaredDifferences / sampleCount)
			if time.Duration(average) > maxAverage || time.Duration(standardDeviation) > maxStandardDeviation {
				t.Fatalf(
					"completion latency average = %s (max %s), standard deviation = %s (max %s)",
					time.Duration(average),
					maxAverage,
					time.Duration(standardDeviation),
					maxStandardDeviation,
				)
			}
		})
	}
}

func BenchmarkCompleteContextualCatalog(b *testing.B) {
	schema := largeContextualCatalog()
	for _, benchmark := range []struct {
		name     string
		query    string
		position int
	}{
		{name: "operator", query: "SELECT * FROM table_0500 WHERE column_10 ", position: len("SELECT * FROM table_0500 WHERE column_10 ")},
		{name: "function prefix", query: "SELECT countD FROM table_0500", position: len("SELECT countD")},
		{name: "repeated interval", query: "SELECT * FROM table_0500 WHERE column_10 BETWEEN " + strings.Repeat("INTERVAL ", 1000) + "1 DAY ", position: len("SELECT * FROM table_0500 WHERE column_10 BETWEEN ") + len("INTERVAL ")*1000 + len("1 DAY ")},
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
