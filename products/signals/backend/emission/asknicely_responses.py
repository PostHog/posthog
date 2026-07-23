"""Signal emitter for asknicely `responses` (record kind: feedback).

Uses the free-text `comment` as the signal — NPS responses without a comment are skipped by the emitter. Record id is `response_id`; `created` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

ASKNICELY_FIELDS = ("response_id", "comment", "score", "status", "question_type", "segment", "created")

ASKNICELY_CONFIG = SignalSourceTableConfig(
    source_product="asknicely",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="asknicely",
        source_type="feedback",
        id_field="response_id",
        title_field="comment",
        extra_fields=("score", "status", "question_type", "segment", "created"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created",
    partition_field_is_datetime_string=True,
    fields=ASKNICELY_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
