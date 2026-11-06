"""Signal emitter for qualtrics `survey_responses` (record kind: feedback).

`values` is a JSON map of question id to raw answer, mixed with embedded data. Only keys that end
in `_TEXT` (text entry questions and "other" text boxes) are read, so choice codes and embedded
data such as recipient details never reach the description. Embedded data keys that look like
contact fields (e.g. `shipping_address_TEXT`) are skipped too. Unfinished responses are skipped in
Python because the stored type of `finished` (bool or 0/1) is not certain.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import (
    SurveyAnswer,
    is_explicitly_false,
    looks_like_contact_key,
    make_survey_emitter,
    parse_json,
)
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

QUALTRICS_FIELDS = ("response_id", "survey_id", "recorded_date", "finished", "values")


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    values = parse_json(record.get("values"))
    if not isinstance(values, dict):
        return
    for key, value in values.items():
        if isinstance(key, str) and key.endswith("_TEXT") and not looks_like_contact_key(key):
            yield SurveyAnswer(kind="text", text=value)


QUALTRICS_CONFIG = SignalSourceTableConfig(
    source_product="qualtrics",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="qualtrics",
        source_type="feedback",
        build_source_id=lambda record: record["response_id"],
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "recorded_date", "finished"),
        is_eligible=lambda record: not is_explicitly_false(record.get("finished")),
    ),
    unloggable_fields=("values",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="recorded_date",
    partition_field_is_datetime_string=True,
    fields=QUALTRICS_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
