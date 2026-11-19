"""Signal emitter for uservoice `nps_ratings` (record kind: feedback).

`comment` is the optional free-text comment left with the 0-10 rating. A bare rating with no
comment is skipped. `created_at` is an ISO string.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

USERVOICE_NPS_FIELDS = ("id", "comment", "rating", "created_at")

USERVOICE_NPS_CONFIG = SignalSourceTableConfig(
    source_product="uservoice_nps",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="uservoice_nps",
        source_type="feedback",
        id_field="id",
        title_field="comment",
        extra_fields=("rating", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=USERVOICE_NPS_FIELDS,
    where_clause="comment IS NOT NULL AND comment != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
