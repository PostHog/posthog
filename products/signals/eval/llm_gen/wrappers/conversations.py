from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import stable_int, stable_uuid


def wrap_as_conversations_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    ticket_id = stable_uuid(seed, idx, "conversations.id")
    ticket_number = (stable_int(seed, idx, "conversations.num", bits=20) % 9000) + 1000
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "id": ticket_id,
        "ticket_number": ticket_number,
        "channel_source": "intercom",
        "channel_detail": "intercom_conversation",
        "status": "open",
        "priority": "normal",
        "created_at": now,
        "email_subject": signal.title,
        "messages": [["customer", signal.body]],
    }
