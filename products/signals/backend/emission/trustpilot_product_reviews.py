"""Signal emitter for trustpilot `product_reviews` (record kind: review).

`content` is the review body and `stars` the 1-5 rating. `created_at` is an ISO string. Reviews
with no text are skipped. `product` is a JSON object, and only its name is read. The consumer,
reference id and redirect uri are not read, because they identify the reviewer.

This table has its own product value, so the existing `trustpilot` toggle for `service_reviews`
keeps its behavior.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

TRUSTPILOT_PRODUCT_REVIEWS_FIELDS = (
    "id",
    "content",
    "stars",
    "language",
    "state",
    "JSONExtractString(product, 'name') AS product_name",
    "created_at",
)

TRUSTPILOT_PRODUCT_REVIEWS_CONFIG = SignalSourceTableConfig(
    source_product="trustpilot_product_reviews",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="trustpilot_product_reviews",
        source_type="review",
        id_field="id",
        title_field="content",
        extra_fields=("stars", "language", "state", "product_name", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=TRUSTPILOT_PRODUCT_REVIEWS_FIELDS,
    where_clause="content IS NOT NULL AND content != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
