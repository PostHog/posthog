"""Signal emitter for aha `ideas` (record kind: feedback).

`created_at` is an ISO string; `workflow_status` is a nested object coerced to text in extra.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

AHA_FIELDS = ("id", "name", "workflow_status", "score", "votes", "url", "created_at")

AHA_CONFIG = SignalSourceTableConfig(
    source_product="aha",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="aha",
        source_type="feedback",
        id_field="id",
        title_field="name",
        extra_fields=("workflow_status", "score", "votes", "url", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=AHA_FIELDS,
    max_records=500,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
