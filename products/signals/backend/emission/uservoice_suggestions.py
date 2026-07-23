"""Signal emitter for uservoice `suggestions` (record kind: feedback).

`created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

USERVOICE_FIELDS = ("id", "title", "formatted_text", "state", "vote_count", "category_name", "created_at")

USERVOICE_CONFIG = SignalSourceTableConfig(
    source_product="uservoice",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="uservoice",
        source_type="feedback",
        id_field="id",
        title_field="title",
        body_field="formatted_text",
        extra_fields=("state", "vote_count", "category_name", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=USERVOICE_FIELDS,
    where_clause="state != 'closed'",
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
