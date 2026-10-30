"""Signal emitter for survicate `responses` (record kind: feedback).

`answers` is a JSON list of answered questions. An item counts only when its type names a free-text
question and its value is a string. The respondent and attribute columns are never selected, and
the page url loses its credentials, query string and fragment.
"""

from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission._survey import SurveyAnswer, make_survey_emitter, parse_json
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalSourceTableConfig

SURVICATE_FIELDS = ("uuid", "survey_id", "collected_at", "answers", "url")


def _extract_answers(record: dict[str, Any]) -> Iterable[SurveyAnswer]:
    answers = parse_json(record.get("answers"))
    if not isinstance(answers, list):
        return
    for item in answers:
        if not isinstance(item, dict):
            continue
        value = item.get("answer", item.get("value"))
        kind = item.get("type") or item.get("question_type") or item.get("answer_type")
        if isinstance(value, dict):
            kind = kind or value.get("type")
            value = value.get("value", value.get("text"))
        yield SurveyAnswer(kind=kind, text=value)


def _strip_url_query(extra: dict[str, Any]) -> dict[str, Any]:
    """Keep scheme, host, port and path. Drop userinfo, query string and fragment."""
    url = extra.get("url")
    if url:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            extra["url"] = None
            return extra
        if parts.hostname:
            authority = f"{parts.hostname}:{port}" if port else parts.hostname
            extra["url"] = f"{parts.scheme}://{authority}{parts.path}"
        else:
            # A relative page path carries no host, so keep the path alone.
            extra["url"] = parts.path or None
    return extra


SURVICATE_CONFIG = SignalSourceTableConfig(
    source_product="survicate",
    source_type="feedback",
    emitter=make_survey_emitter(
        source_product="survicate",
        source_type="feedback",
        build_source_id=lambda record: record["uuid"],
        extract_answers=_extract_answers,
        extra_fields=("survey_id", "collected_at", "url"),
        transform_extra=_strip_url_query,
    ),
    unloggable_fields=("answers", "url"),
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="collected_at",
    partition_field_is_datetime_string=True,
    fields=SURVICATE_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
