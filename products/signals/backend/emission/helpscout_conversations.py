"""Signal emitter for helpscout `conversations` (record kind: ticket).

The message bodies live in the separate `threads` table, which the fetcher cannot join, and the
conversations table has no preview column. The subject is the only text here.
`status` is active, pending, closed, or spam; `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

HELPSCOUT_FIELDS = ("id", "number", "subject", "status", "state", "type", "created_at")

HELPSCOUT_CONFIG = SignalSourceTableConfig(
    source_product="helpscout",
    source_type="ticket",
    emitter=make_flat_emitter(
        source_product="helpscout",
        source_type="ticket",
        id_field="id",
        title_field="subject",
        extra_fields=("number", "status", "state", "type", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=HELPSCOUT_FIELDS,
    where_clause="status NOT IN ('closed', 'spam')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
