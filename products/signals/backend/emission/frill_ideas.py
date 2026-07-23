"""Signal emitter for frill `ideas` (record kind: feedback).

Record id is `idx`; `created_at` is an ISO string. `is_completed` boolean filter — verify storage on first sync.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FRILL_FIELDS = ("idx", "name", "description", "status", "vote_count", "topics", "created_at")

FRILL_CONFIG = SignalSourceTableConfig(
    source_product="frill",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="frill",
        source_type="feedback",
        id_field="idx",
        title_field="name",
        body_field="description",
        extra_fields=("status", "vote_count", "topics", "created_at"),
        json_list_fields=("topics",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=FRILL_FIELDS,
    where_clause="is_completed = false",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
