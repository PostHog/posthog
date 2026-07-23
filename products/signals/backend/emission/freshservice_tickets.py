"""Signal emitter for freshservice `tickets` (record kind: ticket).

`status` is an integer (4=resolved, 5=closed); `created_at` is a native timestamp.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FRESHSERVICE_FIELDS = (
    "id",
    "subject",
    "description_text",
    "status",
    "priority",
    "type",
    "category",
    "tags",
    "created_at",
)

FRESHSERVICE_CONFIG = SignalSourceTableConfig(
    source_product="freshservice",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="freshservice",
        source_type="ticket",
        id_field="id",
        title_field="subject",
        body_field="description_text",
        extra_fields=("status", "priority", "type", "category", "tags", "created_at"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    fields=FRESHSERVICE_FIELDS,
    where_clause="status NOT IN (4, 5)",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
