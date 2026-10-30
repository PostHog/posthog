"""Signal emitter for monday `items` (record kind: issue).

The item text lives in `column_values`, a JSON list of `{id, type, text, value}` objects. Only the
`text` and `long_text` column types are read, so people, email and phone columns never reach a signal.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig, redacted_record

logger = get_logger(__name__)

MONDAY_FIELDS = (
    "id",
    "name",
    "state",
    "JSONExtractString(`group`, 'title') AS group_title",
    "column_values",
    "created_at",
    "_board_id AS board_id",
)

TEXT_COLUMN_TYPES = ("text", "long_text")
# `column_values` also holds people, email and phone column text, so it never goes to the logs.
UNLOGGABLE_FIELDS = ("column_values",)
MAX_BODY_CHARS = 4000


def monday_body(raw: Any) -> str:
    parts: list[str] = []
    for column in parse_json_list(raw):
        if not isinstance(column, dict) or column.get("type") not in TEXT_COLUMN_TYPES:
            continue
        text = column.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)[:MAX_BODY_CHARS]


def monday_item_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        item_id = record["id"]
        name = record["name"]
    except KeyError as e:
        msg = f"Monday item record missing required field {e}"
        logger.exception(
            msg, record=redacted_record(record, UNLOGGABLE_FIELDS), team_id=team_id, signals_type="data-import-signals"
        )
        raise ValueError(msg) from e
    if not item_id or not name:
        logger.info("Ignoring Monday item with empty id or name", team_id=team_id, signals_type="data-import-signals")
        return None
    body = monday_body(record.get("column_values"))
    created_at = record.get("created_at")
    board_id = record.get("board_id")
    return SignalEmitterOutput(
        source_product="monday",
        source_type="issue",
        source_id=str(item_id),
        description=f"{name}\n{body}" if body else str(name),
        weight=1.0,
        extra={
            "state": record.get("state") or None,
            "group": record.get("group_title") or None,
            "board_id": None if board_id is None else str(board_id),
            "created_at": None if created_at is None else str(created_at),
        },
    )


MONDAY_CONFIG = SignalSourceTableConfig(
    source_product="monday",
    source_type="issue",
    emitter=monday_item_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=MONDAY_FIELDS,
    unloggable_fields=UNLOGGABLE_FIELDS,
    where_clause="ifNull(state, '') NOT IN ('archived', 'deleted')",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
