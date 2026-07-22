"""Signal emitter for gorgias `tickets` (record kind: ticket).

Gorgias uses `created_datetime` (ISO string); message bodies live in a separate table, so the subject is the text here.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GORGIAS_FIELDS = ("id", "subject", "status", "priority", "channel", "tags", "created_datetime")

GORGIAS_CONFIG = SignalSourceTableConfig(
    source_product="gorgias",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="gorgias",
        source_type="ticket",
        id_field="id",
        title_field="subject",
        extra_fields=("status", "priority", "channel", "tags", "created_datetime"),
        json_list_fields=("tags",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_datetime",
    partition_field_is_datetime_string=True,
    fields=GORGIAS_FIELDS,
    where_clause="status != 'closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
