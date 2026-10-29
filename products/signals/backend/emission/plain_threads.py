"""Signal emitter for plain `threads` (record kind: ticket).

`created_at` is an ISO string; `preview_text` gives a short body preview.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

PLAIN_FIELDS = ("id", "title", "preview_text", "status", "priority", "labels", "created_at")

PLAIN_CONFIG = SignalSourceTableConfig(
    source_product="plain",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="plain",
        source_type="ticket",
        id_field="id",
        title_field="title",
        body_field="preview_text",
        extra_fields=("status", "priority", "labels", "created_at"),
        json_list_fields=("labels",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=PLAIN_FIELDS,
    where_clause="status != 'DONE'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
