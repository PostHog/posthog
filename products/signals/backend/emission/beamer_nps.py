"""Signal emitter for beamer `nps` (record kind: feedback).

`feedback` is the free-text comment left with the score. A bare score with no comment is skipped.
`date` is an ISO string. The user id, email and page url are not read, because they identify the user.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

BEAMER_NPS_FIELDS = ("id", "feedback", "score", "date")

BEAMER_NPS_CONFIG = SignalSourceTableConfig(
    source_product="beamer_nps",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="beamer_nps",
        source_type="feedback",
        id_field="id",
        title_field="feedback",
        extra_fields=("score", "date"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date",
    partition_field_is_datetime_string=True,
    fields=BEAMER_NPS_FIELDS,
    where_clause="feedback IS NOT NULL AND feedback != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
