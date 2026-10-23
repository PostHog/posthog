"""Signal emitter for vitally `Conversations` (record kind: ticket).

The list endpoint the importer syncs `Conversations` from does not return `messages`; message
bodies are fetched per conversation into the separate `Messages` table, which the fetcher cannot
join. The subject is the only text here.
`accountId` is not selected because it identifies the customer account.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

VITALLY_FIELDS = ("id", "subject", "created_at", "external_url")


def vitally_conversation_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        conversation_id = record["id"]
    except KeyError as e:
        msg = f"Vitally conversation record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not conversation_id:
        return None

    subject = record.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        logger.info(
            "Ignoring Vitally conversation without subject",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None

    created_at = record.get("created_at")
    external_url = record.get("external_url")
    return SignalEmitterOutput(
        source_product="vitally",
        source_type="ticket",
        source_id=str(conversation_id),
        description=subject.strip(),
        weight=1.0,
        extra={
            "external_url": external_url or None,
            "created_at": None if created_at is None else str(created_at),
        },
    )


VITALLY_CONFIG = SignalSourceTableConfig(
    source_product="vitally",
    source_type="ticket",
    emitter=vitally_conversation_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=VITALLY_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
