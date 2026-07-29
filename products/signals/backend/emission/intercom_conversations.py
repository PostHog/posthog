"""Signal emitter for intercom `conversations` (record kind: ticket).

Intercom is OAuth-connected and its `conversations` table isn't flat, so this is a bespoke
emitter (like Jira's):
- The opening message isn't a top-level column — it lives in the `source` JSON blob
  (`source.body`, HTML). `title` is often null, so we fall back to the stripped source body.
  The rest of the thread is in `conversation_parts` (a separate table we don't sync).
- `created_at` is a Unix epoch (seconds), so the partition cursor wraps it in
  `fromUnixTimestamp(...)`. Verify the stored type on the first real sync.
"""

import re
from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

INTERCOM_IGNORED_STATES = ("closed",)

FIELDS = (
    "id",
    "title",
    "state",
    "priority",
    "admin_assignee_id",
    "created_at",
    "JSONExtractString(source, 'body') AS source_body",
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: Any) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    return _TAG_RE.sub(" ", raw).replace("&nbsp;", " ").strip()


def intercom_conversation_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        conversation_id = record["id"]
    except KeyError as e:
        msg = f"Intercom conversation record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not conversation_id:
        msg = f"Intercom conversation record has empty id: {conversation_id!r}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg)

    title = record.get("title")
    body = _strip_html(record.get("source_body"))
    # Prefer an explicit subject; otherwise use the opening message. Skip conversations with no
    # readable text (auto-created/empty ones can't produce a useful signal).
    description = title or body
    if not description:
        logger.info(
            "Ignoring Intercom conversation without text",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None
    if title and body:
        description = f"{title}\n{body}"

    return SignalEmitterOutput(
        source_product="intercom",
        source_type="ticket",
        source_id=str(conversation_id),
        description=description,
        weight=1.0,
        extra={
            "state": record.get("state") or None,
            "priority": record.get("priority") or None,
            "admin_assignee_id": (
                str(record["admin_assignee_id"]) if record.get("admin_assignee_id") is not None else None
            ),
            "created_at": str(record["created_at"]) if record.get("created_at") is not None else None,
        },
    )


INTERCOM_CONFIG = SignalSourceTableConfig(
    source_product="intercom",
    source_type="ticket",
    emitter=intercom_conversation_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    # created_at is a Unix epoch (seconds). Wrap so the cursor compares as a datetime; verify the
    # stored column type on the first real sync (it may already be a DateTime).
    partition_field="fromUnixTimestamp(toUInt32(created_at))",
    fields=FIELDS,
    where_clause=f"state NOT IN ({', '.join(repr(s) for s in INTERCOM_IGNORED_STATES)})",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
