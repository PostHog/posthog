"""Signal emitter for featurebase `survey_responses` (record kind: feedback).

`responses` is a JSON list of answers, each with a `type` (text, link, rating or multiple-choice)
and a `value`. Only `text` answers reach the description, and a response with none is skipped.
The `user` column is never selected, because it identifies the respondent.

This table has its own product value, so the existing `featurebase` toggle for `posts` keeps its
behavior.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import SurveyAnswer, make_survey_emitter, parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

FEATUREBASE_SURVEY_FIELDS = ("id", "survey_id", "responses", "created_at")


def _source_id(record: dict[str, Any]) -> str | None:
    # The warehouse keys rows on (surveyId, id), so a response id alone can repeat across surveys.
    response_id = record["id"]
    if not response_id:
        return None
    survey_id = record.get("survey_id")
    return f"{survey_id}:{response_id}" if survey_id else str(response_id)


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    answers = parse_json(record.get("responses"))
    if not isinstance(answers, list):
        return
    for item in answers:
        if isinstance(item, dict):
            yield SurveyAnswer(kind=item.get("type"), text=item.get("value"))


FEATUREBASE_SURVEY_CONFIG = SignalSourceTableConfig(
    source_product="featurebase_surveys",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="featurebase_surveys",
        source_type="feedback",
        build_source_id=_source_id,
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "created_at"),
    ),
    unloggable_fields=("responses",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=FEATUREBASE_SURVEY_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
