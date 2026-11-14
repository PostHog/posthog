"""Signal emitter for yotpo `reviews` (record kind: review).

`content` is the review text, `title` its headline and `score` the star rating. `created_at` is an
ISO string. Reviews with no text are skipped. `deleted` marks an unpublished review, which is kept,
because a hidden negative review is often the most actionable one. The reviewer name and email
are not read, because they identify the customer.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

YOTPO_FIELDS = (
    "id",
    "if(title IS NULL OR title = '', content, concat(title, '\\n', content)) AS review_text",
    "score",
    "sku",
    "deleted",
    "created_at",
)

YOTPO_CONFIG = SignalSourceTableConfig(
    source_product="yotpo",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="yotpo",
        source_type="review",
        id_field="id",
        title_field="review_text",
        extra_fields=("score", "sku", "deleted", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=YOTPO_FIELDS,
    where_clause="content IS NOT NULL AND content != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
