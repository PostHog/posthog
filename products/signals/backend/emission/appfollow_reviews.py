"""Signal emitter for appfollow `reviews` (record kind: review).

`date` is an ISO string; `content` is the review body, `rating` the star rating.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

APPFOLLOW_FIELDS = ("id", "title", "content", "rating", "store", "app_version", "date")

APPFOLLOW_CONFIG = SignalSourceTableConfig(
    source_product="appfollow",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="appfollow",
        source_type="review",
        id_field="id",
        title_field="title",
        body_field="content",
        extra_fields=("rating", "store", "app_version", "date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date",
    partition_field_is_datetime_string=True,
    fields=APPFOLLOW_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
