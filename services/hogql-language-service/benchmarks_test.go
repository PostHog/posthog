package hogqllanguageservice_test

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/completion"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/serviceauth"
	"github.com/PostHog/posthog/services/hogql-language-service/internal/validation"
)

const (
	syntheticTableCount      = 4096
	syntheticFieldsPerTable  = 25
	syntheticPropertyCount   = 100000
	syntheticNamespaceCount  = 4
	syntheticPropertiesPerNS = syntheticPropertyCount / syntheticNamespaceCount
	cursorMarker             = "§"
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
		{name: "field broad prefix", query: "SELECT w.column_ FROM warehouse_table_2048 AS w", position: len("SELECT w.column_")},
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
		{name: "unknown event property", query: "SELECT properties.$event_property_25000 FROM events"},
	} {
		b.Run(benchmark.name, func(b *testing.B) {
			benchmarkValidation(b, schema, benchmark.query)
		})
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
	for tableIndex := 0; tableIndex < syntheticTableCount-3; tableIndex++ {
		fields := make(map[string]catalog.Field, syntheticFieldsPerTable)
		for fieldIndex := 0; fieldIndex < syntheticFieldsPerTable; fieldIndex++ {
			name := fmt.Sprintf("column_%02d", fieldIndex)
			fields[name] = catalog.Field{Name: name, Type: "String"}
		}
		name := fmt.Sprintf("warehouse_table_%04d", tableIndex)
		tables[name] = catalog.Table{ID: fmt.Sprintf("table-%04d", tableIndex), Name: name, Type: "data_warehouse", Fields: fields}
	}
	tables["events"] = catalog.Table{Name: "events", Type: "posthog", Fields: fields(
		"distinct_id", "event", "person_id", "properties", "session_id", "timestamp", "uuid",
	)}
	tables["sessions"] = catalog.Table{Name: "sessions", Type: "posthog", Fields: fields(
		"$autocapture_count", "$channel_type", "$end_timestamp", "$entry_pathname", "$entry_referring_domain",
		"$entry_utm_campaign", "$entry_utm_content", "$entry_utm_medium", "$entry_utm_source", "$entry_utm_term",
		"$exit_pathname", "$last_external_click_url", "$num_uniq_urls", "$pageview_count", "$session_duration",
		"$start_timestamp", "session_id",
	)}
	tables["posthog.trace_spans"] = catalog.Table{Name: "posthog.trace_spans", Type: "posthog", Fields: fields(
		"duration_nano", "name", "parent_span_id", "service_name", "span_id", "status_code", "timestamp", "trace_id",
	)}

	properties := make(map[string][]catalog.Property, syntheticNamespaceCount)
	for _, namespace := range []struct {
		name   string
		prefix string
	}{
		{name: "event", prefix: "$event_property_"},
		{name: "person", prefix: "$person_property_"},
		{name: "group:0", prefix: "$group_property_"},
		{name: "session", prefix: "$session_property_"},
	} {
		values := make([]catalog.Property, syntheticPropertiesPerNS)
		for propertyIndex := range values {
			values[propertyIndex] = catalog.Property{Name: fmt.Sprintf("%s%05d", namespace.prefix, propertyIndex), ValueType: "String"}
		}
		properties[namespace.name] = values
	}
	return &catalog.Catalog{Tables: tables, Properties: properties}
}

func fields(names ...string) map[string]catalog.Field {
	result := make(map[string]catalog.Field, len(names))
	for _, name := range names {
		result[name] = catalog.Field{Name: name, Type: "String"}
	}
	return result
}
