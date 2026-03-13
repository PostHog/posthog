pub const AVRO_SCHEMA: &str = r#"
{
"type": "record",
"name": "MetricRecord",
"doc": "Schema for an OTEL metric data point.",
"fields": [
    {
    "name": "uuid",
    "type": ["null", "string"],
    "doc": "Unique identifier for the metric record."
    },
    {
    "name": "trace_id",
    "type": ["null", "bytes"],
    "doc": "Identifier for the trace this metric is associated with."
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
    "doc": "The primary timestamp of the data point, in microseconds since epoch."
    },
    {
    "name": "observed_timestamp",
    "type": ["null", {
        "type": "long",
        "logicalType": "timestamp-micros"
    }],
    "doc": "The timestamp when the metric was ingested, in microseconds since epoch."
    },
    {
    "name": "service_name",
    "type": ["null", "string"],
    "doc": "The name of the service that generated the metric."
    },
    {
    "name": "metric_name",
    "type": ["null", "string"],
    "doc": "The name of the metric (e.g., 'system.cpu.utilization')."
    },
    {
    "name": "metric_type",
    "type": ["null", "string"],
    "doc": "The type of metric: gauge, sum, histogram, summary, exponential_histogram."
    },
    {
    "name": "value",
    "type": ["null", "double"],
    "doc": "The primary numeric value of the data point."
    },
    {
    "name": "count",
    "type": ["null", "long"],
    "doc": "Count for histogram/summary data points, or 1 for simple data points."
    },
    {
    "name": "histogram_bounds",
    "type": ["null", {
        "type": "array",
        "items": "double"
    }],
    "doc": "Explicit bucket boundaries for histogram metrics."
    },
    {
    "name": "histogram_counts",
    "type": ["null", {
        "type": "array",
        "items": "long"
    }],
    "doc": "Bucket counts for histogram metrics."
    },
    {
    "name": "unit",
    "type": ["null", "string"],
    "doc": "The unit of the metric (e.g., 'bytes', 'seconds', '1')."
    },
    {
    "name": "aggregation_temporality",
    "type": ["null", "string"],
    "doc": "Aggregation temporality: delta or cumulative."
    },
    {
    "name": "is_monotonic",
    "type": ["null", "boolean"],
    "doc": "Whether the sum is monotonic (counter vs up-down counter)."
    },
    {
    "name": "resource_attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "Attributes describing the resource that produced the metric."
    },
    {
    "name": "instrumentation_scope",
    "type": ["null", "string"],
    "doc": "The name of the library or framework that captured the metric."
    },
    {
    "name": "attributes",
    "type": ["null", {
        "type": "map",
        "values": "string"
    }],
    "doc": "A map of custom string-valued attributes associated with the data point."
    }
]
}"#;
