package hogqllanguageservice_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/httpapi"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/ratelimit"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

const (
	syntheticTableCount     = 4096
	syntheticFieldsPerTable = 25
	syntheticPropertyCount  = 120000
	cursorMarker            = "§"
)

const sessionActorQuery = `
SELECT
    s.session_id,
    s.$start_timestamp,
    s.$end_timestamp,
    s.$session_duration,
    s.$channel_type,
    s.$entry_` + cursorMarker + `pathname,
    s.$entry_referring_domain,
    s.$entry_utm_source,
    s.$entry_utm_medium,
    s.$entry_utm_campaign,
    s.$entry_utm_term,
    s.$entry_utm_content,
    s.$num_uniq_urls,
    s.$autocapture_count,
    s.$exit_pathname,
    s.$last_external_click_url,
    s.$pageview_count
FROM sessions AS s
WHERE s.session_id IN (
    SELECT session_id
    FROM events
    WHERE event = '$pageview'
      AND timestamp >= now() - INTERVAL 30 DAY
)
ORDER BY s.$start_timestamp DESC
LIMIT 100`

const traceTreeQuery = `
WITH matched_traces AS (
    SELECT DISTINCT trace_id
    FROM posthog.trace_spans
    WHERE name = 'database.query'
      AND service_name = 'analytics-api'
      AND timestamp >= now() - INTERVAL 7 DAY
),
spans AS (
    SELECT
        s.span_id,
        s.parent_span_id,
        s.trace_id,
        s.service_name,
        s.name,
        s.duration_n` + cursorMarker + `ano,
        s.status_code,
        s.timestamp
    FROM posthog.trace_spans AS s
    WHERE s.trace_id IN (SELECT trace_id FROM matched_traces)
      AND s.service_name = 'analytics-api'
      AND s.timestamp >= now() - INTERVAL 7 DAY
)
SELECT
    coalesce(p.service_name, '') AS parent_service,
    if(empty(s.parent_span_id), '<ROOT>', coalesce(p.name, '<ROOT>')) AS parent_name,
    s.service_name,
    s.name,
    count() AS span_count,
    sum(s.duration_nano) AS total_duration_nano,
    avg(s.duration_nano) AS avg_duration_nano,
    quantiles(0.5, 0.95, 0.99, 0.999)(s.duration_nano) AS duration_quantiles,
    countIf(s.status_code = 2) AS error_count,
    avg(
        if(
            empty(s.parent_span_id) OR isNull(p.timestamp),
            toFloat(0),
            toFloat(dateDiff('microsecond', p.timestamp, s.timestamp) * 1000)
        )
    ) AS avg_start_offset_nano
FROM spans AS s
LEFT JOIN spans AS p
    ON p.trace_id = s.trace_id AND p.span_id = s.parent_span_id
GROUP BY parent_service, parent_name, s.service_name, s.name
ORDER BY total_duration_nano DESC
LIMIT 1000`

const eventJourneyQuery = `
WITH first_touch AS (
    SELECT
        e.person_id,
        min(e.timestamp) AS first_seen,
        argMin(e.properties.$event_property_249` + cursorMarker + `99, e.timestamp) AS entry_value
    FROM events AS e
    WHERE e.event = '$pageview'
      AND e.timestamp >= now() - INTERVAL 90 DAY
      AND e.properties.$event_property_00001 != ''
    GROUP BY e.person_id
),
returning AS (
    SELECT
        e.person_id,
        countIf(e.event = '$pageview') AS pageviews,
        countDistinct(toDate(e.timestamp)) AS active_days,
        max(e.timestamp) AS last_seen
    FROM events AS e
    WHERE e.timestamp >= now() - INTERVAL 90 DAY
    GROUP BY e.person_id
)
SELECT
    f.entry_value,
    count() AS people,
    avg(r.pageviews) AS average_pageviews,
    avg(r.active_days) AS average_active_days,
    quantiles(0.5, 0.9, 0.99)(dateDiff('second', f.first_seen, r.last_seen)) AS retention_seconds
FROM first_touch AS f
LEFT JOIN returning AS r ON r.person_id = f.person_id
WHERE r.pageviews > 1
GROUP BY f.entry_value
HAVING people >= 10
ORDER BY people DESC, f.entry_value ASC
LIMIT 100`

type catalogUpdate struct {
	Revision string          `json:"revision"`
	Catalog  catalog.Catalog `json:"catalog"`
}

type completionCase struct {
	name     string
	query    string
	position int
}

func BenchmarkCompleteLargeCatalog(b *testing.B) {
	schema := catalog.Prepare(largeSyntheticCatalog())
	sessionQuery, sessionPosition := queryAndPosition(sessionActorQuery)
	traceQuery, tracePosition := queryAndPosition(traceTreeQuery)
	eventQuery, eventPosition := queryAndPosition(eventJourneyQuery)
	cases := []completionCase{
		{name: "table broad prefix", query: "SELECT * FROM warehouse_table_", position: len("SELECT * FROM warehouse_table_")},
		{name: "alias broad prefix", query: "SELECT * FROM legacy_warehouse_table_", position: len("SELECT * FROM legacy_warehouse_table_")},
		{name: "dotted alias broad prefix", query: "SELECT * FROM legacy.warehouse.table_", position: len("SELECT * FROM legacy.warehouse.table_")},
		{name: "field broad prefix", query: "SELECT w. FROM warehouse_table_2048 AS w", position: len("SELECT w.")},
		{name: "event property broad prefix", query: "SELECT properties.$event_property_ FROM events", position: len("SELECT properties.$event_property_")},
		{name: "event property selective prefix", query: "SELECT properties.$event_property_249 FROM events", position: len("SELECT properties.$event_property_249")},
		{name: "large session query", query: sessionQuery, position: sessionPosition},
		{name: "large trace query", query: traceQuery, position: tracePosition},
		{name: "large event query", query: eventQuery, position: eventPosition},
	}

	for _, benchmark := range cases {
		b.Run(benchmark.name, func(b *testing.B) {
			benchmarkCompletion(b, schema, benchmark.query, benchmark.position)
		})
	}
}

func BenchmarkValidateLargeCatalog(b *testing.B) {
	schema := catalog.Prepare(largeSyntheticCatalog())
	sessionQuery, _ := queryAndPosition(sessionActorQuery)
	eventQuery, _ := queryAndPosition(eventJourneyQuery)
	traceQuery, _ := queryAndPosition(traceTreeQuery)
	for _, benchmark := range []struct {
		name  string
		query string
	}{
		{name: "known event query", query: "SELECT event, count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event ORDER BY count() DESC LIMIT 100"},
		{name: "large session query", query: sessionQuery},
		{name: "large event query", query: eventQuery},
		{name: "large trace query", query: traceQuery},
		{name: "unknown table", query: "SELECT column_00 FROM warehouse_tabel_2048"},
		{name: "unknown event property", query: "SELECT properties.$event_property_120000 FROM events"},
	} {
		b.Run(benchmark.name, func(b *testing.B) {
			benchmarkValidation(b, schema, benchmark.query)
		})
	}
}

func TestLargeCatalogSupportedScale(t *testing.T) {
	schema := largeSyntheticCatalog()
	if len(schema.Tables) != syntheticTableCount {
		t.Fatalf("tables = %d, want %d", len(schema.Tables), syntheticTableCount)
	}
	for name, table := range schema.Tables {
		if len(table.Fields) != syntheticFieldsPerTable {
			t.Fatalf("table %q fields = %d, want %d", name, len(table.Fields), syntheticFieldsPerTable)
		}
	}
	if len(schema.Properties) != 1 || len(schema.Properties["event"]) != syntheticPropertyCount {
		t.Fatalf("property namespaces = %d, event properties = %d", len(schema.Properties), len(schema.Properties["event"]))
	}

	update := catalogUpdate{Revision: "supported-scale", Catalog: *schema}
	payload, err := json.Marshal(update)
	if err != nil {
		t.Fatal(err)
	}
	registry := catalog.NewRegistry(1024, 8<<30, time.Hour)
	limiterConfig := ratelimit.Config{Capacity: 10, RefillPerSec: 10, MaxEntries: 10, IdleTTL: time.Hour}
	preAuthLimiter, err := ratelimit.New(limiterConfig)
	if err != nil {
		t.Fatal(err)
	}
	principalLimiter, err := ratelimit.New(limiterConfig)
	if err != nil {
		t.Fatal(err)
	}
	handler := httpapi.NewHandler(httpapi.Config{
		Catalogs:         registry,
		Auth:             serviceauth.New(nil, true),
		PreAuthLimiter:   preAuthLimiter,
		PrincipalLimiter: principalLimiter,
		Logger:           slog.New(slog.NewTextHandler(io.Discard, nil)),
	})
	request := httptest.NewRequest(http.MethodPut, "/teams/1/users/1/catalog", bytes.NewReader(payload))
	request.Header.Set("Content-Type", "application/json")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("catalog publication returned %d: %s", response.Code, response.Body.String())
	}
	prepared, revision, ok := registry.Get(serviceauth.Authorization{TeamID: 1, UserID: 1})
	if !ok {
		t.Fatal("published catalog was not found")
	}
	if revision != update.Revision || prepared.TableCount() != syntheticTableCount || prepared.PropertyCount() != syntheticPropertyCount {
		t.Fatalf("published catalog = revision %q, found %t, tables %d, properties %d", revision, ok, prepared.TableCount(), prepared.PropertyCount())
	}

	for _, test := range []struct {
		query    string
		position int
		total    int
	}{
		{query: "SELECT * FROM warehouse_table_", total: syntheticTableCount - 3},
		{query: "SELECT * FROM legacy_warehouse_table_", total: syntheticTableCount - 3},
		{query: "SELECT * FROM legacy.warehouse.table_", total: syntheticTableCount - 3},
		{query: "SELECT w. FROM warehouse_table_2048 AS w", position: len("SELECT w."), total: syntheticFieldsPerTable},
		{query: "SELECT properties.$event_property_ FROM events", position: len("SELECT properties.$event_property_"), total: syntheticPropertyCount},
	} {
		position := test.position
		if position == 0 {
			position = len(test.query)
		}
		result, err := completion.Complete(prepared, test.query, position, completion.PositionEncodingUTF8, "")
		if err != nil {
			t.Fatalf("complete %q: %v", test.query, err)
		}
		if result.Total != test.total || len(result.Suggestions) != completion.PageSize {
			t.Fatalf("complete %q returned total %d, page %d, cursor %q", test.query, result.Total, len(result.Suggestions), result.NextCursor)
		}
		if test.total == completion.PageSize {
			if result.NextCursor != "" {
				t.Fatalf("complete %q returned unexpected cursor %q", test.query, result.NextCursor)
			}
			continue
		}
		if result.NextCursor == "" {
			t.Fatalf("complete %q did not return a second-page cursor", test.query)
		}
		second, err := completion.Complete(prepared, test.query, position, completion.PositionEncodingUTF8, result.NextCursor)
		if err != nil {
			t.Fatalf("complete second page %q: %v", test.query, err)
		}
		if second.Total != test.total || len(second.Suggestions) == 0 || second.Suggestions[0].Label == result.Suggestions[0].Label {
			t.Fatalf("complete second page %q returned %#v", test.query, second)
		}
	}

	for _, query := range []string{
		"SELECT column_24 FROM legacy.warehouse.table_2048",
		"SELECT properties.$event_property_119999 FROM events",
	} {
		if result := validation.Validate(prepared, query); !result.Valid {
			t.Fatalf("validate %q returned %#v", query, result)
		}
	}
}

func BenchmarkCatalogPublication(b *testing.B) {
	schema := largeSyntheticCatalog()
	update := catalogUpdate{Revision: "synthetic-revision", Catalog: *schema}
	payload, err := json.Marshal(update)
	if err != nil {
		b.Fatal(err)
	}
	authorization := serviceauth.Authorization{TeamID: 1, UserID: 1}
	prepared := catalog.Prepare(schema)
	b.Run("decode", func(b *testing.B) {
		b.ReportAllocs()
		b.SetBytes(int64(len(payload)))
		b.ResetTimer()
		reportCatalogMetrics(b, schema, len(payload))
		for range b.N {
			var decoded catalogUpdate
			if err := json.Unmarshal(payload, &decoded); err != nil {
				b.Fatal(err)
			}
		}
	})

	b.Run("prepare", func(b *testing.B) {
		var result *catalog.PreparedCatalog
		b.ReportAllocs()
		b.ResetTimer()
		reportCatalogMetrics(b, schema, len(payload))
		b.ReportMetric(float64(prepared.EstimatedBytes()), "prepared-B")
		for range b.N {
			result = catalog.Prepare(schema)
		}
		if result == nil {
			b.Fatal("catalog preparation returned nil")
		}
	})

	b.Run("cache replacement", func(b *testing.B) {
		registry := catalog.NewRegistry(2, 1<<30, time.Hour)
		b.ReportAllocs()
		b.ResetTimer()
		reportCatalogMetrics(b, schema, len(payload))
		b.ReportMetric(float64(prepared.EstimatedBytes()), "prepared-B")
		for range b.N {
			if err := registry.Put(authorization, update.Revision, prepared); err != nil {
				b.Fatal(err)
			}
		}
	})

	b.Run("decode prepare and replace", func(b *testing.B) {
		registry := catalog.NewRegistry(2, 1<<30, time.Hour)
		b.ReportAllocs()
		b.SetBytes(int64(len(payload)))
		b.ResetTimer()
		reportCatalogMetrics(b, schema, len(payload))
		b.ReportMetric(float64(prepared.EstimatedBytes()), "prepared-B")
		for range b.N {
			var decoded catalogUpdate
			if err := json.Unmarshal(payload, &decoded); err != nil {
				b.Fatal(err)
			}
			if err := registry.Put(authorization, decoded.Revision, catalog.Prepare(&decoded.Catalog)); err != nil {
				b.Fatal(err)
			}
		}
	})
}

func benchmarkCompletion(b *testing.B, schema *catalog.PreparedCatalog, query string, position int) {
	result, err := completion.Complete(schema, query, position, completion.PositionEncodingUTF8, "")
	if err != nil {
		b.Fatal(err)
	}
	payload, err := json.Marshal(result)
	if err != nil {
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.SetBytes(int64(len(query)))
	b.ResetTimer()
	b.ReportMetric(float64(len(query)), "query-B")
	b.ReportMetric(float64(len(payload)), "response-B")
	if result.ParseError != "" {
		b.ReportMetric(1, "parse-errors")
	}
	for range b.N {
		if _, err := completion.Complete(schema, query, position, completion.PositionEncodingUTF8, ""); err != nil {
			b.Fatal(err)
		}
	}
}

func benchmarkValidation(b *testing.B, schema *catalog.PreparedCatalog, query string) {
	result := validation.Validate(schema, query)
	payload, err := json.Marshal(result)
	if err != nil {
		b.Fatal(err)
	}
	b.ReportAllocs()
	b.SetBytes(int64(len(query)))
	b.ResetTimer()
	b.ReportMetric(float64(len(result.Diagnostics)), "diagnostics")
	b.ReportMetric(float64(len(query)), "query-B")
	b.ReportMetric(float64(len(payload)), "response-B")
	for range b.N {
		validation.Validate(schema, query)
	}
}

func reportCatalogMetrics(b *testing.B, schema *catalog.Catalog, requestBytes int) {
	b.ReportMetric(float64(len(schema.Tables)), "tables")
	b.ReportMetric(syntheticPropertyCount, "properties")
	b.ReportMetric(float64(requestBytes), "request-B")
}

func queryAndPosition(marked string) (string, int) {
	position := strings.Index(marked, cursorMarker)
	if position < 0 {
		panic("query does not contain a cursor marker")
	}
	return strings.Replace(marked, cursorMarker, "", 1), position
}

func largeSyntheticCatalog() *catalog.Catalog {
	tables := make(map[string]catalog.Table, syntheticTableCount)
	tableAliases := make(map[string]string, 2*(syntheticTableCount-3))
	for tableIndex := 0; tableIndex < syntheticTableCount-3; tableIndex++ {
		fields := make(map[string]catalog.Field, syntheticFieldsPerTable)
		for fieldIndex := 0; fieldIndex < syntheticFieldsPerTable; fieldIndex++ {
			name := fmt.Sprintf("column_%02d", fieldIndex)
			fields[name] = catalog.Field{Name: name, Type: "String"}
		}
		name := fmt.Sprintf("warehouse_table_%04d", tableIndex)
		tables[name] = catalog.Table{ID: fmt.Sprintf("table-%04d", tableIndex), Name: name, Type: "data_warehouse", Fields: fields}
		tableAliases[fmt.Sprintf("legacy_warehouse_table_%04d", tableIndex)] = name
		tableAliases[fmt.Sprintf("legacy.warehouse.table_%04d", tableIndex)] = name
	}
	tables["events"] = catalog.Table{Name: "events", Type: "posthog", Fields: scaleFields(
		"distinct_id", "event", "person_id", "properties", "session_id", "timestamp", "uuid",
	)}
	tables["sessions"] = catalog.Table{Name: "sessions", Type: "posthog", Fields: scaleFields(
		"$autocapture_count", "$channel_type", "$end_timestamp", "$entry_pathname", "$entry_referring_domain",
		"$entry_utm_campaign", "$entry_utm_content", "$entry_utm_medium", "$entry_utm_source", "$entry_utm_term",
		"$exit_pathname", "$last_external_click_url", "$num_uniq_urls", "$pageview_count", "$session_duration",
		"$start_timestamp", "session_id",
	)}
	tables["posthog.trace_spans"] = catalog.Table{Name: "posthog.trace_spans", Type: "posthog", Fields: scaleFields(
		"duration_nano", "name", "parent_span_id", "service_name", "span_id", "status_code", "timestamp", "trace_id",
	)}

	properties := make([]catalog.Property, syntheticPropertyCount)
	for propertyIndex := range properties {
		properties[propertyIndex] = catalog.Property{Name: fmt.Sprintf("$event_property_%05d", propertyIndex), ValueType: "String"}
	}
	return &catalog.Catalog{Tables: tables, TableAliases: tableAliases, Properties: map[string][]catalog.Property{"event": properties}}
}

func scaleFields(names ...string) map[string]catalog.Field {
	result := fields(names...)
	for fieldIndex := len(result); fieldIndex < syntheticFieldsPerTable; fieldIndex++ {
		name := fmt.Sprintf("scale_column_%02d", fieldIndex)
		result[name] = catalog.Field{Name: name, Type: "String"}
	}
	return result
}

func fields(names ...string) map[string]catalog.Field {
	result := make(map[string]catalog.Field, len(names))
	for _, name := range names {
		result[name] = catalog.Field{Name: name, Type: "String"}
	}
	return result
}
