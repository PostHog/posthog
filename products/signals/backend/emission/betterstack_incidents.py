"""Signal emitter for betterstack `incidents` (record kind: incident).

`name` is the monitor or heartbeat name and `cause` says what failed (status code, timeout, missed heartbeat).
The table has no creation column, so `started_at` (an ISO string) is the partition field.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

BETTERSTACK_FIELDS = (
    "id",
    "name",
    "cause",
    "url",
    "started_at",
)

BETTERSTACK_CONFIG = SignalSourceTableConfig(
    source_product="betterstack",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="betterstack",
        source_type="incident",
        id_field="id",
        title_field="name",
        body_field="cause",
        extra_fields=("url", "started_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="started_at",
    partition_field_is_datetime_string=True,
    fields=BETTERSTACK_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
