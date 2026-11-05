"""Signal emitter for mintlify `feedback` (record kind: feedback).

`created_at` is an ISO string; `comment` is the free-text feedback.
`status` is pending, in_progress, resolved or dismissed. Resolved and dismissed rows, and rows with no comment, are skipped.
The contact column is not read, because it is an email address.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

MINTLIFY_FIELDS = (
    "id",
    "comment",
    "path",
    "helpful",
    "status",
    "source",
    "created_at",
)

MINTLIFY_CONFIG = SignalSourceTableConfig(
    source_product="mintlify",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="mintlify",
        source_type="feedback",
        id_field="id",
        title_field="comment",
        extra_fields=("path", "helpful", "status", "source", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=MINTLIFY_FIELDS,
    where_clause="comment IS NOT NULL AND comment != '' AND status NOT IN ('resolved', 'dismissed')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
