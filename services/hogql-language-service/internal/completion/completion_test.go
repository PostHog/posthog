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
	"unicode/utf16"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/querylimits"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

func testCatalog() *catalog.PreparedCatalog {
	return catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"events": {Name: "events", Type: "posthog", Fields: map[string]catalog.Field{
			"uuid": {Name: "uuid", Type: "string"}, "event": {Name: "event", Type: "string"},
			"properties": {Name: "properties", Type: "json"}, "timestamp": {Name: "timestamp", Type: "datetime"},
		}},
		"Events": {Name: "Events", Type: "data_warehouse", Fields: map[string]catalog.Field{
			"custom_field": {Name: "custom_field", Type: "string"}, "properties": {Name: "properties", Type: "json"},
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
		"event":   {{Name: "$browser", ValueType: "String"}, {Name: "$geo_city", ValueType: "String"}, {Name: "$geo_country", ValueType: "String"}, {Name: "$Geo_Region", ValueType: "String"}},
		"person":  {{Name: "$geo_city", ValueType: "String"}, {Name: "email", ValueType: "String"}},
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

func TestTableAliasesUseCanonicalPropertyOrigins(t *testing.T) {
	properties := map[string][]catalog.Property{
		"event":  {{Name: "$browser", ValueType: "String"}},
		"person": {{Name: "email", ValueType: "String"}},
	}
	for _, test := range []struct {
		name     string
		tables   map[string]catalog.Table
		aliases  map[string]string
		query    string
		expected string
		excluded string
	}{
		{
			name:     "ordinary alias",
			tables:   map[string]catalog.Table{"events": {Fields: map[string]catalog.Field{"properties": {Type: "json"}}}},
			aliases:  map[string]string{"legacy_events": "events"},
			query:    "SELECT legacy_events.properties.$br FROM legacy_events",
			expected: "$browser",
		},
		{
			name:     "misleading person alias",
			tables:   map[string]catalog.Table{"events": {Fields: map[string]catalog.Field{"properties": {Type: "json"}}}},
			aliases:  map[string]string{"persons": "events"},
			query:    "SELECT persons.properties.$br FROM persons",
			expected: "$browser",
			excluded: "email",
		},
		{
			name:     "event-like warehouse alias",
			tables:   map[string]catalog.Table{"warehouse_records": {Fields: map[string]catalog.Field{"properties": {Type: "json"}}}},
			aliases:  map[string]string{"events": "warehouse_records"},
			query:    "SELECT events.properties.$br FROM events",
			excluded: "$browser",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			prepared := catalog.Prepare(&catalog.Catalog{Tables: test.tables, TableAliases: test.aliases, Properties: properties})
			result, err := Complete(prepared, test.query, strings.Index(test.query, " FROM "), PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if test.expected != "" && !hasSuggestion(result.Suggestions, test.expected) {
				t.Fatalf("query %q returned %#v", test.query, result)
			}
			if test.excluded != "" && hasSuggestion(result.Suggestions, test.excluded) {
				t.Fatalf("query %q returned excluded property %#v", test.query, result)
			}
		})
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

func TestCompletesFieldsForCollidingNormalizedTableReferences(t *testing.T) {
	fieldTable := func(name, field string) catalog.Table {
		return catalog.Table{Name: name, Type: "data_warehouse", Fields: map[string]catalog.Field{field: {Name: field, Type: "string"}}}
	}
	for _, test := range []struct {
		name    string
		catalog *catalog.Catalog
	}{
		{
			name: "canonical tables",
			catalog: &catalog.Catalog{Tables: map[string]catalog.Table{
				"a.b.c_d": fieldTable("a.b.c_d", "left_field"),
				"a.b_c.d": fieldTable("a.b_c.d", "right_field"),
			}},
		},
		{
			name: "alias and canonical table",
			catalog: &catalog.Catalog{
				Tables: map[string]catalog.Table{
					"left_target": fieldTable("left_target", "left_field"),
					"a.b_c.d":     fieldTable("a.b_c.d", "right_field"),
				},
				TableAliases: map[string]string{"a.b.c_d": "left_target"},
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			test.catalog.Properties = map[string][]catalog.Property{}
			prepared := catalog.Prepare(test.catalog)
			query := "SELECT l. FROM a.b.c_d AS l JOIN a.b_c.d AS r ON 1 = 1"
			left, err := Complete(prepared, query, len("SELECT l."), PositionEncodingUTF8, "")
			if err != nil || len(left.Suggestions) != 1 || left.Suggestions[0].Label != "left_field" {
				t.Fatalf("left completion = %#v, error = %v", left, err)
			}
			query = "SELECT r. FROM a.b.c_d AS l JOIN a.b_c.d AS r ON 1 = 1"
			right, err := Complete(prepared, query, len("SELECT r."), PositionEncodingUTF8, "")
			if err != nil || len(right.Suggestions) != 1 || right.Suggestions[0].Label != "right_field" {
				t.Fatalf("right completion = %#v, error = %v", right, err)
			}
		})
	}
}

func TestCompletesTablesAfterFrom(t *testing.T) {
	for _, test := range []struct {
		name, query string
		tables      map[string]string
	}{
		{"catalog", "SELECT * FROM ord|", map[string]string{"orders": "data_warehouse"}},
		{"cte from", "WITH recent AS (SELECT event FROM events) SELECT * FROM rec|", map[string]string{"recent": "CTE"}},
		{"cte join", "WITH recent AS (SELECT event FROM events) SELECT * FROM events JOIN rec| ON 1 = 1", map[string]string{"recent": "CTE"}},
		{"cte comma", "WITH recent AS (SELECT event FROM events) SELECT * FROM events, rec|", map[string]string{"recent": "CTE"}},
		{"catalog and cte", "WITH order_summary AS (SELECT event FROM events) SELECT * FROM ord|", map[string]string{"orders": "data_warehouse", "order_summary": "CTE"}},
		{"case-variant catalog tables", "SELECT * FROM EV|", map[string]string{"Events": "data_warehouse", "events": "posthog"}},
		{"case-variant catalog and CTE", "WITH Orders AS (SELECT event FROM events) SELECT * FROM ord|", map[string]string{"Orders": "CTE", "orders": "data_warehouse"}},
		{"unicode prefix", "WITH `Σ` AS (SELECT event FROM events) SELECT * FROM ς|", map[string]string{"Σ": "CTE"}},
		{"case-variant nested CTEs", "WITH recent AS (SELECT event FROM events) SELECT * FROM (WITH Recent AS (SELECT uuid FROM events) SELECT * FROM rec|) AS s", map[string]string{"Recent": "CTE", "recent": "CTE"}},
		{"outer visible", "WITH recent AS (SELECT event FROM events) SELECT * FROM (SELECT * FROM rec|) AS s", map[string]string{"recent": "CTE"}},
		{"previous cte", "WITH recent AS (SELECT event FROM events), recent_next AS (SELECT * FROM rec|) SELECT * FROM recent_next", map[string]string{"recent": "CTE"}},
		{"no self or later cte", "WITH recent AS (SELECT * FROM rec|), recent_next AS (SELECT event FROM events) SELECT * FROM recent", nil},
		{"no sibling cte", "SELECT * FROM (WITH recent AS (SELECT event FROM events) SELECT * FROM recent) AS a JOIN (SELECT * FROM rec|) AS b ON 1 = 1", nil},
		{"no previous statement", "WITH recent AS (SELECT event FROM events) SELECT * FROM recent; SELECT * FROM rec|", nil},
		{"no scalar alias", "WITH 1 AS recent SELECT * FROM rec|", nil},
		{"malformed cte", "WITH recent AS (SELECT event FROM events SELECT * FROM rec|", nil},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.query, '|')
			query := strings.Replace(test.query, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if len(result.Suggestions) != len(test.tables) || result.Total != len(test.tables) {
				t.Fatalf("result = %#v, want tables %#v", result, test.tables)
			}
			seen := map[string]bool{}
			for _, suggestion := range result.Suggestions {
				detail, exists := test.tables[suggestion.Label]
				if !exists || seen[suggestion.Label] || suggestion.Kind != "table" || suggestion.Detail != detail {
					t.Fatalf("unexpected suggestion %#v, want tables %#v", suggestion, test.tables)
				}
				seen[suggestion.Label] = true
			}
		})
	}
}

func TestCompletesDottedTablePaths(t *testing.T) {
	prepared := catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{
			"postgres.demo.orders":       {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
			"postgres.demo.order items":  {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
			"events.properties.archive":  {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
			"persons.properties.archive": {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		},
		TableAliases: map[string]string{"POSTGRES.demo.orders": "postgres.demo.orders"},
		Properties: map[string][]catalog.Property{
			"event":  {{Name: "$browser", ValueType: "String"}},
			"person": {{Name: "email", ValueType: "String"}},
		},
	})
	for _, test := range []struct {
		name     string
		source   string
		encoding PositionEncoding
		expected *Suggestion
	}{
		{name: "namespace", source: "SELECT * FROM postgres.|", expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "demo.orders"}},
		{name: "leaf", source: "SELECT * FROM postgres.demo.or|", expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "orders"}},
		{name: "join", source: "SELECT * FROM events JOIN postgres.demo.or| ON 1 = 1", expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "orders"}},
		{name: "alias exact namespace case", source: "SELECT * FROM POSTGRES.demo.or|", expected: &Suggestion{Label: "POSTGRES.demo.orders", Detail: "postgres.demo.orders", InsertText: "orders"}},
		{name: "leaf prefix case is replaced", source: "SELECT * FROM postgres.demo.OR|", expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "orders"}},
		{name: "wrong namespace case", source: "SELECT * FROM postgres.DEMO.or|"},
		{name: "comma source remains unsupported", source: "SELECT * FROM events, postgres.demo.or|"},
		{name: "event property spelling remains table context", source: "SELECT * FROM events.properties.|", expected: &Suggestion{Label: "events.properties.archive", Detail: "data_warehouse", InsertText: "archive"}},
		{name: "person property spelling remains table context", source: "SELECT * FROM persons.properties.|", expected: &Suggestion{Label: "persons.properties.archive", Detail: "data_warehouse", InsertText: "archive"}},
		{name: "unicode utf16", source: "SELECT '😀'; SELECT * FROM postgres.demo.or|", encoding: PositionEncodingUTF16, expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "orders"}},
		{name: "midword server cursor", source: "SELECT * FROM postgres.demo.or|suffix", expected: &Suggestion{Label: "postgres.demo.orders", Detail: "data_warehouse", InsertText: "orders"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			bytePosition := strings.IndexByte(test.source, '|')
			query := strings.Replace(test.source, "|", "", 1)
			position := bytePosition
			if test.encoding == "" {
				test.encoding = PositionEncodingUTF8
			}
			if test.encoding == PositionEncodingUTF16 {
				position = len(utf16.Encode([]rune(query[:bytePosition])))
			}
			result, err := Complete(prepared, query, position, test.encoding, "")
			if err != nil {
				t.Fatal(err)
			}
			if test.expected == nil {
				if len(result.Suggestions) != 0 {
					t.Fatalf("result = %#v", result)
				}
				return
			}
			if len(result.Suggestions) != 1 {
				t.Fatalf("result = %#v", result)
			}
			actual := result.Suggestions[0]
			if actual.Label != test.expected.Label || actual.Detail != test.expected.Detail || actual.InsertText != test.expected.InsertText {
				t.Fatalf("suggestion = %#v, want %#v", actual, *test.expected)
			}
		})
	}

	quotedCanonical := catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{
			"postgres.demo.order items": {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		},
		TableAliases: map[string]string{"postgres.demo.order_items": "postgres.demo.order items"},
		Properties:   map[string][]catalog.Property{},
	})
	query := "SELECT * FROM postgres.demo.order"
	result, err := Complete(quotedCanonical, query, len(query), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 1 || result.Suggestions[0].Label != "postgres.demo.order_items" || result.Suggestions[0].InsertText != "order_items" {
		t.Fatalf("quoted canonical alias result = %#v", result)
	}

	cteCatalog := catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"postgres.demo.orders":        {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
		"postgres.demo.catalog_table": {Type: "data_warehouse", Fields: map[string]catalog.Field{}},
	}})
	cteQuery := "WITH `postgres.demo.cte` AS (SELECT 1), `postgres.demo.orders` AS (SELECT 2) SELECT * FROM postgres.demo."
	cteResult, err := Complete(cteCatalog, cteQuery, len(cteQuery), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(cteResult.Suggestions) != 1 || cteResult.Suggestions[0].Label != "postgres.demo.catalog_table" || cteResult.Suggestions[0].InsertText != "catalog_table" {
		t.Fatalf("dotted CTE result = %#v", cteResult)
	}
}

func TestCompletesOneSpellingPerAliasedTableAndHonorsExactCTEShadowing(t *testing.T) {
	prepared := catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{
			"postgres.demo.orders": {Type: "data_warehouse", Fields: map[string]catalog.Field{"id": {Type: "integer"}}},
			"events":               {Type: "posthog", Fields: map[string]catalog.Field{"uuid": {Type: "uuid"}}},
		},
		TableAliases: map[string]string{"demo_postgres_orders": "postgres.demo.orders"},
		Properties:   map[string][]catalog.Property{},
	})
	for _, test := range []struct {
		query    string
		expected []string
	}{
		{query: "SELECT * FROM ", expected: []string{"events", "postgres.demo.orders"}},
		{query: "SELECT * FROM demo_", expected: []string{"demo_postgres_orders"}},
		{query: "WITH demo_postgres_orders AS (SELECT uuid FROM events) SELECT * FROM ", expected: []string{"demo_postgres_orders", "events", "postgres.demo.orders"}},
		{query: "WITH `postgres.demo.orders` AS (SELECT uuid FROM events) SELECT * FROM ", expected: []string{"postgres.demo.orders", "demo_postgres_orders", "events"}},
	} {
		result, err := Complete(prepared, test.query, len(test.query), PositionEncodingUTF8, "")
		if err != nil {
			t.Fatal(err)
		}
		labels := make([]string, len(result.Suggestions))
		for index, suggestion := range result.Suggestions {
			labels[index] = suggestion.Label
		}
		if strings.Join(labels, ",") != strings.Join(test.expected, ",") {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
	}
}

func TestCompletesFieldsForAlias(t *testing.T) {
	type testCase struct {
		name, query string
		fields      []Suggestion
	}
	tests := []testCase{
		{"qualified", "SELECT o.| FROM orders AS o", []Suggestion{{Label: "amount", Detail: "float"}, {Label: "order_id", Detail: "string"}}},
		{"alias is not another source", "SELECT uu| FROM events AS e", []Suggestion{{Label: "uuid", Detail: "string"}}},
		{"self join", "SELECT uu| FROM events AS e JOIN events AS other ON e.uuid = other.uuid", []Suggestion{
			{Label: "uuid", Detail: "string from e", InsertText: "e.uuid"}, {Label: "uuid", Detail: "string from other", InsertText: "other.uuid"},
		}},
		{"physical join", "SELECT prop| FROM events JOIN persons ON 1 = 1", []Suggestion{
			{Label: "properties", Detail: "json from events", InsertText: "events.properties"}, {Label: "properties", Detail: "json from persons", InsertText: "persons.properties"},
		}},
		{"cte and subquery", "WITH recent AS (SELECT uuid FROM events) SELECT uu| FROM recent AS r JOIN (SELECT uuid FROM events) AS s ON 1 = 1", []Suggestion{
			{Label: "uuid", Detail: "string from r", InsertText: "r.uuid"}, {Label: "uuid", Detail: "string from s", InsertText: "s.uuid"},
		}},
		{"cte self join", "WITH recent AS (SELECT uuid FROM events) SELECT uu| FROM recent AS r JOIN recent AS s ON 1 = 1", []Suggestion{
			{Label: "uuid", Detail: "string from r", InsertText: "r.uuid"}, {Label: "uuid", Detail: "string from s", InsertText: "s.uuid"},
		}},
		{"quoted qualifier", "SELECT uu| FROM events AS `recent.items` JOIN events AS `FROM` ON 1 = 1", []Suggestion{
			{Label: "uuid", Detail: "string from `FROM`", InsertText: "`FROM`.uuid"}, {Label: "uuid", Detail: "string from `recent.items`", InsertText: "`recent.items`.uuid"},
		}},
		{"dotted cte", "WITH `recent.items` AS (SELECT uuid FROM events) SELECT uu| FROM `recent.items` JOIN events AS e ON 1 = 1", []Suggestion{
			{Label: "uuid", Detail: "string from `recent.items`", InsertText: "`recent.items`.uuid"}, {Label: "uuid", Detail: "string from e", InsertText: "e.uuid"},
		}},
		{"warehouse qualifier", "WITH recent AS (SELECT uuid AS synced_id FROM events) SELECT synced_| FROM postgres.synced.orders JOIN recent ON 1 = 1", []Suggestion{
			{Label: "synced_id", Detail: "string from postgres__synced__orders", InsertText: "postgres__synced__orders.synced_id"}, {Label: "synced_id", Detail: "string from recent", InsertText: "recent.synced_id"},
		}},
		{"quoted warehouse segment", "WITH recent AS (SELECT uuid AS synced_id FROM events) SELECT synced_| FROM `postgres.synced`.orders JOIN recent ON 1 = 1", []Suggestion{
			{Label: "synced_id", Detail: "string from `postgres.synced__orders`", InsertText: "`postgres.synced__orders`.synced_id"}, {Label: "synced_id", Detail: "string from recent", InsertText: "recent.synced_id"},
		}},
		{"quoted field", "WITH t AS (SELECT uuid AS `user id` FROM events) SELECT us| FROM t AS a JOIN t AS b ON 1 = 1", []Suggestion{
			{Label: "user id", Detail: "string from a", InsertText: "a.`user id`"}, {Label: "user id", Detail: "string from b", InsertText: "b.`user id`"},
		}},
		{"unknown expression type", "WITH t AS (SELECT count() AS total FROM events) SELECT tot| FROM t AS a JOIN t AS b ON 1 = 1", []Suggestion{
			{Label: "total", Detail: "from a", InsertText: "a.total"}, {Label: "total", Detail: "from b", InsertText: "b.total"},
		}},
		{"case-folded fields", "WITH a AS (SELECT uuid AS shared FROM events), b AS (SELECT uuid AS SHARED FROM events) SELECT sha| FROM a JOIN b ON 1 = 1", []Suggestion{
			{Label: "SHARED", Detail: "string from b", InsertText: "b.SHARED"}, {Label: "shared", Detail: "string from a", InsertText: "a.shared"},
		}},
		{"select alias precedence", "SELECT e.event AS uuid FROM events AS e JOIN events AS other ON 1 = 1 ORDER BY uu|", []Suggestion{{Label: "uuid", Detail: "string"}}},
		{"case-sensitive select alias precedence", "SELECT e.properties AS UUID FROM events AS e JOIN events AS other ON 1 = 1 ORDER BY uu|", []Suggestion{
			{Label: "UUID", Detail: "json"}, {Label: "uuid", Detail: "string from e", InsertText: "e.uuid"}, {Label: "uuid", Detail: "string from other", InsertText: "other.uuid"},
		}},
		{"case-variant relation aliases", "SELECT prop| FROM events AS e JOIN persons AS E ON 1 = 1", []Suggestion{
			{Label: "properties", Detail: "json from E", InsertText: "E.properties"}, {Label: "properties", Detail: "json from e", InsertText: "e.properties"},
		}},
		{"qualified join stays unqualified", "SELECT e.uu| FROM events AS e JOIN events AS other ON 1 = 1", []Suggestion{{Label: "uuid", Detail: "string"}}},
		{"nested alias shadow", "SELECT * FROM events AS e WHERE uuid IN (SELECT uu| FROM events AS e)", []Suggestion{{Label: "uuid", Detail: "string"}}},
		{"cte scope isolation", "WITH t AS (SELECT uu| FROM events AS e) SELECT * FROM t JOIN events AS other ON 1 = 1", []Suggestion{{Label: "uuid", Detail: "string"}}},
		{"subquery scope isolation", "SELECT * FROM events AS e JOIN (SELECT uu| FROM events AS other) AS s ON 1 = 1", []Suggestion{{Label: "uuid", Detail: "string"}}},
	}
	var sources []string
	var fields []Suggestion
	for index := range PageSize + 2 {
		alias := fmt.Sprintf("source_%02d", index)
		sources = append(sources, "events AS "+alias)
		fields = append(fields, Suggestion{Label: "uuid", Detail: "string from " + alias, InsertText: alias + ".uuid"})
	}
	tests = append(tests, testCase{"joined pagination", "SELECT uu| FROM " + strings.Join(sources, " CROSS JOIN "), fields})
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.query, '|')
			query := strings.Replace(test.query, "|", "", 1)
			var fields []Suggestion
			cursor := ""
			for {
				result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, cursor)
				if err != nil || result.ParseError != "" || len(result.Suggestions) > PageSize {
					t.Fatalf("result = %#v, err = %v", result, err)
				}
				for _, suggestion := range result.Suggestions {
					if suggestion.Kind == "field" {
						fields = append(fields, suggestion)
					}
				}
				cursor = result.NextCursor
				if cursor == "" {
					break
				}
				if len(fields) >= len(test.fields) {
					t.Fatalf("unexpected next page: %#v", result)
				}
			}
			if len(fields) != len(test.fields) {
				t.Fatalf("fields = %#v, want %#v", fields, test.fields)
			}
			for index, expected := range test.fields {
				actual := fields[index]
				if actual.Label != expected.Label || actual.Detail != expected.Detail || actual.InsertText != expected.InsertText {
					t.Errorf("field = %#v, want %#v", actual, expected)
				}
				if actual.InsertText != "" {
					start := strings.LastIndexByte(query[:position], ' ') + 1
					completed := query[:start] + actual.InsertText + query[position:]
					if checked := validation.Validate(testCatalog(), completed); !checked.Valid {
						t.Errorf("inserted query %q is invalid: %#v", completed, checked)
					}
				}
				if index > 0 && fields[index-1].SortText >= actual.SortText {
					t.Errorf("sort keys disagree with page order: %#v", fields)
				}
			}
		})
	}
}

func TestRecoversCTEBindingsForIncompleteOuterClause(t *testing.T) {
	for _, test := range []struct {
		name, source, label, detail string
		encoding                    PositionEncoding
	}{
		{name: "cursor in select", source: "WITH recent AS (SELECT uuid, properties FROM events) SELECT recent.pro| FROM recent WHERE (", label: "properties", detail: "json"},
		{name: "cursor in predicate", source: "WITH recent AS (SELECT uuid, properties FROM events) SELECT uuid FROM recent WHERE (recent.pro|", label: "properties", detail: "json"},
		{name: "chain alias and renamed field", source: "WITH base AS (SELECT uuid, timestamp FROM events), recent AS (SELECT uuid, timestamp AS happened_at FROM base) SELECT r.hap| FROM recent AS r WHERE (", label: "happened_at", detail: "datetime"},
		{name: "wildcard", source: "WITH recent AS (SELECT * FROM events) SELECT recent.uu| FROM recent WHERE uuid =", label: "uuid", detail: "string"},
		{name: "unqualified chain field", source: "WITH base AS (SELECT uuid FROM events), recent AS (SELECT uuid FROM base) SELECT uu| FROM recent WHERE (", label: "uuid", detail: "string"},
		{name: "quoted exact case", source: "WITH `Recent` AS (SELECT uuid AS `EventID` FROM events) SELECT R.Eve| FROM `Recent` AS R WHERE (", label: "EventID", detail: "string"},
		{name: "prewhere", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent PREWHERE (", label: "uuid", detail: "string"},
		{name: "group by", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent GROUP BY (", label: "uuid", detail: "string"},
		{name: "having", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent HAVING (", label: "uuid", detail: "string"},
		{name: "order by", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent ORDER BY (", label: "uuid", detail: "string"},
		{name: "limit", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent LIMIT (", label: "uuid", detail: "string"},
		{name: "comments and keyword strings", source: "WITH recent AS (SELECT uuid FROM events WHERE event = 'FROM WHERE'), /* SELECT FROM */ next AS (SELECT uuid FROM recent) SELECT next.uu| FROM next WHERE (", label: "uuid", detail: "string"},
		{name: "unicode utf8", source: "WITH `Σ` AS (SELECT uuid FROM events) SELECT '😀', `Σ`.uu| FROM `Σ` WHERE (", label: "uuid", detail: "string", encoding: PositionEncodingUTF8},
		{name: "unicode utf16", source: "WITH `Σ` AS (SELECT uuid FROM events) SELECT '😀', `Σ`.uu| FROM `Σ` WHERE (", label: "uuid", detail: "string", encoding: PositionEncodingUTF16},
	} {
		t.Run(test.name, func(t *testing.T) {
			bytePosition := strings.IndexByte(test.source, '|')
			query := strings.Replace(test.source, "|", "", 1)
			position := bytePosition
			if test.encoding == "" {
				test.encoding = PositionEncodingUTF8
			}
			if test.encoding == PositionEncodingUTF16 {
				position = len(utf16.Encode([]rune(query[:bytePosition])))
			}
			result, err := Complete(testCatalog(), query, position, test.encoding, "")
			if err != nil {
				t.Fatal(err)
			}
			if result.ParseError == "" {
				t.Fatal("expected the original incomplete query to retain its parse error")
			}
			suggestion, ok := findSuggestion(result.Suggestions, test.label)
			if !ok || suggestion.Detail != test.detail {
				t.Fatalf("result = %#v", result)
			}
		})
	}
}

func TestIncompleteOuterQueryRemainsInvalidForValidation(t *testing.T) {
	for _, suffix := range []string{"(", "/* unfinished"} {
		t.Run(suffix, func(t *testing.T) {
			incomplete := "WITH recent AS (SELECT uuid FROM events) SELECT recent.uuid FROM recent WHERE " + suffix
			checked := validation.Validate(testCatalog(), incomplete)
			if checked.Valid || len(checked.Diagnostics) != 1 || checked.Diagnostics[0].Code != "syntax_error" {
				t.Fatalf("validation accepted the incomplete source: %#v", checked)
			}
		})
	}
}

func TestIncompleteOuterRecoveryKeepsSelectAliasVisibility(t *testing.T) {
	for _, test := range []struct {
		name, source, expected, excluded string
	}{
		{name: "where sees prior alias", source: "WITH recent AS (SELECT uuid FROM events) SELECT uuid AS event_id FROM recent WHERE (eve|", expected: "event_id"},
		{name: "earlier select item does not see later alias", source: "WITH recent AS (SELECT uuid FROM events) SELECT eve|, uuid AS event_id FROM recent WHERE (", excluded: "event_id"},
		{name: "from does not see select alias", source: "WITH recent AS (SELECT uuid FROM events) SELECT uuid AS event_id FROM eve| WHERE (", excluded: "event_id"},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.source, '|')
			query := strings.Replace(test.source, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if test.expected != "" {
				if _, ok := findSuggestion(result.Suggestions, test.expected); !ok {
					t.Fatalf("result = %#v", result)
				}
			}
			if test.excluded != "" {
				if _, ok := findSuggestion(result.Suggestions, test.excluded); ok {
					t.Fatalf("result leaked %q: %#v", test.excluded, result)
				}
			}
		})
	}
}

func TestRecoversPropertyOriginsForIncompleteOuterClause(t *testing.T) {
	for _, test := range []struct {
		name, source, expected, excluded string
	}{
		{name: "event property", source: "WITH unused AS (SELECT properties AS props FROM persons), recent AS (SELECT properties AS props FROM events) SELECT recent.props.$geo_c| FROM recent WHERE uuid =", expected: "$geo_country", excluded: "email"},
		{name: "person property", source: "WITH unused AS (SELECT properties AS props FROM events), recent AS (SELECT properties AS props FROM persons) SELECT recent.props.$geo_c| FROM recent WHERE id =", expected: "$geo_city", excluded: "$geo_country"},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.source, '|')
			query := strings.Replace(test.source, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if _, ok := findSuggestion(result.Suggestions, test.expected); result.ParseError == "" || !ok {
				t.Fatalf("result = %#v", result)
			}
			if _, ok := findSuggestion(result.Suggestions, test.excluded); ok {
				t.Fatalf("result leaked %q: %#v", test.excluded, result)
			}
		})
	}
}

func TestDoesNotRecoverUnsupportedIncompleteCTEScopes(t *testing.T) {
	for _, test := range []struct {
		name, source, excluded string
	}{
		{name: "damaged cte", source: "WITH recent AS (SELECT uuid FROM events WHERE ( SELECT recent.uu| FROM recent WHERE (", excluded: "uuid"},
		{name: "missing cte close", source: "WITH recent AS (SELECT uuid FROM events SELECT recent.uu| FROM recent WHERE (", excluded: "uuid"},
		{name: "cursor in cte", source: "WITH recent AS (SELECT uu| FROM events) SELECT * FROM recent WHERE (", excluded: "uuid"},
		{name: "nested outer select", source: "WITH recent AS (SELECT uuid FROM events) SELECT * FROM (SELECT recent.uu| FROM recent) AS nested WHERE (", excluded: "uuid"},
		{name: "incomplete join source", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent JOIN WHERE (", excluded: "uuid"},
		{name: "incomplete join condition", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent JOIN events ON ( WHERE (", excluded: "uuid"},
		{name: "set operation", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent UNION SELECT uuid FROM events WHERE (", excluded: "uuid"},
		{name: "multiple statements", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent; SELECT * FROM events WHERE (", excluded: "uuid"},
		{name: "scalar with alias", source: "WITH 1 AS recent SELECT events.uu| FROM events WHERE (", excluded: "uuid"},
		{name: "unterminated comment after cursor", source: "WITH recent AS (SELECT uuid FROM events) SELECT recent.uu| FROM recent WHERE /* unfinished", excluded: "uuid"},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.source, '|')
			query := strings.Replace(test.source, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if result.ParseError == "" {
				t.Fatalf("incomplete query lost its parse error: %#v", result)
			}
			if _, ok := findSuggestion(result.Suggestions, test.excluded); ok {
				t.Fatalf("result recovered unsupported scope: %#v", result)
			}
		})
	}
}

func TestCompletesScopedProjections(t *testing.T) {
	for _, test := range []struct {
		name, query string
		fields      map[string]string
	}{
		{"cte", "WITH t AS (SELECT order_id, amount AS total FROM orders) SELECT t.| FROM t", map[string]string{"order_id": "string", "total": "float"}},
		{"boolean literal type", "WITH t AS (SELECT TRUE AS enabled FROM events) SELECT t.| FROM t", map[string]string{"enabled": "boolean"}},
		{"closed comment after cursor", "WITH t AS (SELECT uuid FROM events) SELECT t.uu| FROM t /* finished */", map[string]string{"uuid": "string"}},
		{"line comment at eof after cursor", "WITH t AS (SELECT uuid FROM events) SELECT t.uu| FROM t -- finished", map[string]string{"uuid": "string"}},
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
		{"unrelated cte preserves properties", "WITH t AS (SELECT 1 AS x) SELECT properties.$geo_ci| FROM events JOIN t ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"unrelated subquery preserves properties", "SELECT properties.$geo_ci| FROM events JOIN (SELECT 1 AS x) AS t ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"renamed properties are unrelated", "WITH t AS (SELECT properties AS attrs FROM events) SELECT properties.$geo_ci| FROM events JOIN t ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"derived properties are ambiguous", "WITH t AS (SELECT properties FROM events) SELECT properties.$geo_ci| FROM events JOIN t ON 1 = 1", nil},
		{"qualified physical properties remain available", "WITH t AS (SELECT properties FROM events) SELECT e.properties.$geo_ci| FROM events AS e JOIN t ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"lowercase alias keeps event properties", "SELECT e.properties.$geo_co| FROM events AS e JOIN persons AS E ON 1 = 1", map[string]string{"$geo_country": "String"}},
		{"uppercase alias keeps person properties", "SELECT E.properties.$geo| FROM events AS e JOIN persons AS E ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"wrong-case alias does not recover event properties", "SELECT E.properties.$geo| FROM events AS e", nil},
		{"exact custom table does not inherit event properties", "SELECT Events.properties.$geo| FROM Events", nil},
		{"nested virtual owner requires exact qualifier", "SELECT e.person.properties.$geo_ci| FROM events AS e", map[string]string{"$geo_city": "String"}},
		{"nested virtual owner rejects wrong-case qualifier", "SELECT E.person.properties.$geo| FROM events AS e", nil},
		{"cte property provenance", "WITH recent AS (SELECT properties FROM events) SELECT recent.properties.$geo_co| FROM recent", map[string]string{"$geo_country": "String"}},
		{"unqualified cte property provenance", "WITH recent AS (SELECT properties FROM events) SELECT properties.$geo_co| FROM recent", map[string]string{"$geo_country": "String"}},
		{"subquery property provenance", "SELECT recent.properties.$geo_co| FROM (SELECT properties FROM events) AS recent", map[string]string{"$geo_country": "String"}},
		{"renamed property provenance", "WITH recent AS (SELECT properties AS props FROM events) SELECT recent.props.$geo_co| FROM recent", map[string]string{"$geo_country": "String"}},
		{"unqualified renamed property provenance", "WITH recent AS (SELECT properties AS props FROM events) SELECT props.$geo_co| FROM recent", map[string]string{"$geo_country": "String"}},
		{"chained property provenance", "WITH a AS (SELECT properties FROM events), b AS (SELECT properties FROM a) SELECT b.properties.$geo_co| FROM b", map[string]string{"$geo_country": "String"}},
		{"wildcard property provenance", "WITH a AS (SELECT * FROM events), b AS (SELECT * FROM a) SELECT b.properties.$geo_co| FROM b", map[string]string{"$geo_country": "String"}},
		{"qualified wildcard property provenance", "WITH a AS (SELECT e.* FROM events AS e JOIN events AS other ON 1 = 1) SELECT a.properties.$geo_co| FROM a", map[string]string{"$geo_country": "String"}},
		{"visible property alias", "SELECT properties AS props, props.$geo_co| FROM events", map[string]string{"$geo_country": "String"}},
		{"property alias chain", "SELECT properties AS props, props AS attrs, attrs.$geo_co| FROM events", map[string]string{"$geo_country": "String"}},
		{"property alias before duplicate", "SELECT properties AS props, props.$geo_co|, uuid AS props FROM events", map[string]string{"$geo_country": "String"}},
		{"property alias after duplicate", "SELECT properties AS props, uuid AS props, props.$geo| FROM events", nil},
		{"cte name does not determine provenance", "WITH events AS (SELECT properties FROM persons) SELECT events.properties.$geo| FROM events", map[string]string{"$geo_city": "String"}},
		{"case-variant CTE property provenance", "WITH t AS (SELECT properties FROM events), T AS (SELECT properties FROM persons) SELECT T.properties.$geo| FROM t JOIN T ON 1 = 1", map[string]string{"$geo_city": "String"}},
		{"lowercase case-variant CTE property provenance", "WITH t AS (SELECT properties FROM events), T AS (SELECT properties FROM persons) SELECT t.properties.$geo_co| FROM t JOIN T ON 1 = 1", map[string]string{"$geo_country": "String"}},
		{"wrong-case CTE has no fields", "WITH t AS (SELECT properties FROM events) SELECT T.| FROM T", nil},
		{"case-variant table fields stay isolated", "SELECT Events.| FROM Events", map[string]string{"custom_field": "string", "properties": "json"}},
		{"ambiguous joined properties", "WITH t AS (SELECT properties FROM events JOIN persons ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"self join properties are ambiguous", "WITH t AS (SELECT properties FROM events AS e JOIN events AS other ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"unaliased self join properties are ambiguous", "WITH t AS (SELECT properties FROM events JOIN events ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"qualified duplicate table name suppresses provenance", "WITH t AS (SELECT events.properties FROM events JOIN events ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"qualified duplicate wildcard suppresses provenance", "WITH t AS (SELECT e.* FROM events AS e JOIN events AS e ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"duplicate qualifier suppresses virtual properties", "SELECT e.person.properties.$geo| FROM events AS e JOIN events AS e ON 1 = 1", nil},
		{"self join wildcard properties are ambiguous", "WITH t AS (SELECT * FROM events AS e JOIN events AS other ON 1 = 1) SELECT t.properties.$geo| FROM t", nil},
		{"inner alias hides outer property source", "SELECT (SELECT properties.$geo| FROM persons AS e) FROM events AS e", map[string]string{"$geo_city": "String"}},
		{"duplicate projected properties", "WITH t AS (SELECT events.properties, events.properties FROM events) SELECT t.properties.$geo| FROM t", nil},
		{"scalar property leaf has no provenance", "WITH t AS (SELECT properties.$geo_city AS city FROM events) SELECT t.city.$geo| FROM t", nil},
		{"boolean literal does not inherit alias provenance", "WITH t AS (SELECT properties AS TRUE, TRUE AS enabled FROM events) SELECT t.enabled.$geo| FROM t", nil},
		{"derived body isolation", "SELECT * FROM orders AS x JOIN (SELECT x.| FROM events) AS s ON 1 = 1", nil},
		{"joined derived sources", "WITH t AS (SELECT event FROM events) SELECT s.| FROM t JOIN (SELECT amount AS total FROM orders) AS s ON 1 = 1", map[string]string{"total": "float"}},
		{"unicode prefix", "WITH t AS (SELECT amount AS `数額` FROM orders) SELECT t.数| FROM t", map[string]string{"数額": "float"}},
		{"earlier select alias", "SELECT amount AS total, tot| FROM orders", map[string]string{"total": "float"}},
		{"alias chain", "SELECT amount AS total, total AS subtotal, sub| FROM orders", map[string]string{"subtotal": "float"}},
		{"alias in where", "SELECT amount AS total FROM orders WHERE tot| > 0", map[string]string{"total": "float"}},
		{"alias in prewhere", "SELECT amount AS total FROM orders PREWHERE tot| > 0", map[string]string{"total": "float"}},
		{"alias in group by", "SELECT amount AS total FROM orders GROUP BY tot|", map[string]string{"total": "float"}},
		{"alias in having", "SELECT sum(amount) AS total FROM orders HAVING tot| > 0", map[string]string{"total": ""}},
		{"alias in order by", "SELECT amount AS total FROM orders ORDER BY tot|", map[string]string{"total": "float"}},
		{"alias in window", "SELECT amount AS total FROM orders WINDOW w AS (PARTITION BY tot|)", map[string]string{"total": "float"}},
		{"alias in limit", "SELECT amount AS total FROM orders LIMIT tot|", map[string]string{"total": "float"}},
		{"alias without from", "SELECT 1 AS total ORDER BY tot|", map[string]string{"total": ""}},
		{"alias shadows field", "SELECT order_id AS amount FROM orders ORDER BY amo|", map[string]string{"amount": "string"}},
		{"qualified field bypasses alias", "SELECT order_id AS amount FROM orders ORDER BY orders.amo|", map[string]string{"amount": "float"}},
		{"projected alias chain", "SELECT s.sub| FROM (SELECT amount AS total, total AS subtotal FROM orders) AS s", map[string]string{"subtotal": "float"}},
		{"no forward select alias", "SELECT tot|, amount AS total FROM orders", nil},
		{"no self select alias", "SELECT tot| AS total FROM orders", nil},
		{"no alias in join", "SELECT amount AS total FROM orders JOIN events ON tot| = 1", nil},
		{"no outer select alias", "SELECT amount AS total FROM orders WHERE order_id IN (SELECT tot| FROM events)", nil},
		{"no inner select alias", "SELECT tot| FROM orders WHERE order_id IN (SELECT event AS total FROM events)", nil},
		{"no select alias across statements", "SELECT amount AS total FROM orders; SELECT tot| FROM events", nil},
		{"no select alias across union", "SELECT amount AS total FROM orders UNION ALL SELECT tot| FROM orders", nil},
		{"union all property isolation", "SELECT properties FROM events UNION ALL SELECT properties.$geo| FROM persons", map[string]string{"$geo_city": "String"}},
		{"union arm local property alias", "SELECT properties AS props FROM events UNION ALL SELECT properties AS props FROM persons WHERE props.$geo| = 'x'", map[string]string{"$geo_city": "String"}},
		{"union arm does not inherit property alias", "SELECT properties AS props FROM events UNION ALL SELECT props.$geo| FROM persons", nil},
		{"union distinct property isolation", "SELECT properties FROM events UNION DISTINCT SELECT properties.$geo| FROM persons", map[string]string{"$geo_city": "String"}},
		{"except property isolation", "SELECT properties FROM events EXCEPT SELECT properties.$geo| FROM persons", map[string]string{"$geo_city": "String"}},
		{"no select alias in cte", "WITH t AS (SELECT tot| FROM orders) SELECT amount AS total FROM orders", nil},
		{"alias property shadow", "SELECT uuid AS properties FROM events ORDER BY properties.$geo_ci|", nil},
		{"alias virtual property shadow", "SELECT uuid AS session FROM events ORDER BY session.properties.$entry|", nil},
		{"qualified properties bypass alias", "SELECT uuid AS properties FROM events ORDER BY events.properties.$geo_ci|", map[string]string{"$geo_city": "String"}},
		{"no recovered select aliases", "SELECT amount AS total FROM orders WHERE tot| >", nil},
		{"recovery preserves relation case", "SELECT Mixed.cus| FROM Events AS Mixed WHERE custom_field =", map[string]string{"custom_field": "string"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			position := strings.IndexByte(test.query, '|')
			query := strings.Replace(test.query, "|", "", 1)
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if test.name == "recovery preserves relation case" && !strings.HasPrefix(result.ParseError, "parse incomplete SQL:") {
				t.Fatalf("parse error = %q, want recovered incomplete SQL error", result.ParseError)
			}
			fields := map[string]string{}
			for _, suggestion := range result.Suggestions {
				if suggestion.Kind == "field" || suggestion.Kind == "property" {
					if _, duplicate := fields[suggestion.Label]; duplicate {
						t.Fatalf("duplicate suggestion: %#v", suggestion)
					}
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

func derivedLookupQuery(sources, aliases, fields, missing int) (string, int) {
	items := make([]string, fields)
	for index := range items {
		items[index] = fmt.Sprintf("amount AS field_%03d", index)
	}
	ctes := []string{"c0 AS (SELECT " + strings.Join(items, ", ") + " FROM orders)"}
	for index := 1; index < sources; index++ {
		ctes = append(ctes, fmt.Sprintf("c%d AS (SELECT * FROM c0)", index))
	}
	from := "c0 AS a0"
	for index := 1; index < aliases; index++ {
		from += fmt.Sprintf(" JOIN c%d AS a%d ON 1 = 1", index%sources, index)
	}
	projections := strings.Repeat("unknown_identifier, ", missing) + "a0.field_000 AS known"
	ctes = append(ctes, "result AS (SELECT "+projections+" FROM "+from+")")
	prefix := "WITH " + strings.Join(ctes, ", ") + " SELECT result."
	return prefix + " FROM result", len(prefix)
}

func TestDerivedLookupWork(t *testing.T) {
	for _, test := range []struct {
		name                              string
		sources, aliases, fields, missing int
		limit                             bool
	}{
		{name: "repeated aliases share one field index", sources: 1, aliases: 512, fields: 256, missing: 256},
		{name: "distinct sources exhaust lookup budget", sources: 128, aliases: 128, fields: 8, missing: 512, limit: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			query, position := derivedLookupQuery(test.sources, test.aliases, test.fields, test.missing)
			if err := querylimits.Validate(query); err != nil {
				t.Fatal(err)
			}
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, "")
			if test.limit {
				if !errors.Is(err, querylimits.ErrFieldLookupTooLarge) || len(result.Suggestions) != 0 {
					t.Fatalf("result = %#v, err = %v", result, err)
				}
			} else if known, ok := findSuggestion(result.Suggestions, "known"); err != nil || !ok || known.Detail != "float" {
				t.Fatalf("result = %#v, err = %v", result, err)
			}
			if test.limit {
				result, err = Complete(testCatalog(), query+" WHERE (", position, PositionEncodingUTF8, "")
				if !errors.Is(err, querylimits.ErrFieldLookupTooLarge) || len(result.Suggestions) != 0 {
					t.Fatalf("incomplete result = %#v, err = %v", result, err)
				}
			}
		})
	}
}

func BenchmarkCompleteDerivedLookups(b *testing.B) {
	query, position := derivedLookupQuery(1, 512, 256, 256)
	schema := testCatalog()
	b.ReportAllocs()
	b.ResetTimer()
	for range b.N {
		if _, err := Complete(schema, query, position, PositionEncodingUTF8, ""); err != nil {
			b.Fatal(err)
		}
	}
}

func TestCompletionFieldLookupWorkBudget(t *testing.T) {
	tables := map[string]catalog.Table{}
	var sources []string
	for index := range 128 {
		name := fmt.Sprintf("source_%d", index)
		tables[name] = catalog.Table{Name: name, Fields: map[string]catalog.Field{
			"amount":                             {Name: "amount", Type: "float"},
			"field_" + strings.Repeat("x", 8192): {Type: "float"},
		}}
		sources = append(sources, name)
	}
	schema := catalog.Prepare(&catalog.Catalog{Tables: tables})
	for _, query := range []string{
		"SELECT " + strings.Repeat("x", 8192) + " AS total FROM " + strings.Join(sources, " CROSS JOIN ") + " ORDER BY tot|",
		"SELECT field_| FROM " + strings.Join(sources, " CROSS JOIN "),
	} {
		position := strings.IndexByte(query, '|')
		query = strings.Replace(query, "|", "", 1)
		if err := querylimits.Validate(query); err != nil {
			t.Fatal(err)
		}
		result, err := Complete(schema, query, position, PositionEncodingUTF8, "")
		if !errors.Is(err, querylimits.ErrFieldLookupTooLarge) || len(result.Suggestions) != 0 {
			t.Fatalf("result = %#v, err = %v", result, err)
		}
	}
}

func TestProjectionPaginationAndLimits(t *testing.T) {
	var items []string
	var names []string
	for index := 0; index < PageSize+2; index++ {
		name := fmt.Sprintf("field_%02d", index)
		if index == PageSize {
			name = names[index-1] + "$x"
		}
		names = append(names, name)
		items = append(items, "amount AS "+name)
	}
	items = append(items, "amount AS field_00")
	for _, source := range []string{
		"WITH t AS (SELECT " + strings.Join(items, ", ") + " FROM orders) SELECT t.| FROM t",
		"SELECT t.| FROM (SELECT " + strings.Join(items, ", ") + " FROM orders) AS t",
		"SELECT " + strings.Join(items[:PageSize+2], ", ") + " FROM orders ORDER BY field_|",
	} {
		position := strings.IndexByte(source, '|')
		query := strings.Replace(source, "|", "", 1)
		cursor := ""
		var fields []string
		previousSortText := ""
		for {
			result, err := Complete(testCatalog(), query, position, PositionEncodingUTF8, cursor)
			if err != nil || result.Total != PageSize+2 || len(result.Suggestions) > PageSize {
				t.Fatalf("result = %#v, err = %v", result, err)
			}
			for _, suggestion := range result.Suggestions {
				if suggestion.SortText <= previousSortText {
					t.Fatalf("query %q: sort key %q does not follow %q", query, suggestion.SortText, previousSortText)
				}
				previousSortText = suggestion.SortText
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
			if name != names[index] {
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
		for _, suffix := range []string{" FROM c14", " FROM c14 WHERE ("} {
			_, err := Complete(testCatalog(), prefix+suffix, len(prefix), PositionEncodingUTF8, "")
			if !errors.Is(err, querylimits.ErrCTEProjectionTooLarge) {
				t.Fatalf("projection %q, suffix %q: err = %v", projection, suffix, err)
			}
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
			"timestamp":       {Name: "timestamp", Type: "datetime"},
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
	aliasQuery := "SELECT o.\"order-total\" AS \"billing total\" FROM orders AS o ORDER BY bill"
	aliasResult, err := Complete(schema, aliasQuery, len(aliasQuery), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	cteQuery := "WITH `recent.items` AS (SELECT * FROM orders), `recent items` AS (SELECT * FROM orders) SELECT * FROM rec"
	cteResult, err := Complete(schema, cteQuery, len(cteQuery), PositionEncodingUTF8, "")
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
		{result: fieldResult, label: "timestamp", insertText: ""},
		{result: aliasResult, label: "billing total", insertText: "`billing total`"},
		{result: cteResult, label: "recent.items", insertText: "`recent.items`"},
		{result: cteResult, label: "recent items", insertText: "`recent items`"},
	} {
		suggestion, ok := findSuggestion(test.result.Suggestions, test.label)
		if !ok || suggestion.InsertText != test.insertText {
			t.Fatalf("suggestion %q = %#v, want insert text %q", test.label, suggestion, test.insertText)
		}
	}
	for _, test := range []struct {
		query, insertText string
	}{
		{"SELECT * FROM orders WHERE 1 = 1 AND tim| > now()", "timestamp"},
		{"SELECT o.tim| FROM orders AS o", "timestamp"},
		{"SELECT tim| FROM orders AS a JOIN orders AS b ON 1 = 1", "a.timestamp"},
	} {
		position := strings.IndexByte(test.query, '|')
		query := strings.Replace(test.query, "|", "", 1)
		result, err := Complete(schema, query, position, PositionEncodingUTF8, "")
		if err != nil {
			t.Fatal(err)
		}
		suggestion, ok := findSuggestion(result.Suggestions, "timestamp")
		insertText := suggestion.InsertText
		if insertText == "" {
			insertText = suggestion.Label
		}
		if !ok || insertText != test.insertText {
			t.Fatalf("query %q: suggestion = %#v, want insertion %q", query, suggestion, test.insertText)
		}
		completed := query[:position-len("tim")] + insertText + query[position:]
		if checked := validation.Validate(schema, completed); !checked.Valid {
			t.Errorf("inserted query %q is invalid: %#v", completed, checked)
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

func TestDoesNotCompleteFieldsForWrongCaseTableReference(t *testing.T) {
	query := "SELECT Orders. FROM Orders"
	result, err := Complete(testCatalog(), query, len("SELECT Orders."), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Suggestions) != 0 {
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
		required   []string
		excluded   []string
		total      int
	}{
		{name: "empty query select", query: "", position: 0, label: "SELECT", kind: "keyword", total: 2},
		{name: "empty query with", query: "", position: 0, label: "WITH", kind: "keyword", total: 2},
		{name: "whitespace query", query: " \n\t\u2003", position: len(" \n\t\u2003"), label: "SELECT", kind: "keyword", total: 2},
		{name: "select prefix", query: "sel", position: 3, label: "SELECT", kind: "keyword", total: 1},
		{name: "with prefix", query: "wi", position: 2, label: "WITH", kind: "keyword", total: 1},
		{name: "after comment", query: "-- example\n", position: len("-- example\n"), label: "WITH", kind: "keyword", total: 2},
		{name: "after statement", query: "SELECT 1; ", position: len("SELECT 1; "), label: "SELECT", kind: "keyword", total: 2},
		{name: "function in select", query: "SELECT cou FROM orders", position: len("SELECT cou"), label: "count", kind: "function", insertText: "count()"},
		{name: "embedded function in select", query: "SELECT geoD FROM orders", position: len("SELECT geoD"), label: "geoDistance", kind: "function", insertText: "geoDistance()"},
		{name: "function in where", query: "SELECT * FROM orders WHERE coa", position: len("SELECT * FROM orders WHERE coa"), label: "coalesce", kind: "function", insertText: "coalesce()"},
		{name: "true after operator", query: "SELECT * FROM orders WHERE amount = tr", position: len("SELECT * FROM orders WHERE amount = tr"), label: "TRUE", kind: "keyword"},
		{name: "false after operator", query: "SELECT * FROM orders WHERE amount = fa", position: len("SELECT * FROM orders WHERE amount = fa"), label: "FALSE", kind: "keyword"},
		{name: "operator after field", query: "SELECT * FROM orders WHERE amount ", position: len("SELECT * FROM orders WHERE amount "), label: "=", kind: "operator", insertText: "=", excluded: []string{"AND"}},
		{name: "boolean after predicate", query: "SELECT * FROM orders WHERE amount > 0 ", position: len("SELECT * FROM orders WHERE amount > 0 "), label: "AND", kind: "keyword", insertText: "AND", excluded: []string{"=", "WHERE"}},
		{name: "where after join predicate", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid ", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "where prefix after join predicate", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid wh", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid wh"), label: "WHERE", kind: "keyword", insertText: "WHERE", total: 1},
		{name: "where after parenthesized join predicate", query: "SELECT * FROM events AS e JOIN events AS other ON (e.uuid = other.uuid) ", position: len("SELECT * FROM events AS e JOIN events AS other ON (e.uuid = other.uuid) "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "no where inside join parentheses", query: "SELECT * FROM events AS e JOIN events AS other ON (e.uuid = other.uuid ", position: len("SELECT * FROM events AS e JOIN events AS other ON (e.uuid = other.uuid "), label: "AND", kind: "keyword", insertText: "AND", excluded: []string{"WHERE"}},
		{name: "no where within join between bounds", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount BETWEEN 1 ", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount BETWEEN 1 "), label: "AND", kind: "keyword", insertText: "AND", total: 1},
		{name: "where after joined ctes before order by", query: "WITH a AS (SELECT uuid FROM events WHERE event = 'demo'), b AS (SELECT uuid FROM events) SELECT a.uuid FROM a LEFT JOIN b ON a.uuid = b.uuid\n\nORDER BY a.uuid", position: len("WITH a AS (SELECT uuid FROM events WHERE event = 'demo'), b AS (SELECT uuid FROM events) SELECT a.uuid FROM a LEFT JOIN b ON a.uuid = b.uuid\n"), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "only boolean continuations after join predicate before later join", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid  JOIN persons AS p ON 1 = 1", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "AND", kind: "keyword", insertText: "AND", required: []string{"OR"}, excluded: []string{"WHERE", "GROUP BY", "ORDER BY", "LIMIT"}, total: 2},
		{name: "comparison and boolean continuations after join expression before later join", query: "SELECT * FROM events AS e JOIN events AS other ON TRUE  JOIN persons AS p ON 1 = 1", position: len("SELECT * FROM events AS e JOIN events AS other ON TRUE "), label: "=", kind: "operator", insertText: "=", required: []string{"AND", "OR"}, excluded: []string{"WHERE", "GROUP BY", "ORDER BY", "LIMIT"}},
		{name: "nested later join does not suppress where", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid  ORDER BY (SELECT 1 FROM events JOIN persons ON 1 = 1)", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "join in comment does not suppress where", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid  /* JOIN persons */ ORDER BY e.uuid", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "join in string does not suppress where", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid  ORDER BY 'JOIN persons'", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "join in later statement does not suppress where", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid ; SELECT * FROM events JOIN persons ON 1 = 1", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "join in next union branch does not suppress where", query: "SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid  UNION ALL SELECT * FROM events JOIN persons ON 1 = 1", position: len("SELECT * FROM events AS e JOIN events AS other ON e.uuid = other.uuid "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "no clauses inside unfinished join case", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 ", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 "), label: "THEN", kind: "keyword", excluded: []string{"WHERE", "GROUP BY", "ORDER BY", "LIMIT"}},
		{name: "function inside unfinished join case", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN cou", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN cou"), label: "count", kind: "function", insertText: "count()", excluded: []string{"WHERE"}},
		{name: "no clauses inside parenthesized join case condition", query: "SELECT * FROM orders AS a JOIN orders AS b ON CASE WHEN (", position: len("SELECT * FROM orders AS a JOIN orders AS b ON CASE WHEN ("), label: "count", kind: "function", insertText: "count()", excluded: []string{"WHERE", "GROUP BY", "ORDER BY", "LIMIT"}},
		{name: "no clauses inside join case function", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN coalesce(", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN coalesce("), label: "count", kind: "function", insertText: "count()", excluded: []string{"WHERE", "GROUP BY", "ORDER BY", "LIMIT"}},
		{name: "inner select keeps its own where", query: "SELECT * FROM orders AS a JOIN orders AS b ON CASE WHEN (SELECT amount FROM orders  )", position: len("SELECT * FROM orders AS a JOIN orders AS b ON CASE WHEN (SELECT amount FROM orders "), label: "WHERE", kind: "keyword"},
		{name: "else inside unfinished join case", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN 1 el", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN 1 el"), label: "ELSE", kind: "keyword", excluded: []string{"WHERE"}, total: 1},
		{name: "end inside nested unfinished join case", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN CASE WHEN a.amount > 0 THEN 1 END ELSE 0 en", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN CASE WHEN a.amount > 0 THEN 1 END ELSE 0 en"), label: "END", kind: "keyword", excluded: []string{"WHERE"}},
		{name: "where after closed join case", query: "SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN 1 ELSE 0 END ", position: len("SELECT * FROM orders AS a JOIN orders AS b ON a.amount = CASE WHEN b.amount > 0 THEN 1 ELSE 0 END "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "where after standalone closed join case", query: "SELECT * FROM events JOIN persons ON CASE WHEN TRUE THEN 1 ELSE 0 END ", position: len("SELECT * FROM events JOIN persons ON CASE WHEN TRUE THEN 1 ELSE 0 END "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "where after true join predicate", query: "SELECT * FROM events JOIN persons ON TRUE ", position: len("SELECT * FROM events JOIN persons ON TRUE "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "where after lowercase false join predicate", query: "SELECT * FROM events JOIN persons ON false ", position: len("SELECT * FROM events JOIN persons ON false "), label: "WHERE", kind: "keyword", insertText: "WHERE"},
		{name: "qualified true stays a field", query: "SELECT * FROM events AS e JOIN persons ON e.TRUE ", position: len("SELECT * FROM events AS e JOIN persons ON e.TRUE "), label: "=", kind: "operator", insertText: "=", excluded: []string{"WHERE"}},
		{name: "quoted true stays an identifier", query: `SELECT * FROM events JOIN persons ON "TRUE" `, position: len(`SELECT * FROM events JOIN persons ON "TRUE" `), label: "=", kind: "operator", insertText: "=", excluded: []string{"WHERE"}},
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
			for _, required := range test.required {
				if !hasSuggestion(result.Suggestions, required) {
					t.Fatalf("missing suggestion %q in %#v", required, result.Suggestions)
				}
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
		"-- sel",
		"/* wi",
		"-- FROM postgres.demo.or",
		"/* FROM postgres.demo.or",
		"SELECT 'FROM postgres.demo.or",
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
	for _, ctePrefix := range []string{"", "WITH table_05 AS (SELECT 1), table_30 AS (SELECT 2) "} {
		t.Run(ctePrefix, func(t *testing.T) {
			input := ctePrefix + query
			var expected []string
			if ctePrefix != "" {
				expected = append(expected, "table_05", "table_30")
			}
			for index := range 30 {
				if ctePrefix == "" || index != 5 {
					expected = append(expected, fmt.Sprintf("table_%02d", index))
				}
			}
			first, err := Complete(prepared, input, len(input), PositionEncodingUTF8, "")
			if err != nil {
				t.Fatal(err)
			}
			if len(first.Suggestions) != PageSize || first.NextCursor == "" || first.Total != len(expected) {
				t.Fatalf("first page = %#v", first)
			}
			second, err := Complete(prepared, input, len(input), PositionEncodingUTF8, first.NextCursor)
			if err != nil {
				t.Fatal(err)
			}
			if len(second.Suggestions) != len(expected)-PageSize || second.NextCursor != "" || second.Total != len(expected) {
				t.Fatalf("second page = %#v", second)
			}
			for index, suggestion := range append(first.Suggestions, second.Suggestions...) {
				if suggestion.Label != expected[index] {
					t.Fatalf("suggestion %d = %#v, want %s", index, suggestion, expected[index])
				}
			}
		})
	}
	if _, err := Complete(prepared, query, len(query), PositionEncodingUTF8, "not-a-cursor"); err == nil {
		t.Fatal("invalid cursor was accepted")
	}
}

func TestAliasCompletionPagesWithoutRepeatingCanonicalTargets(t *testing.T) {
	value := &catalog.Catalog{Tables: map[string]catalog.Table{}, TableAliases: map[string]string{}, Properties: map[string][]catalog.Property{}}
	for index := range 30 {
		canonical := fmt.Sprintf("postgres.demo.table_%02d", index)
		alias := fmt.Sprintf("legacy.demo.table_%02d", index)
		value.Tables[canonical] = catalog.Table{Type: "data_warehouse", Fields: map[string]catalog.Field{}}
		value.TableAliases[alias] = canonical
	}
	prepared := catalog.Prepare(value)
	query := "SELECT * FROM legacy.demo.table_"
	first, err := Complete(prepared, query, len(query), PositionEncodingUTF8, "")
	if err != nil {
		t.Fatal(err)
	}
	second, err := Complete(prepared, query, len(query), PositionEncodingUTF8, first.NextCursor)
	if err != nil {
		t.Fatal(err)
	}
	all := append(first.Suggestions, second.Suggestions...)
	if first.Total != 30 || second.Total != 30 || len(all) != 30 || second.NextCursor != "" {
		t.Fatalf("pages = %#v, %#v", first, second)
	}
	for index, suggestion := range all {
		expectedAlias := fmt.Sprintf("legacy.demo.table_%02d", index)
		expectedCanonical := fmt.Sprintf("postgres.demo.table_%02d", index)
		expectedInsertText := fmt.Sprintf("table_%02d", index)
		if suggestion.Label != expectedAlias || suggestion.Detail != expectedCanonical || suggestion.InsertText != expectedInsertText {
			t.Fatalf("suggestion %d = %#v", index, suggestion)
		}
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
		{name: "joined fields", query: "SELECT column_ FROM table_0500 AS a JOIN table_0500 AS b ON 1 = 1", position: len("SELECT column_"), callsPerSample: 100},
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
		{name: "joined fields", query: "SELECT column_ FROM table_0500 AS a JOIN table_0500 AS b ON 1 = 1", position: len("SELECT column_")},
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
