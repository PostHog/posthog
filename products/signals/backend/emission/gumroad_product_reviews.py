"""Signal emitter for gumroad `product_reviews` (record kind: review).

`message` is the review text and `rating` the star rating. `created_at` is an ISO string. Reviews
with no text are skipped. The reviewer name and the purchase id are not read, because they identify
the buyer. `response` is the seller's own reply, so it is not part of the signal.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GUMROAD_FIELDS = ("id", "message", "rating", "product_id", "created_at")

GUMROAD_CONFIG = SignalSourceTableConfig(
    source_product="gumroad",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="gumroad",
        source_type="review",
        id_field="id",
        title_field="message",
        extra_fields=("rating", "product_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=GUMROAD_FIELDS,
    where_clause="message IS NOT NULL AND message != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
