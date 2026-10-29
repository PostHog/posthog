"""Signal emitter for asana `tasks` (record kind: issue).

`projects` and `tags` are JSON lists of objects; only their names are kept. Section and milestone
rows are not work to act on, so they are skipped along with completed tasks.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._prompts import ISSUE_ACTIONABILITY_PROMPT, ISSUE_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

ASANA_FIELDS = (
    "gid",
    "name",
    "notes",
    "created_at",
    "permalink_url",
    "resource_subtype",
    "projects",
    "tags",
)

MAX_NOTES_CHARS = 4000


def names_from_json_list(raw: Any) -> list[str]:
    """Names from a JSON list of `{"name": ...}` objects. Entries without a name are dropped."""
    return [str(item["name"]) for item in parse_json_list(raw) if isinstance(item, dict) and item.get("name")]


def asana_task_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        gid = record["gid"]
        name = record["name"]
    except KeyError as e:
        msg = f"Asana task record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not gid or not name:
        logger.info("Ignoring Asana task with empty gid or name", team_id=team_id, signals_type="data-import-signals")
        return None
    notes = record.get("notes")
    body = str(notes).strip()[:MAX_NOTES_CHARS] if notes else ""
    created_at = record.get("created_at")
    return SignalEmitterOutput(
        source_product="asana",
        source_type="issue",
        source_id=str(gid),
        description=f"{name}\n{body}" if body else str(name),
        weight=1.0,
        extra={
            "url": record.get("permalink_url") or None,
            "resource_subtype": record.get("resource_subtype") or None,
            "created_at": None if created_at is None else str(created_at),
            "projects": names_from_json_list(record.get("projects")),
            "tags": names_from_json_list(record.get("tags")),
        },
    )


ASANA_CONFIG = SignalSourceTableConfig(
    source_product="asana",
    source_type="issue",
    emitter=asana_task_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=ASANA_FIELDS,
    where_clause=("NOT ifNull(completed, false) AND ifNull(resource_subtype, '') NOT IN ('section', 'milestone')"),
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=ISSUE_ACTIONABILITY_PROMPT,
    summarization_prompt=ISSUE_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
