"""Signal emitter for kustomer `conversations` (record kind: ticket).

`createdAt` is an ISO string; the conversation `name` is the only text on this table.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

KUSTOMER_FIELDS = ("id", "name", "status", "priority", "tags", "createdAt")

KUSTOMER_CONFIG = SignalSourceTableConfig(
    source_product="kustomer",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="kustomer",
        source_type="ticket",
        id_field="id",
        title_field="name",
        extra_fields=("status", "priority", "tags", "createdAt"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdAt",
    partition_field_is_datetime_string=True,
    fields=KUSTOMER_FIELDS,
    where_clause="status != 'done'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
