"""Signal emitter for trustpilot `service_reviews` (record kind: review).

`created_at` is an ISO string; `text` is the review body, `stars` the rating.
The consumer, location and referral email columns are not read, because they identify the reviewer.
Reviews with no text are skipped.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

TRUSTPILOT_FIELDS = (
    "id",
    "title",
    "text",
    "stars",
    "language",
    "status",
    "source",
    "created_at",
)

TRUSTPILOT_CONFIG = SignalSourceTableConfig(
    source_product="trustpilot",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="trustpilot",
        source_type="review",
        id_field="id",
        title_field="title",
        body_field="text",
        extra_fields=("stars", "language", "status", "source", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=TRUSTPILOT_FIELDS,
    where_clause="text IS NOT NULL AND text != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
