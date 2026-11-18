"""Signal emitter for pylon `issues` (record kind: ticket).

An issue is a support conversation or ticket. The text is `title` plus `body_html`, which is HTML,
so the emitter strips the tags. `title` can be empty for chat-started issues, so the body is the fallback.
`state` is new, waiting_on_you, waiting_on_customer, on_hold, closed, or a custom slug.
`created_at` is an RFC 3339 string. The requester, assignee and account objects are not read.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra, strip_html
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

PYLON_FIELDS = (
    "id",
    "number",
    "title",
    "body_html",
    "state",
    "type",
    "link",
    "created_at",
)

PYLON_EXTRA_FIELDS = ("number", "state", "type", "link", "created_at")


def pylon_issue_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        issue_id = record["id"]
    except KeyError as e:
        msg = f"Pylon issue record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not issue_id:
        logger.info("Ignoring Pylon issue with empty id", team_id=team_id, signals_type="data-import-signals")
        return None

    raw_title = record.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    body = strip_html(record.get("body_html"))
    if not title and not body:
        logger.info("Ignoring Pylon issue without text", team_id=team_id, signals_type="data-import-signals")
        return None
    description = f"{title}\n{body}" if title and body else title or body

    return SignalEmitterOutput(
        source_product="pylon",
        source_type="ticket",
        source_id=str(issue_id),
        description=description,
        weight=1.0,
        extra=build_extra(record, PYLON_EXTRA_FIELDS, ()),
    )


PYLON_CONFIG = SignalSourceTableConfig(
    source_product="pylon",
    source_type="ticket",
    emitter=pylon_issue_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=PYLON_FIELDS,
    where_clause="state != 'closed'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
