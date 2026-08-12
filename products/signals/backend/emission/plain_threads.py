"""Signal emitter for plain `threads` (record kind: ticket).

`createdAt` is an ISO string; `previewText` gives a short body preview.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

PLAIN_FIELDS = ("id", "title", "previewText", "status", "priority", "labels", "createdAt")

PLAIN_CONFIG = SignalSourceTableConfig(
    source_product="plain",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="plain",
        source_type="ticket",
        id_field="id",
        title_field="title",
        body_field="previewText",
        extra_fields=("status", "priority", "labels", "createdAt"),
        json_list_fields=("labels",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdAt",
    partition_field_is_datetime_string=True,
    fields=PLAIN_FIELDS,
    where_clause="status != 'DONE'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
