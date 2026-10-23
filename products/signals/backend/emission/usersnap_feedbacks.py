"""Signal emitter for usersnap `feedbacks` (record kind: feedback).

The feedback text lives in `ordered_inputs`, a JSON list of form field values. Only a field's
`text_value` counts. Email, client, custom data and screenshot columns are never selected.
"""

from collections.abc import Iterable
from typing import Any

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import (
    SurveyAnswer,
    looks_like_contact_key,
    make_survey_emitter,
    parse_json,
)
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

USERSNAP_FIELDS = (
    "feedback_id",
    "feedback_number",
    "public_link",
    "created_at",
    "status_type",
    "priority",
    "labels",
    "ordered_inputs",
)


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    inputs = parse_json(record.get("ordered_inputs"))
    if not isinstance(inputs, list):
        return
    for item in inputs:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        label = label.strip() if isinstance(label, str) else None
        # A custom form field can collect contact details as text; skip those by label.
        if label and looks_like_contact_key(label):
            continue
        yield SurveyAnswer(kind="text", text=item.get("text_value"), label=label or None)


USERSNAP_CONFIG = SignalSourceTableConfig(
    source_product="usersnap",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="usersnap",
        source_type="feedback",
        build_source_id=lambda record: record["feedback_id"],
        extract_answers=_extract_answers,
        extra_fields=("feedback_number", "public_link", "status_type", "priority", "labels", "created_at"),
        json_list_fields=("labels",),
    ),
    unloggable_fields=("ordered_inputs",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=USERSNAP_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
