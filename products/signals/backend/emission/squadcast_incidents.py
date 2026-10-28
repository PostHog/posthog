"""Signal emitter for squadcast `incidents` (record kind: incident).

Rows come from the incident export. `status` is triggered, acknowledged, resolved, or suppressed; `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SQUADCAST_FIELDS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "url",
    "created_at",
)

SQUADCAST_CONFIG = SignalSourceTableConfig(
    source_product="squadcast",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="squadcast",
        source_type="incident",
        id_field="id",
        title_field="title",
        body_field="description",
        extra_fields=("status", "priority", "url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SQUADCAST_FIELDS,
    where_clause="status NOT IN ('resolved', 'suppressed')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
