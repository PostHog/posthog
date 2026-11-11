"""Signal emitter for langsmith `feedback` (record kind: feedback).

Most LangSmith feedback is a bare score from an evaluator. Only rows with a human-readable
`comment` or `correction` carry a useful signal, so the query skips the rest.
`created_at` is an ISO string. `correction` and `value` can hold JSON, so both are read as text.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import FEEDBACK_ACTIONABILITY_PROMPT, FEEDBACK_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

LANGSMITH_FIELDS = (
    "id",
    "key",
    "score",
    "value",
    "comment",
    "correction",
    "run_id",
    "trace_id",
    "created_at",
)

LANGSMITH_EXTRA_FIELDS = ("key", "score", "value", "run_id", "trace_id", "created_at")

# An empty JSON correction serializes to one of these and carries no text. The query skips them
# so they do not use up the fetch limit, and the emitter drops them too as a backstop.
_EMPTY_TEXT_VALUES = ("", "{}", "[]", "null")


def _text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in _EMPTY_TEXT_VALUES else text


def langsmith_feedback_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        record_id = record["id"]
        key = record["key"]
    except KeyError as e:
        msg = f"langsmith record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    comment = _text(record.get("comment"))
    correction = _text(record.get("correction"))
    if not record_id or not (comment or correction):
        logger.info(
            "Ignoring langsmith record with empty id or no comment and correction",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    label = _text(key) or "feedback"
    lines = [f"{label}: {comment}" if comment else label]
    if correction:
        lines.append(f"Correction: {correction}")
    extra = {field: None if record.get(field) is None else str(record.get(field)) for field in LANGSMITH_EXTRA_FIELDS}
    return SignalEmitterOutput(
        source_product="langsmith",
        source_type="feedback",
        source_id=str(record_id),
        description="\n".join(lines),
        weight=1.0,
        extra=extra,
    )


LANGSMITH_CONFIG = SignalSourceTableConfig(
    source_product="langsmith",
    source_type="feedback",
    emitter=langsmith_feedback_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=LANGSMITH_FIELDS,
    where_clause=(
        "((comment IS NOT NULL AND trim(comment) != '') "
        "OR (correction IS NOT NULL AND trim(correction) NOT IN ('', '{}', '[]', 'null')))"
    ),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=FEEDBACK_ACTIONABILITY_PROMPT,
    summarization_prompt=FEEDBACK_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
