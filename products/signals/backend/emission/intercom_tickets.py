"""Signal emitter for intercom `tickets` (record kind: ticket).

Like `intercom_conversations.py`, the text is not a top-level column. It is in the
`ticket_attributes` JSON, under the default `_default_title_` and `_default_description_` keys.
The query reads only those two keys, because custom attributes can hold contact details.
`ticket_state` and `ticket_type` are objects, so the query reads the state category
(submitted, in_progress, waiting_on_customer, resolved) and the type name from them.
`created_at` is a Unix epoch (seconds), the same as on conversations.

The source product is `intercom_tickets`, not `intercom`: the config row is unique per
(source_product, source_type), so a shared product would turn this table on with the
existing Intercom conversations toggle.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import build_extra, strip_html
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

_STATE_CATEGORY = "JSONExtractString(ticket_state, 'category')"

INTERCOM_TICKETS_FIELDS = (
    "id",
    "ticket_id",
    "category",
    "JSONExtractString(ticket_attributes, '_default_title_') AS ticket_title",
    "JSONExtractString(ticket_attributes, '_default_description_') AS ticket_description",
    f"{_STATE_CATEGORY} AS ticket_state_category",
    "JSONExtractString(ticket_type, 'name') AS ticket_type_name",
    "created_at",
)

INTERCOM_TICKETS_EXTRA_FIELDS = ("ticket_id", "category", "ticket_state_category", "ticket_type_name", "created_at")


def intercom_ticket_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        ticket_id = record["id"]
    except KeyError as e:
        msg = f"Intercom ticket record missing required field {e}"
        logger.exception(msg, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not ticket_id:
        logger.info("Ignoring Intercom ticket with empty id", team_id=team_id, signals_type="data-import-signals")
        return None

    title = strip_html(record.get("ticket_title"))
    body = strip_html(record.get("ticket_description"))
    if not title and not body:
        logger.info("Ignoring Intercom ticket without text", team_id=team_id, signals_type="data-import-signals")
        return None
    description = f"{title}\n{body}" if title and body else title or body

    # JSONExtractString returns '' for a missing key, so empty strings become None like absent columns.
    extra = {key: value or None for key, value in build_extra(record, INTERCOM_TICKETS_EXTRA_FIELDS, ()).items()}

    return SignalEmitterOutput(
        source_product="intercom_tickets",
        source_type="ticket",
        source_id=str(ticket_id),
        description=description,
        weight=1.0,
        extra=extra,
    )


INTERCOM_TICKETS_CONFIG = SignalSourceTableConfig(
    source_product="intercom_tickets",
    source_type="ticket",
    emitter=intercom_ticket_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="fromUnixTimestamp(toInt(created_at))",
    fields=INTERCOM_TICKETS_FIELDS,
    where_clause=f"{_STATE_CATEGORY} != 'resolved'",
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
