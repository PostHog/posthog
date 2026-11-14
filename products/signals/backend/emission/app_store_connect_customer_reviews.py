"""Signal emitter for App Store Connect `customer_reviews` (record kind: review).

Apple's camelCase attributes land snake_case in the warehouse (`createdDate` becomes
`created_date`). `title` and `body` are the review text, `rating` the star rating.
`reviewer_nickname` is deliberately not selected.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

APP_STORE_CONNECT_FIELDS = ("id", "app_id", "title", "body", "rating", "territory", "created_date")

APP_STORE_CONNECT_CONFIG = SignalSourceTableConfig(
    source_product="app_store_connect",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="app_store_connect",
        source_type="review",
        id_field="id",
        title_field="title",
        body_field="body",
        extra_fields=("app_id", "rating", "territory", "created_date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_date",
    partition_field_is_datetime_string=True,
    fields=APP_STORE_CONNECT_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
