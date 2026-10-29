"""Signal emitter for firehydrant `incidents` (record kind: incident).

`description` is often empty, so the body falls back to `summary`.
`discarded_at` is not filtered: it is null on most rows, and a column that is null on every row can be absent from the table.
`created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FIREHYDRANT_FIELDS = (
    "id",
    "name",
    "coalesce(nullIf(description, ''), summary) AS details",
    "severity",
    "priority",
    "current_milestone",
    "incident_url",
    "created_at",
)

FIREHYDRANT_CONFIG = SignalSourceTableConfig(
    source_product="firehydrant",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="firehydrant",
        source_type="incident",
        id_field="id",
        title_field="name",
        body_field="details",
        extra_fields=("severity", "priority", "current_milestone", "incident_url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=FIREHYDRANT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
