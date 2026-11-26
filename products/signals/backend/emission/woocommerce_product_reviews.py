"""Signal emitter for woocommerce `product_reviews` (record kind: review).

`review` is HTML, so the query strips the tags. `date_created_gmt` is an ISO string. Spam and
trashed reviews are skipped, and so are reviews with no text. The reviewer name and email are not
read, because they identify the customer.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

WOOCOMMERCE_FIELDS = (
    "id",
    "trim(replaceRegexpAll(review, '<[^>]+>', ' ')) AS review_text",
    "rating",
    "status",
    "verified",
    "product_id",
    "date_created_gmt",
)

WOOCOMMERCE_CONFIG = SignalSourceTableConfig(
    source_product="woocommerce",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="woocommerce",
        source_type="review",
        id_field="id",
        title_field="review_text",
        extra_fields=("rating", "status", "verified", "product_id", "date_created_gmt"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date_created_gmt",
    partition_field_is_datetime_string=True,
    fields=WOOCOMMERCE_FIELDS,
    where_clause="review IS NOT NULL AND review != '' AND status NOT IN ('spam', 'trash')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
