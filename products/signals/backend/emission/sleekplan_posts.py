"""Signal emitter for sleekplan `Posts` (record kind: feedback).

`created` is a datetime string; `description` is the plain-text post body.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SLEEKPLAN_FIELDS = (
    "feedback_id",
    "title",
    "description",
    "status",
    "type",
    "total_up",
    "created",
)

SLEEKPLAN_CONFIG = SignalSourceTableConfig(
    source_product="sleekplan",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="sleekplan",
        source_type="feedback",
        id_field="feedback_id",
        title_field="title",
        body_field="description",
        extra_fields=("status", "type", "total_up", "created"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created",
    partition_field_is_datetime_string=True,
    fields=SLEEKPLAN_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
