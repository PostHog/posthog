package main

import (
	"fmt"

	"github.com/PostHog/posthog/services/hogql-language-service/internal/catalog"
)

type catalogPublication struct {
	Revision string          `json:"revision"`
	Catalog  catalog.Catalog `json:"catalog"`
}

func demoTable(name, kind string, fields map[string]string) catalog.Table {
	table := catalog.Table{Name: name, Type: kind, Fields: make(map[string]catalog.Field, len(fields))}
	for name, fieldType := range fields {
		table.Fields[name] = catalog.Field{Name: name, Type: fieldType}
	}
	return table
}

func syntheticCatalog() catalogPublication {
	tables := map[string]catalog.Table{}
	for _, table := range []catalog.Table{
		demoTable("events", "posthog", map[string]string{
			"uuid": "uuid", "event": "string", "timestamp": "datetime", "created_at": "datetime",
			"distinct_id": "string", "person_id": "uuid", "properties": "json", "elements_chain": "string",
			"$session_id": "string", "$window_id": "string", "person": "virtual_table",
			"session": "virtual_table", "group_0": "virtual_table", "group_1": "virtual_table",
		}),
		demoTable("persons", "posthog", map[string]string{
			"id": "uuid", "created_at": "datetime", "properties": "json", "is_identified": "boolean", "last_seen_at": "datetime",
		}),
		demoTable("sessions", "posthog", map[string]string{
			"session_id": "string", "distinct_id": "string", "$start_timestamp": "datetime", "$end_timestamp": "datetime",
			"$session_duration": "float", "$pageview_count": "integer", "$autocapture_count": "integer",
			"$entry_current_url": "string", "$exit_current_url": "string", "$entry_pathname": "string", "$channel_type": "string",
		}),
		demoTable("groups", "posthog", map[string]string{
			"key": "string", "index": "integer", "created_at": "datetime", "updated_at": "datetime", "properties": "json",
		}),
		demoTable("postgres.demo.orders", "data_warehouse", map[string]string{
			"id": "integer", "person_id": "uuid", "amount": "float", "currency": "string", "status": "string", "created_at": "datetime",
		}),
		demoTable("demo_customers", "data_warehouse", map[string]string{
			"id": "integer", "email": "string", "plan": "string", "billing address": "string", "café": "string",
		}),
		demoTable("demo_rules", "data_warehouse", map[string]string{
			"active_day": "date", "display_name": "string", "is_enabled": "boolean", "is_archived": "boolean",
		}),
	} {
		tables[table.Name] = table
	}
	properties := map[string][]catalog.Property{
		"event": {
			{Name: "$current_url", ValueType: "String"}, {Name: "$pathname", ValueType: "String"},
			{Name: "$browser", ValueType: "String"}, {Name: "$os", ValueType: "String"},
			{Name: "$device_type", ValueType: "String"}, {Name: "$geoip_country_name", ValueType: "String"},
			{Name: "$geoip_city_name", ValueType: "String"}, {Name: "$referrer", ValueType: "String"},
			{Name: "$utm_source", ValueType: "String"}, {Name: "$session_id", ValueType: "String"},
			{Name: "order_total", ValueType: "Numeric"}, {Name: "button_text", ValueType: "String"},
		},
		"person": {
			{Name: "email", ValueType: "String"}, {Name: "name", ValueType: "String"},
			{Name: "plan", ValueType: "String"}, {Name: "company", ValueType: "String"}, {Name: "$initial_referrer", ValueType: "String"},
		},
		"session": {{Name: "$entry_current_url", ValueType: "String"}, {Name: "$exit_current_url", ValueType: "String"}},
		"group:0": {{Name: "name", ValueType: "String"}, {Name: "industry", ValueType: "String"}, {Name: "employee_count", ValueType: "Numeric"}},
		"group:1": {{Name: "name", ValueType: "String"}, {Name: "region", ValueType: "String"}},
	}
	for index := range 35 {
		properties["event"] = append(properties["event"], catalog.Property{Name: fmt.Sprintf("demo_property_%02d", index), ValueType: "String"})
	}
	return catalogPublication{Revision: "synthetic-demo-v3", Catalog: catalog.Catalog{
		Tables:       tables,
		TableAliases: map[string]string{"demo_postgres_orders": "postgres.demo.orders"},
		Properties:   properties,
	}}
}
