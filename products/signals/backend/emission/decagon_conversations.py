"""Signal emitter for decagon `conversations` (record kind: ticket).

`messages` is a JSON list of `{text, role, created_at}` objects, where role is USER or AI.
The description is built from the first few user messages. Conversations without user text are skipped.
`user_id` is not selected because it identifies the end user.
"""

from typing import Any

from structlog import get_logger

from products.signals.backend.emission._common import parse_json_list
from products.signals.backend.emission._prompts import TICKET_ACTIONABILITY_PROMPT, TICKET_SUMMARIZATION_PROMPT
from products.signals.backend.emission.fetchers.data_warehouse import data_warehouse_record_fetcher
from products.signals.backend.emission.registry import SignalEmitterOutput, SignalSourceTableConfig

logger = get_logger(__name__)

DECAGON_FIELDS = ("conversation_id", "created_at", "messages", "csat_rating", "tags")

MAX_USER_MESSAGES = 5
MAX_MESSAGE_CHARS = 1000


def _user_message_texts(raw_messages: Any) -> list[str]:
    texts: list[str] = []
    for message in parse_json_list(raw_messages):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        text = message.get("text")
        if not isinstance(role, str) or role.upper() != "USER":
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        texts.append(text.strip()[:MAX_MESSAGE_CHARS])
        if len(texts) >= MAX_USER_MESSAGES:
            break
    return texts


def decagon_conversation_emitter(team_id: int, record: dict[str, Any]) -> SignalEmitterOutput | None:
    try:
        conversation_id = record["conversation_id"]
    except KeyError as e:
        msg = f"Decagon conversation record missing required field {e}"
        logger.exception(msg, record=record, team_id=team_id, signals_type="data-import-signals")
        raise ValueError(msg) from e
    if not conversation_id:
        return None

    texts = _user_message_texts(record.get("messages"))
    if not texts:
        logger.info(
            "Ignoring Decagon conversation without user message text",
            team_id=team_id,
            signals_type="data-import-signals",
        )
        return None

    csat_rating = record.get("csat_rating")
    created_at = record.get("created_at")
    return SignalEmitterOutput(
        source_product="decagon",
        source_type="ticket",
        source_id=str(conversation_id),
        description="\n".join(texts),
        weight=1.0,
        extra={
            "csat_rating": None if csat_rating is None else str(csat_rating),
            "tags": parse_json_list(record.get("tags")),
            "created_at": None if created_at is None else str(created_at),
        },
    )


DECAGON_CONFIG = SignalSourceTableConfig(
    source_product="decagon",
    source_type="ticket",
    emitter=decagon_conversation_emitter,
    record_fetcher=data_warehouse_record_fetcher,
    partition_field="created_at",
    partition_field_is_datetime_string=True,
    fields=DECAGON_FIELDS,
    max_records=200,
    first_sync_lookback_days=1,
    actionability_prompt=TICKET_ACTIONABILITY_PROMPT,
    summarization_prompt=TICKET_SUMMARIZATION_PROMPT,
    description_summarization_threshold_chars=2000,
)
