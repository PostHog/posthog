from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Cost Anomaly Detection is part of Cost Explorer, a global service reached through us-east-1, so
# both the endpoint and the SigV4 signing region are fixed.
CE_ENDPOINT_URL = "https://ce.us-east-1.amazonaws.com/"
CE_SIGNING_REGION = "us-east-1"
CE_SIGNING_NAME = "ce"
CE_TARGET_PREFIX = "AWSInsightsIndexService"
CE_CONTENT_TYPE = "application/x-amz-json-1.1"

REQUEST_TIMEOUT_SECONDS = 120

# AWS keeps anomalies for up to 90 days, so no sync can reach back further than that.
ANOMALY_RETENTION_DAYS = 90

# An ongoing anomaly keeps changing: its score, impact and end date all move until AWS closes it.
# So an incremental run rewinds this far behind the stored watermark and re-merges those rows.
ONGOING_ANOMALY_LOOKBACK_DAYS = 14


@dataclass(frozen=True)
class AnomalyDetectionEndpointConfig:
    name: str
    # Operation name, dispatched through the `X-Amz-Target` header.
    operation: str
    # Response key holding the list of items.
    result_key: str
    primary_key: list[str]
    # `MaxResults` per request. The API bills per paginated request, so pages are as wide as the
    # documented range allows (`MaxResults` has a minimum of 1 and no documented maximum).
    page_size: int
    # Only GetAnomalies takes a server-side date filter: `DateInterval`, matched against
    # `AnomalyEndDate`.
    supports_date_interval: bool = False
    # Flattened columns holding `YearMonthDay` values, parsed into datetimes.
    date_columns: tuple[str, ...] = ()
    # Response members kept whole rather than flattened into columns: filter expressions nest
    # arbitrarily deep and are keyed by the customer's own tag and cost category keys, so
    # flattening them would mint a column per key. The pipeline stores them as JSON.
    raw_keys: frozenset[str] = field(default_factory=frozenset)
    # Stable datetime column to partition on, if the table has one.
    partition_key: str | None = None


AWS_COST_ANOMALY_DETECTION_ENDPOINTS: dict[str, AnomalyDetectionEndpointConfig] = {
    "anomalies": AnomalyDetectionEndpointConfig(
        name="anomalies",
        operation="GetAnomalies",
        result_key="Anomalies",
        primary_key=["anomaly_id"],
        page_size=100,
        supports_date_interval=True,
        date_columns=("anomaly_start_date", "anomaly_end_date"),
        # The first day an anomaly was detected never moves once AWS has reported it.
        partition_key="anomaly_start_date",
    ),
    "anomaly_monitors": AnomalyDetectionEndpointConfig(
        name="anomaly_monitors",
        operation="GetAnomalyMonitors",
        result_key="AnomalyMonitors",
        primary_key=["monitor_arn"],
        page_size=100,
        date_columns=("creation_date", "last_updated_date", "last_evaluated_date"),
        raw_keys=frozenset({"MonitorSpecification"}),
    ),
    "anomaly_subscriptions": AnomalyDetectionEndpointConfig(
        name="anomaly_subscriptions",
        operation="GetAnomalySubscriptions",
        result_key="AnomalySubscriptions",
        primary_key=["subscription_arn"],
        page_size=100,
        raw_keys=frozenset({"ThresholdExpression"}),
    ),
}

ENDPOINTS = tuple(AWS_COST_ANOMALY_DETECTION_ENDPOINTS.keys())

# Only GetAnomalies filters server-side, on `AnomalyEndDate`. Monitors and subscriptions carry no
# filter (and subscriptions carry no timestamp at all), so they stay full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "anomalies": [
        {
            "label": "anomaly_end_date",
            "type": IncrementalFieldType.DateTime,
            "field": "anomaly_end_date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "anomalies": "Cost anomalies AWS detected on the account, with their spend impact and root causes. AWS keeps 90 days of anomalies.",
    "anomaly_monitors": "Cost monitors that inspect the account's spend, with the dimension and specification each one evaluates.",
    "anomaly_subscriptions": "Alert subscriptions attached to the cost monitors, with their subscribers, frequency and alert threshold.",
}
