"""Signal emitter for discourse `posts` (record kind: feedback).

`created_at` is an ISO string; `raw` is the Markdown post body.
Only the opening post of each topic is read, so replies do not flood the inbox.
Hidden and deleted posts are skipped. The username and user id columns are not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

DISCOURSE_FIELDS = (
    "id",
    "topic_id",
    "topic_title",
    "raw",
    "category_id",
    "created_at",
)

DISCOURSE_CONFIG = SignalSourceTableConfig(
    source_product="discourse",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="discourse",
        source_type="feedback",
        id_field="id",
        title_field="topic_title",
        body_field="raw",
        extra_fields=("topic_id", "category_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=DISCOURSE_FIELDS,
    where_clause="post_number = 1 AND (hidden IS NULL OR hidden = false) AND deleted_at IS NULL",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
