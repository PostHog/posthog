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
		"event":   {{Name: "$geo_city", ValueType: "String"}, {Name: "café", ValueType: "String"}, {Name: "amount", ValueType: "Numeric"}},
		"person":  {{Name: "$geo_country", ValueType: "String"}},
		"session": {{Name: "$entry_current_url", ValueType: "String"}},
		"group:0": {{Name: "industry", ValueType: "String"}},
	}})
}

func traversalSchema() *catalog.PreparedCatalog {
	return catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{
			"events": {Fields: map[string]catalog.Field{
				"event": {Type: "String"}, "person": {Type: "lazy", Relation: "person"},
				"session": {Type: "lazy", Relation: "session"},
			}},
			"sessions": {Fields: map[string]catalog.Field{"session_id": {Type: "String"}}},
		},
		Relations: map[string]catalog.RelationDefinition{
			"person": {Fields: map[string]catalog.Field{
				"email": {Type: "String"}, "properties": {Type: "JSON", PropertyNamespace: "person"},
				"manager": {Type: "lazy", Relation: "person"}, "payload": {Type: "JSON"},
			}},
			"session": {Table: "sessions"},
		},
		Properties: map[string][]catalog.Property{"person": {{Name: "plan", ValueType: "String"}}},
	})
}

func TestValidateTraversalRelations(t *testing.T) {
	for _, query := range []string{
		"SELECT e.person.email FROM events AS e",
		"SELECT person.email FROM events",
		"SELECT e.person.properties.plan FROM events AS e",
		"SELECT e.person.manager.email FROM events AS e",
		"SELECT e.person.properties.plan.nested FROM events AS e",
		"SELECT e.person.payload.unknown FROM events AS e",
		"SELECT e.session.session_id FROM events AS e",
	} {
		result := Validate(traversalSchema(), query)
		if !result.Valid || strings.Join(result.TableNames, ",") != "events" {
			t.Fatalf("query %q returned %#v", query, result)
		}
	}
	for _, test := range []struct {
		query, code, value string
	}{
		{"SELECT e.person.emali FROM events AS e", "unknown_field", "emali"},
		{"SELECT e.person.properties.paln FROM events AS e", "unknown_property", "paln"},
		{"SELECT e.person.properties.paln.nested FROM events AS e", "unknown_property", "paln"},
		{"SELECT e.person.missing.email FROM events AS e", "unknown_field", "missing"},
	} {
		result := Validate(traversalSchema(), test.query)
		if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != test.code {
			t.Fatalf("query %q returned %#v", test.query, result)
		}
		if got := test.query[result.Diagnostics[0].Start:result.Diagnostics[0].End]; got != test.value {
			t.Fatalf("query %q diagnostic covered %q", test.query, got)
		}
	}
}

func TestValidateNotices(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		schema  *catalog.PreparedCatalog
		notices []struct{ source, message string }
	}{
		{
			name:  "qualified fields and table",
			query: "SELECT e.event, e.timestamp FROM events AS e",
			notices: []struct{ source, message string }{
				{"event", "Field 'event' is of type 'String'"},
				{"timestamp", "Field 'timestamp' is of type 'DateTime'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "cte projection",
			query: "WITH x AS (SELECT event AS kind FROM events) SELECT x.kind FROM x",
			notices: []struct{ source, message string }{
				{"event", "Field 'event' is of type 'String'"},
				{"events", "Table 'events'"},
				{"kind", "Field 'kind' is of type 'String'"},
				{"x", "Table 'x' is a common table expression"},
			},
		},
		{
			name:  "select alias before duplicate",
			query: "SELECT event AS v, v, timestamp AS v FROM events",
			notices: []struct{ source, message string }{
				{"event", "Field 'event' is of type 'String'"},
				{"v", "Field 'v' is of type 'String'"},
				{"timestamp", "Field 'timestamp' is of type 'DateTime'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "property",
			query: "SELECT e.properties.$geo_city FROM events AS e",
			notices: []struct{ source, message string }{
				{"$geo_city", "Event property '$geo_city' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "numeric property",
			query: "SELECT e.properties.amount FROM events AS e",
			notices: []struct{ source, message string }{
				{"amount", "Event property 'amount' is of type 'Float'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:   "traversed property",
			query:  "SELECT e.person.properties.plan FROM events AS e",
			schema: traversalSchema(),
			notices: []struct{ source, message string }{
				{"plan", "Person property 'plan' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "quoted field",
			query: "SELECT `event` FROM events",
			notices: []struct{ source, message string }{
				{"`event`", "Field 'event' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "double-quoted field",
			query: "SELECT \"event\" FROM events",
			notices: []struct{ source, message string }{
				{"\"event\"", "Field 'event' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:   "relation traversal",
			query:  "SELECT e.person.email FROM events AS e",
			schema: traversalSchema(),
			notices: []struct{ source, message string }{
				{"email", "Field 'email' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "unicode offsets",
			query: "SELECT '🐱', event FROM events",
			notices: []struct{ source, message string }{
				{"event", "Field 'event' is of type 'String'"},
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "wildcard",
			query: "SELECT * FROM events",
			notices: []struct{ source, message string }{
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "unknown field",
			query: "SELECT missing FROM events",
			notices: []struct{ source, message string }{
				{"events", "Table 'events'"},
			},
		},
		{
			name:  "unresolved qualifier",
			query: "SELECT missing.event FROM events",
			notices: []struct{ source, message string }{
				{"events", "Table 'events'"},
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			testSchema := test.schema
			if testSchema == nil {
				testSchema = schema()
			}
			result := Validate(testSchema, test.query)
			if len(result.Notices) != len(test.notices) {
				t.Fatalf("notices = %#v", result.Notices)
			}
			for index, expected := range test.notices {
				actual := result.Notices[index]
				if test.query[actual.Start:actual.End] != expected.source || actual.Message != expected.message {
					t.Fatalf("notice %d = %#v, want %q: %q", index, actual, expected.source, expected.message)
				}
			}
		})
	}
}

func TestValidateNoticesUseCanonicalTableAndSkipAmbiguousFields(t *testing.T) {
	aliased := catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{"warehouse_orders": {
			Name: "warehouse_orders", Fields: map[string]catalog.Field{"order_id": {Type: "integer"}},
		}},
		TableAliases: map[string]string{"orders": "warehouse_orders"},
		Properties:   map[string][]catalog.Property{},
	})
	query := "SELECT orders.order_id FROM orders"
	result := Validate(aliased, query)
	if !result.Valid || len(result.Notices) != 2 || result.Notices[0].Message != "Field 'order_id' is of type 'Integer'" || result.Notices[1].Message != "Table 'orders' refers to 'warehouse_orders'" {
		t.Fatalf("alias notices = %#v", result)
	}
	for _, query := range []string{
		"SELECT amount FROM warehouse_orders AS o JOIN warehouse_orders AS p ON o.order_id = p.order_id",
		"WITH x AS (SELECT event AS v, timestamp AS v FROM events) SELECT x.v FROM x",
		"SELECT event AS v, timestamp AS v FROM events ORDER BY v",
	} {
		checked := Validate(schema(), query)
		fieldAt := strings.LastIndex(query, "v")
		if strings.Contains(query, "amount") {
			fieldAt = strings.Index(query, "amount")
		} else if strings.Contains(query, "x.v") {
			fieldAt = strings.Index(query, "x.v") + len("x.")
		}
		for _, notice := range checked.Notices {
			if notice.Start == fieldAt {
				t.Fatalf("ambiguous field has notice in %q: %#v", query, notice)
			}
		}
	}
}

func TestTraversalRelationHopLimit(t *testing.T) {
	parts := make([]string, querylimits.MaxRelationTraversalHops+1)
	for index := range parts {
		parts[index] = "manager"
	}
	query := "SELECT e.person." + strings.Join(parts, ".") + ".email FROM events AS e"
	result := Validate(traversalSchema(), query)
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "query_limit" || result.Diagnostics[0].Message != querylimits.ErrRelationTraversalTooDeep.Error() {
		t.Fatalf("result = %#v", result)
	}
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

func TestValidateCapsNoticesWithoutSuppressingDiagnostics(t *testing.T) {
	fields := strings.Repeat("event, ", querylimits.MaxNotices) + "event"
	valid := Validate(schema(), "SELECT "+fields+" FROM events")
	if !valid.Valid || len(valid.Notices) != querylimits.MaxNotices {
		t.Fatalf("valid result = %#v", valid)
	}

	invalid := Validate(schema(), "SELECT "+fields+", missing FROM events")
	if invalid.Valid || len(invalid.Diagnostics) != 1 || invalid.Diagnostics[0].Code != "unknown_field" || len(invalid.Notices) > querylimits.MaxNotices {
		t.Fatalf("invalid result = %#v", invalid)
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

func TestValidateRelationNamesAreCaseSensitive(t *testing.T) {
	result := Validate(schema(), "SELECT properties FROM Events")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_table" || result.Diagnostics[0].Start != len("SELECT properties FROM ") {
		t.Fatalf("wrong-case table result = %#v", result)
	}

	caseVariants := catalog.Prepare(&catalog.Catalog{Tables: map[string]catalog.Table{
		"events": {Name: "events", Fields: map[string]catalog.Field{
			"properties": {Name: "properties", Type: "json"},
		}},
		"Events": {Name: "Events", Fields: map[string]catalog.Field{
			"custom_field": {Name: "custom_field", Type: "string"},
		}},
		"persons": {Name: "persons", Fields: map[string]catalog.Field{
			"properties": {Name: "properties", Type: "json"},
		}},
	}, Properties: map[string][]catalog.Property{
		"event":  {{Name: "$geo_city", ValueType: "String"}},
		"person": {{Name: "$geo_country", ValueType: "String"}},
	}})

	result = Validate(caseVariants, "SELECT events.properties, Events.custom_field FROM events JOIN Events ON 1 = 1")
	if !result.Valid || len(result.Diagnostics) != 0 || strings.Join(result.TableNames, ",") != "events,Events" {
		t.Fatalf("case-variant table result = %#v", result)
	}

	for _, test := range []struct{ query, suggestion string }{
		{"SELECT e.properties.$geo_cty FROM events AS e JOIN persons AS E ON 1 = 1", "$geo_city"},
		{"SELECT E.properties.$geo_contry FROM events AS e JOIN persons AS E ON 1 = 1", "$geo_country"},
		{"WITH t AS (SELECT properties FROM events), T AS (SELECT properties FROM persons) SELECT t.properties.$geo_cty FROM t JOIN T ON 1 = 1", "$geo_city"},
		{"WITH t AS (SELECT properties FROM events), T AS (SELECT properties FROM persons) SELECT T.properties.$geo_contry FROM t JOIN T ON 1 = 1", "$geo_country"},
	} {
		checked := Validate(caseVariants, test.query)
		if checked.Valid || len(checked.Diagnostics) != 1 || checked.Diagnostics[0].Code != "unknown_property" || len(checked.Diagnostics[0].Suggestions) == 0 || checked.Diagnostics[0].Suggestions[0].Label != test.suggestion {
			t.Fatalf("query %q returned %#v", test.query, checked)
		}
	}

	result = Validate(caseVariants, "WITH t AS (SELECT properties FROM events) SELECT properties FROM T")
	if result.Valid || len(result.Diagnostics) != 1 || result.Diagnostics[0].Code != "unknown_table" || result.Diagnostics[0].Start != len("WITH t AS (SELECT properties FROM events) SELECT properties FROM ") {
		t.Fatalf("wrong-case CTE result = %#v", result)
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
		{query: "SELECT TRUE, false FROM events WHERE TRUE AND false = FALSE", tableName: "events"},
		{query: "SELECT CASE WHEN TRUE THEN false ELSE FALSE END AS enabled FROM events", tableName: "events"},
		{query: "WITH flags AS (SELECT TRUE AS enabled FROM events) SELECT enabled FROM flags WHERE enabled = FALSE", tableName: "events"},
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

func TestValidatePreservesCollidingNormalizedTableReferences(t *testing.T) {
	fieldTable := func(name, field string) catalog.Table {
		return catalog.Table{Name: name, Type: "data_warehouse", Fields: map[string]catalog.Field{field: {Name: field, Type: "string"}}}
	}
	for _, test := range []struct {
		name       string
		catalog    *catalog.Catalog
		query      string
		tableNames string
	}{
		{
			name: "distinct canonical tables across statements and Unicode bytes",
			catalog: &catalog.Catalog{Tables: map[string]catalog.Table{
				"a.b.c_d": fieldTable("a.b.c_d", "left_field"),
				"a.b_c.d": fieldTable("a.b_c.d", "right_field"),
			}},
			query:      "SELECT 'café'; SELECT l.left_field, r.right_field FROM a.b.c_d AS l JOIN a.b_c.d AS r ON 1 = 1",
			tableNames: "a.b.c_d,a.b_c.d",
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
			query:      "SELECT l.left_field, r.right_field FROM a.b.c_d AS l JOIN a.b_c.d AS r ON 1 = 1",
			tableNames: "a.b.c_d,a.b_c.d",
		},
		{
			name: "same target aliases keep implicit qualifiers",
			catalog: &catalog.Catalog{
				Tables: map[string]catalog.Table{"target": fieldTable("target", "shared_field")},
				TableAliases: map[string]string{
					"a.b.c_d": "target",
					"a.b_c.d": "target",
				},
			},
			query:      "SELECT a__b__c_d.shared_field, a__b_c__d.shared_field FROM a.b.c_d JOIN a.b_c.d ON 1 = 1",
			tableNames: "a.b.c_d,a.b_c.d",
		},
		{
			name: "normalized and unchanged names",
			catalog: &catalog.Catalog{Tables: map[string]catalog.Table{
				"a.b.c_d": fieldTable("a.b.c_d", "left_field"),
				"a.b_c_d": fieldTable("a.b_c_d", "right_field"),
			}},
			query:      "SELECT l.left_field, r.right_field FROM a.b.c_d AS l JOIN a.b_c_d AS r ON 1 = 1",
			tableNames: "a.b.c_d,a.b_c_d",
		},
		{
			name: "quoted normalized spelling CTE does not shadow",
			catalog: &catalog.Catalog{Tables: map[string]catalog.Table{
				"a.b.c_d": fieldTable("a.b.c_d", "left_field"),
			}},
			query:      "WITH `a.b_c_d` AS (SELECT 1 AS cte_field) SELECT a__b__c_d.left_field FROM a.b.c_d",
			tableNames: "a.b.c_d",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			test.catalog.Properties = map[string][]catalog.Property{}
			result := Validate(catalog.Prepare(test.catalog), test.query)
			if !result.Valid || strings.Join(result.TableNames, ",") != test.tableNames {
				t.Fatalf("result = %#v", result)
			}
		})
	}
}

func TestValidateCatalogTableAliasesPreserveQuerySpellingAndOccurrences(t *testing.T) {
	value := &catalog.Catalog{
		Tables: map[string]catalog.Table{
			"postgres.demo.orders": {Type: "data_warehouse", Fields: map[string]catalog.Field{"id": {Type: "integer"}}},
			"events":               {Type: "posthog", Fields: map[string]catalog.Field{"uuid": {Type: "uuid"}}},
		},
		TableAliases: map[string]string{"demo_postgres_orders": "postgres.demo.orders"},
		Properties:   map[string][]catalog.Property{},
	}
	prepared := catalog.Prepare(value)

	for _, query := range []string{
		"SELECT id FROM demo_postgres_orders",
		"SELECT a.id, b.id FROM demo_postgres_orders AS a JOIN postgres.demo.orders AS b ON a.id = b.id",
	} {
		result := Validate(prepared, query)
		if !result.Valid {
			t.Fatalf("query %q returned %#v", query, result)
		}
	}
	result := Validate(prepared, "SELECT a.id, b.id FROM demo_postgres_orders AS a JOIN postgres.demo.orders AS b ON a.id = b.id")
	if strings.Join(result.TableNames, ",") != "demo_postgres_orders,postgres.demo.orders" {
		t.Fatalf("table names = %#v", result.TableNames)
	}

	cte := Validate(prepared, "WITH demo_postgres_orders AS (SELECT uuid FROM events) SELECT c.uuid, o.id FROM demo_postgres_orders AS c JOIN postgres.demo.orders AS o ON 1 = 1")
	if !cte.Valid || strings.Join(cte.TableNames, ",") != "events,postgres.demo.orders" {
		t.Fatalf("CTE shadow result = %#v", cte)
	}
}

func TestUnknownTableSuggestionsDeduplicateAliasTargets(t *testing.T) {
	prepared := catalog.Prepare(&catalog.Catalog{
		Tables: map[string]catalog.Table{
			"postgres.demo.orders": {Fields: map[string]catalog.Field{}},
		},
		TableAliases: map[string]string{
			"demo_postgres_orders":   "postgres.demo.orders",
			"legacy_postgres_orders": "postgres.demo.orders",
		},
		Properties: map[string][]catalog.Property{},
	})
	result := Validate(prepared, "SELECT * FROM demo_postgres_order")
	if result.Valid || len(result.Diagnostics) != 1 || len(result.Diagnostics[0].Suggestions) != 1 || result.Diagnostics[0].Suggestions[0].Label != "demo_postgres_orders" {
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
		`SELECT "TRUE" FROM events`,
		"SELECT events.FALSE FROM events",
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
