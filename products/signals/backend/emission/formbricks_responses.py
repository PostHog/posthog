"""Signal emitter for formbricks `responses` (record kind: feedback).

`data` is a JSON map of question id to answer, with no question types. Heuristic: keep a string
answer only when it is at least `MIN_FREE_TEXT_CHARS` long and has whitespace, which drops
short choices, ids, emails and urls. Keys that look like contact fields are skipped because
hidden field values also live in `data`. The contact, contact attribute and meta columns are never
selected.
"""

import re
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

FORMBRICKS_FIELDS = ("id", "survey_id", "finished", "data", "created_at")

MIN_FREE_TEXT_CHARS = 15
_URL_RE = re.compile(r"^https?://\S+$")


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    data = parse_json(record.get("data"))
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if not isinstance(value, str) or looks_like_contact_key(key) or "user" in str(key).lower():
            continue
        text = value.strip()
        if len(text) < MIN_FREE_TEXT_CHARS or not re.search(r"\s", text) or _URL_RE.match(text):
            continue
        yield SurveyAnswer(kind="text", text=text)


FORMBRICKS_CONFIG = SignalSourceTableConfig(
    source_product="formbricks",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="formbricks",
        source_type="feedback",
        build_source_id=lambda record: record["id"],
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "finished", "created_at"),
    ),
    unloggable_fields=("data",),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=FORMBRICKS_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
