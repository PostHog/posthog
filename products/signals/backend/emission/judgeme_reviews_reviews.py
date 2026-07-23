"""Signal emitter for judgeme_reviews `reviews` (record kind: review).

`created_at` is an ISO string; `body` is the review text, `rating` the star rating.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

JUDGEME_REVIEWS_FIELDS = ("id", "title", "body", "rating", "product_title", "verified", "created_at")

JUDGEME_REVIEWS_CONFIG = SignalSourceTableConfig(
    source_product="judgeme_reviews",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="judgeme_reviews",
        source_type="review",
        id_field="id",
        title_field="title",
        body_field="body",
        extra_fields=("rating", "product_title", "verified", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=JUDGEME_REVIEWS_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
