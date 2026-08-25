"""Signal emitter for retently `feedback` (record kind: feedback).

Uses the free-text `comment` — scoreless/comment-less responses are skipped. `createdDate` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

RETENTLY_FIELDS = ("id", "comment", "score", "ratingCategory", "feedbackTopics", "resolved", "createdDate")

RETENTLY_CONFIG = SignalSourceTableConfig(
    source_product="retently",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="retently",
        source_type="feedback",
        id_field="id",
        title_field="comment",
        extra_fields=("score", "ratingCategory", "feedbackTopics", "resolved", "createdDate"),
        json_list_fields=("feedbackTopics",),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="createdDate",
    partition_field_is_datetime_string=True,
    fields=RETENTLY_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
