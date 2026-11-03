"""Signal emitter for surveysparrow `responses` (record kind: feedback).

`answers` is a JSON list. An item counts only when it embeds a question type naming a free-text
question and its answer is a string. Unknown answer shapes fail closed rather than treating string
choice labels as feedback. The source syncs completed responses only. The contact column is never
selected. Response ids are unique per survey, so the source id carries the survey id.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import SurveyAnswer, make_survey_emitter, parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SURVEYSPARROW_FIELDS = ("id", "survey_id", "completed", "completed_time", "answers")


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    answers = parse_json(record.get("answers"))
    if not isinstance(answers, list):
        return
    for item in answers:
        if not isinstance(item, dict):
            continue
        kind = item.get("question_type") or item.get("questionType") or item.get("type")
        value = item.get("answer", item.get("value"))
        if isinstance(value, dict):
            value = value.get("value", value.get("text"))
        yield SurveyAnswer(kind=kind, text=value)


def _source_id(record: dict[str, Any]) -> str | None:
    response_id, survey_id = record["id"], record["survey_id"]
    if response_id in (None, "") or survey_id in (None, ""):
        return None
    return f"{survey_id}:{response_id}"


SURVEYSPARROW_CONFIG = SignalSourceTableConfig(
    source_product="surveysparrow",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="surveysparrow",
        source_type="feedback",
        build_source_id=_source_id,
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "completed", "completed_time"),
    ),
    unloggable_fields=("answers",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="completed_time",
    partition_field_is_datetime_string=True,
    fields=SURVEYSPARROW_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
