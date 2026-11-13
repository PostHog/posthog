"""Signal emitter for beamer `feature_requests` (record kind: feedback).

The title and body live in `translations`, a JSON list with one `{title, content, language,
permalink}` item per language. The English item is used when there is one, else the first item.
`date` is an ISO string. The user id and email are not read, because they identify the user.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra, parse_json_list
from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

BEAMER_FIELDS = ("id", "translations", "status", "category", "votes_count", "comments_count", "date")
BEAMER_EXTRA_FIELDS = ("status", "category", "votes_count", "comments_count", "date")
MAX_DESCRIPTION_CHARS = 4000


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _pick_translation(raw: Any) -> dict[str, Any] | None:
    translations = [item for item in parse_json_list(raw) if isinstance(item, dict) and _text(item.get("title"))]
    if not translations:
        return None
    english = next((item for item in translations if _text(item.get("language")).lower() == "en"), None)
    return english or translations[0]


def beamer_feature_request_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        request_id = record["id"]
    except KeyError as e:
        msg = f"Beamer feature request record missing required field {e}"
        logger.exception(msg, record_keys=list(record), team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not request_id:
        return None

    translation = _pick_translation(record.get("translations"))
    if translation is None:
        logger.info(
            "Ignoring Beamer feature request without a title", team_id=team_id, signals_type="data-import-signals"
        )
        return None

    title = _text(translation.get("title"))
    content = _text(translation.get("content"))
    description = (f"{title}\n{content}" if content else title)[:MAX_DESCRIPTION_CHARS]
    extra = build_extra(record, BEAMER_EXTRA_FIELDS, ())
    extra["permalink"] = _text(translation.get("permalink")) or None
    return SignalEmitterOutput(
        source_product="beamer",
        source_type="feedback",
        source_id=str(request_id),
        description=description,
        weight=1.0,
        extra=extra,
    )


BEAMER_CONFIG = SignalSourceTableConfig(
    source_product="beamer",
    source_type="feedback",
    emitter=beamer_feature_request_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="date",
    partition_field_is_datetime_string=True,
    fields=BEAMER_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
