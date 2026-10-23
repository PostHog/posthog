"""Signal emitter for okendo `reviews` (record kind: review).

`date_created` is an ISO string; `body` is the review text, `rating` the star rating.
`status` is approved, pending or rejected. Rejected reviews and reviews with no text are skipped.
The title is optional, so the signal text is the title and body, or the body alone when there is no title.
The reviewer and order columns are not read, because they identify the customer.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import REVIEW_ACTIONABILITY_PROMPT, REVIEW_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

OKENDO_FIELDS = (
    "review_id",
    "if(title IS NULL OR title = '', body, concat(title, '\\n', body)) AS review_text",
    "rating",
    "status",
    "product_name",
    "is_recommended",
    "date_created",
)

OKENDO_CONFIG = SignalSourceTableConfig(
    source_product="okendo",
    source_type="review",
    emitter=make_flat_emitter(
        source_product="okendo",
        source_type="review",
        id_field="review_id",
        title_field="review_text",
        extra_fields=("rating", "status", "product_name", "is_recommended", "date_created"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date_created",
    partition_field_is_datetime_string=True,
    fields=OKENDO_FIELDS,
    where_clause="body IS NOT NULL AND body != '' AND status != 'rejected'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=REVIEW_ACTIONABILITY_PROMPT,
    summarization_prompt=REVIEW_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
