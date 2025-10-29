pub const AVRO_SCHEMA: &str = r#"
{
"type": "record",
"name": "LogRecord",
"doc": "Schema for a structured log or trace event.",
"fields": [
    {
    "name": "uuid",
    "type": ["null", "string"],
    "doc": "Unique identifier for the log record."
    },
    {
    "name": "trace_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the trace this log is a part of."
    },
    {
    "name": "span_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the span within the trace."
    },
    {
    "name": "trace_flags",
    "type": ["null", "int"],
    "doc": "Flags associated with the trace."
    },
    {
    "name": "timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The primary timestamp of the event, in microseconds since epoch."
    },
    {
    "name": "observed_timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The timestamp when the event was observed or ingested, in microseconds since epoch."
    },
    {
    "name": "created_at",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The timestamp when the record was created in the system, in microseconds since epoch."
    },
    {
    "name": "body",
    "type": ["null", "string"],
    "doc": "The main content or message of the log."
    },
    {
    "name": "severity_text",
    "type": ["null", "string"],
    "doc": "Human-readable severity level (e.g., 'INFO', 'ERROR')."
    },
    {
    "name": "severity_number",
    "type": ["null", "int"],
    "doc": "Numeric representation of the severity level."
    },
    {
    "name": "service_name",
    "type": ["null", "string"],
    "doc": "The name of the service that generated the event."
    },
    {
    "name": "resource_attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "Attributes describing the resource that produced the log (e.g., host, region)."
    },
    {
    "name": "resource_id",
    "type": ["null", "string"],
    "doc": "A unique identifier for the resource."
    },
    {
    "name": "instrumentation_scope",
    "type": ["null", "string"],
    "doc": "The name of the library or framework that captured the log."
    },
    {
    "name": "event_name",
    "type": ["null", "string"],
    "doc": "The name of a specific event that occurred."
    },
    {
    "name": "attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "A map of custom string-valued attributes associated with the log."
    },
    {
    "name": "attributes_map_str",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "Additional map of string attributes."
    },
    {
    "name": "attributes_map_float",
    "type": ["null", {
        "type": "map",
        "values": "double"
    }],
    "doc": "Map of custom double-precision float attributes."
    },
    {
    "name": "attributes_map_datetime",
    "type": ["null", {
        "type": "map",
        "values": {
        "type": "long",
        "logicalType": "timestamp-millis"
        }
    }],
    "doc": "Map of custom timestamp-valued attributes."
    },
    {
    "name": "attribute_keys",
    "type": ["null", {
        "type": "array",
        "items": "string"
    }],
    "doc": "An ordered list of attribute keys."
    },
    {
    "name": "attribute_values",
    "type": ["null", {
        "type": "array",
        "items": "string"
    }],
    "doc": "An ordered list of attribute values, corresponding to attribute_keys."
    }
]
}"#;
