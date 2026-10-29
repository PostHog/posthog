"""Signal emitter for typeform `responses` (record kind: feedback).

`answers` is a JSON list. An answer with `type: text` is a typed-in answer (short or long text
field). Its `field.type` must be `short_text` or `long_text` when present, which drops dropdown
selections that also arrive as `type: text`. Choice, number, email, phone, date, url and file
answers are skipped. Hidden fields, metadata and variables are never selected. Response ids repeat
across forms, so the source id carries the form id.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import SurveyAnswer, make_survey_emitter, parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

TYPEFORM_FIELDS = ("response_id", "form_id", "submitted_at", "answers")

# Typeform field types that hold typed-in prose. Other fields can still answer with `type: text`
# (a dropdown selection, for one), so a known field type outside this set is skipped.
_FREE_TEXT_FIELD_TYPES = frozenset({"short_text", "long_text"})


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    answers = parse_json(record.get("answers"))
    if not isinstance(answers, list):
        return
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        field = answer.get("field")
        field_type = field.get("type") if isinstance(field, dict) else None
        if field_type is not None and field_type not in _FREE_TEXT_FIELD_TYPES:
            continue
        yield SurveyAnswer(kind=answer.get("type"), text=answer.get("text"))


def _source_id(record: dict[str, Any]) -> str | None:
    response_id = record["response_id"]
    if not response_id:
        return None
    form_id = record.get("form_id")
    return f"{form_id}:{response_id}" if form_id else str(response_id)


TYPEFORM_CONFIG = SignalSourceTableConfig(
    source_product="typeform",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="typeform",
        source_type="feedback",
        build_source_id=_source_id,
        extract_answers=_extract_answers,
        extra_fields=("form_id", "submitted_at"),
    ),
    unloggable_fields=("answers",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="submitted_at",
    partition_field_is_datetime_string=True,
    fields=TYPEFORM_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
