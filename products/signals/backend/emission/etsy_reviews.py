"""Signal emitter for etsy `reviews` (record kind: review).

One row per reviewed transaction, so `transaction_id` is the review id. `review` is the text and
`rating` the 1-5 star rating. `created_timestamp` is Unix epoch seconds. Reviews with no text are
skipped. `buyer_user_id` is not read, because it identifies the buyer.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ETSY_FIELDS = ("transaction_id", "review", "rating", "listing_id", "language", "created_timestamp")

ETSY_CONFIG = SignalSourceTableConfig(
    source_product="etsy",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="etsy",
        source_type="review",
        id_field="transaction_id",
        title_field="review",
        extra_fields=("rating", "listing_id", "language", "created_timestamp"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toInt(created_timestamp))",
    fields=ETSY_FIELDS,
    where_clause="review IS NOT NULL AND review != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
