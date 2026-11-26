"""Signal emitter for uptimerobot `incidents` (record kind: incident).

One row is one downtime incident of a monitor, not one row per state change.
`monitor` is a JSON object, so the query reads its `friendlyName` as `monitor_name`; `reason` says what failed.
The table has no creation column, so `started_at` (an ISO string) is the partition field.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

UPTIMEROBOT_FIELDS = (
    "id",
    "JSONExtractString(monitor, 'friendlyName') AS monitor_name",
    "reason",
    "status",
    "type",
    "started_at",
)

UPTIMEROBOT_CONFIG = SignalSourceTableConfig(
    source_product="uptimerobot",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="uptimerobot",
        source_type="incident",
        id_field="id",
        title_field="monitor_name",
        body_field="reason",
        extra_fields=("status", "type", "started_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="started_at",
    partition_field_is_datetime_string=True,
    fields=UPTIMEROBOT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
