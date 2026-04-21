pub const TRACES_AVRO_SCHEMA: &str = r#"
{
"type": "record",
"name": "TraceRecord",
"doc": "Schema for an OTEL trace span.",
"fields": [
    {
    "name": "uuid",
    "type": ["null", "string"],
    "doc": "Unique identifier for the span record."
    },
    {
    "name": "trace_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the trace this span belongs to."
    },
    {
    "name": "span_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for this span within the trace."
    },
    {
    "name": "parent_span_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the parent span, if any."
    },
    {
    "name": "trace_state",
    "type": ["null", "string"],
    "doc": "W3C trace state string."
    },
    {
    "name": "name",
    "type": ["null", "string"],
    "doc": "Operation name of the span."
    },
    {
    "name": "kind",
    "type": ["null", "int"],
    "doc": "SpanKind: 0=UNSPECIFIED, 1=INTERNAL, 2=SERVER, 3=CLIENT, 4=PRODUCER, 5=CONSUMER."
    },
    {
    "name": "flags",
    "type": ["null", "int"],
    "doc": "Trace flags as defined in W3C Trace Context specification."
    },
    {
    "name": "timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "Start time of the span, in microseconds since epoch."
    },
    {
    "name": "end_time",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "End time of the span, in microseconds since epoch."
    },
    {
    "name": "observed_timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The timestamp when the span was received by the collector."
    },
    {
    "name": "service_name",
    "type": ["null", "string"],
    "doc": "The name of the service that generated the span."
    },
    {
    "name": "resource_attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "Attributes describing the resource that produced the span."
    },
    {
    "name": "instrumentation_scope",
    "type": ["null", "string"],
    "doc": "The name and version of the instrumentation library that captured the span."
    },
    {
    "name": "attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "A map of custom string-valued attributes associated with the span."
    },
    {
    "name": "dropped_attributes_count",
    "type": ["null", "int"],
    "doc": "Number of attributes that were dropped due to limits."
    },
    {
    "name": "events",
    "type": ["null", {
        "type": "array",
        "items": "string"
    }],
    "doc": "Array of span events, each serialized as a JSON string."
    },
    {
    "name": "dropped_events_count",
    "type": ["null", "int"],
    "doc": "Number of events that were dropped due to limits."
    },
    {
    "name": "links",
    "type": ["null", {
        "type": "array",
        "items": "string"
    }],
    "doc": "Array of span links, each serialized as a JSON string."
    },
    {
    "name": "dropped_links_count",
    "type": ["null", "int"],
    "doc": "Number of links that were dropped due to limits."
    },
    {
    "name": "status_code",
    "type": ["null", "int"],
    "doc": "Status code: 0=UNSET, 1=OK, 2=ERROR."
    },
    {
    "name": "status_message",
    "type": ["null", "string"],
    "doc": "Status message"
    }
]
}"#;
