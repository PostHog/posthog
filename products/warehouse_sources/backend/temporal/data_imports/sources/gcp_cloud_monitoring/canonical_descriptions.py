from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

API_DOCS = "https://cloud.google.com/monitoring/api/ref_v3/rest"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "MetricDescriptors": {
        "description": "Every metric type the project exposes. Read this to find the metric types a TimeSeries filter can name.",
        "docs_url": f"{API_DOCS}/v3/projects.metricDescriptors",
        "columns": {
            "name": "Resource name of the descriptor, as projects/<project>/metricDescriptors/<type>.",
            "type": "Metric type, for example serviceruntime.googleapis.com/api/request_count.",
            "displayName": "Human-readable name for the metric.",
            "description": "What the metric measures.",
            "metricKind": "Whether the value is a GAUGE, DELTA or CUMULATIVE measurement.",
            "valueType": "Type of the measurement: BOOL, INT64, DOUBLE, STRING, DISTRIBUTION or MONEY.",
            "unit": "Unit the value is reported in, in the Unified Code for Units of Measure.",
            "labels": "Labels that split this metric into separate time series.",
            "launchStage": "Google's launch stage for the metric, such as GA or BETA.",
            "monitoredResourceTypes": "Monitored resource types this metric can be written against.",
        },
    },
    "MonitoredResourceDescriptors": {
        "description": "Every monitored resource type the project exposes, with the labels that identify one resource.",
        "docs_url": f"{API_DOCS}/v3/projects.monitoredResourceDescriptors",
        "columns": {
            "name": "Resource name of the descriptor.",
            "type": "Monitored resource type, for example consumed_api or gce_instance.",
            "displayName": "Human-readable name for the resource type.",
            "description": "What the resource type represents.",
            "labels": "Labels that identify a single resource of this type.",
            "launchStage": "Google's launch stage for the resource type.",
        },
    },
    "TimeSeries": {
        "description": "Metric points matching the source's monitoring filter. One row per time series and interval.",
        "docs_url": f"{API_DOCS}/v3/projects.timeSeries/list",
        "columns": {
            "series_key": "Derived identity of the time series: a hash of the metric type and every metric and resource label. Cloud Monitoring gives a series no id of its own.",
            "metric_type": "Metric type the point belongs to.",
            "metric_labels": "Metric labels that split this series, such as response_code or method.",
            "resource_type": "Monitored resource type the point was written against.",
            "resource_labels": "Resource labels identifying the resource, such as project_id and service.",
            "metric_kind": "Whether the value is a GAUGE, DELTA or CUMULATIVE measurement.",
            "value_type": "Type of the measurement: BOOL, INT64, DOUBLE, STRING, DISTRIBUTION or MONEY.",
            "point_start_time": "Start of the interval the point covers. Equals the end time for a GAUGE metric.",
            "point_end_time": "End of the interval the point covers.",
            "doubleValue": "Point value when the metric's value type is DOUBLE.",
            "int64Value": "Point value when the metric's value type is INT64.",
            "boolValue": "Point value when the metric's value type is BOOL.",
            "stringValue": "Point value when the metric's value type is STRING.",
            "distributionValue": "Point value when the metric's value type is DISTRIBUTION, holding the count, mean and bucket counts.",
        },
    },
}
