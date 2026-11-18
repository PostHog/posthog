"""Signal emitter for chameleon `responses` (record kind: feedback).

`input_text` is the free-text comment a user typed into a Microsurvey. Responses with no comment,
such as a bare button click, are skipped. `button_text` is kept as context (for example the score
the user picked). `profile_id` and the page url are not read, because they identify the user.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

CHAMELEON_FIELDS = ("id", "input_text", "button_text", "survey_id", "created_at")

CHAMELEON_CONFIG = SignalSourceTableConfig(
    source_product="chameleon",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="chameleon",
        source_type="feedback",
        id_field="id",
        title_field="input_text",
        extra_fields=("button_text", "survey_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=CHAMELEON_FIELDS,
    where_clause="input_text IS NOT NULL AND input_text != ''",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
