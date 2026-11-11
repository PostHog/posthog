"""Signal emitter for gainsight_px `survey_responses` (record kind: feedback).

`date` is a timestamp (the import converts the API's epoch milliseconds); `comment` is the free-text answer.
Responses with no comment are skipped. The identify, account and session id columns are not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

GAINSIGHT_PX_FIELDS = (
    "event_id",
    "comment",
    "score",
    "question_type",
    "content_type",
    "engagement_id",
    "date",
)

GAINSIGHT_PX_CONFIG = SignalSourceTableConfig(
    source_product="gainsight_px",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="gainsight_px",
        source_type="feedback",
        id_field="event_id",
        title_field="comment",
        extra_fields=("score", "question_type", "content_type", "engagement_id", "date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date",
    fields=GAINSIGHT_PX_FIELDS,
    where_clause="comment IS NOT NULL AND comment != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
