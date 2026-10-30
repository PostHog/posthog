"""Signal emitter for opsgenie `alerts` (record kind: incident).

`status` is open or closed; `created_at` is an ISO string; `message` is the alert text.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import INCIDENT_ACTIONABILITY_PROMPT, INCIDENT_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

OPSGENIE_FIELDS = (
    "id",
    "message",
    "status",
    "priority",
    "tags",
    "source",
    "created_at",
)

OPSGENIE_CONFIG = SignalSourceTableConfig(
    source_product="opsgenie",
    source_type="incident",
    emitter=make_flat_emitter(
        source_product="opsgenie",
        source_type="incident",
        id_field="id",
        title_field="message",
        extra_fields=("status", "priority", "tags", "source", "created_at"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=OPSGENIE_FIELDS,
    where_clause="status != 'closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=INCIDENT_ACTIONABILITY_PROMPT,
    summarization_prompt=INCIDENT_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
