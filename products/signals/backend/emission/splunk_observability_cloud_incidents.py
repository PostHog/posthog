"""Signal emitter for splunk_observability_cloud `incidents` (record kind: incident).

One row is one detector incident, which groups the trigger and clear events of one anomaly.
`detect_label` names the rule that fired. The incident row has no detector name: the API puts
`detectorName` only on each entry of `events`, so the query reads it from the first event as `detector_name`.
The row has no creation column: the trigger time is the earliest epoch-millisecond `timestamp` in the
`events` JSON list, so that is the partition field. A row with no timestamped event reads as 1970 and is never fetched.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

# Events without a timestamp read as 0 and are dropped, so they cannot pull the trigger time back to 1970.
TRIGGERED_AT_SQL = (
    "fromUnixTimestamp(intDiv(arrayMin(arrayFilter(ts -> ts > 0, "
    "arrayMap(entry -> JSONExtractInt(entry, 'timestamp'), JSONExtractArrayRaw(events)))), 1000))"
)

# Every event of an incident comes from the same detector.
DETECTOR_NAME_SQL = "JSONExtractString(events, 1, 'detectorName')"

SPLUNK_OBSERVABILITY_CLOUD_FIELDS = (
    "incident_id",
    f"{DETECTOR_NAME_SQL} AS detector_name",
    "detect_label",
    "severity",
    "anomaly_state",
    f"{TRIGGERED_AT_SQL} AS triggered_at",
)

SPLUNK_OBSERVABILITY_CLOUD_CONFIG = SignalSourceTableConfig(
    source_product="splunk_observability_cloud",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="splunk_observability_cloud",
        source_type="incident",
        id_field="incident_id",
        title_field="detector_name",
        body_field="detect_label",
        extra_fields=("severity", "anomaly_state", "triggered_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field=TRIGGERED_AT_SQL,
    fields=SPLUNK_OBSERVABILITY_CLOUD_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
