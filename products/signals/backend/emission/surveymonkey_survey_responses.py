"""Signal emitter for surveymonkey `survey_responses` (record kind: feedback).

`pages` is JSON: pages[].questions[].answers[]. A free-text answer is an item with a `text` and no
choice, row or column id (open-ended questions, and the text box of an "other" choice). Only
`response_status = 'completed'` rows are fetched. The `ip_address` and `recipient_id` columns are
never selected.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import SurveyAnswer, make_survey_emitter, parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SURVEYMONKEY_FIELDS = ("id", "survey_id", "date_created", "response_status", "pages")

_STRUCTURED_ANSWER_KEYS = ("choice_id", "row_id", "col_id", "col_choice_id", "tag_data")


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    pages = parse_json(record.get("pages"))
    if not isinstance(pages, list):
        return
    for page in pages:
        for question in (page.get("questions") if isinstance(page, dict) else None) or []:
            for answer in (question.get("answers") if isinstance(question, dict) else None) or []:
                if not isinstance(answer, dict):
                    continue
                if any(answer.get(key) for key in _STRUCTURED_ANSWER_KEYS) and not answer.get("other_id"):
                    continue
                yield SurveyAnswer(kind="text", text=answer.get("text"))


SURVEYMONKEY_CONFIG = SignalSourceTableConfig(
    source_product="surveymonkey",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="surveymonkey",
        source_type="feedback",
        build_source_id=lambda record: record["id"],
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "date_created", "response_status"),
    ),
    unloggable_fields=("pages",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date_created",
    partition_field_is_datetime_string=True,
    fields=SURVEYMONKEY_FIELDS,
    where_clause="response_status = 'completed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
