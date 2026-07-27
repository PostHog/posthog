"""Signal emitter for front `conversations` (record kind: ticket).

Front returns `created_at` as a Unix epoch (seconds); the conversation body lives in the messages table, so the subject is the only text here.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FRONT_FIELDS = ("id", "subject", "status", "tags", "created_at")

FRONT_CONFIG = SignalSourceTableConfig(
    source_product="front",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="front",
        source_type="ticket",
        id_field="id",
        title_field="subject",
        extra_fields=("status", "tags", "created_at"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toUInt32(created_at))",
    fields=FRONT_FIELDS,
    where_clause="status NOT IN ('archived', 'deleted')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
