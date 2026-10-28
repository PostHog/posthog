"""Signal emitter for sprig `Responses` (record kind: feedback).

Each row is one answer to one survey question, so the id is the submission id plus the question id.
`created_at` is an ISO string. `response` changes shape by question type, so it is read as a string.
Answers with no response and bare numeric answers (ratings, NPS scores) are skipped in the query,
so they do not use up the fetch limit. Visitor ids, snapshots and external user ids are not read.
"""

from products.signals.backend.emission._common import make_flat_emitter
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SPRIG_FIELDS = (
    "concat(toString(response_group_uid), ':', toString(question_id)) AS response_key",
    "question_text",
    "toString(response) AS response_text",
    "question_type",
    "survey_id",
    "created_at",
)

SPRIG_CONFIG = SignalSourceTableConfig(
    source_product="sprig",
    source_type="feedback",
    emitter=make_flat_emitter(
        source_product="sprig",
        source_type="feedback",
        id_field="response_key",
        title_field="question_text",
        body_field="response_text",
        extra_fields=("question_type", "survey_id", "created_at"),
    ),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=SPRIG_FIELDS,
    where_clause=(
        "response IS NOT NULL AND trim(toString(response)) != '' "
        "AND NOT match(trim(toString(response)), '^-?[0-9]+([.][0-9]+)?$')"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
