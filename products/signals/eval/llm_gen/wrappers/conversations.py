import hashlib
from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal


def _stable_int(seed: int, idx: int, salt: str, *, bits: int = 48) -> int:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return int(h[: bits // 4], 16)


def _stable_uuid(seed: int, idx: int, salt: str) -> str:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def wrap_as_conversations_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    ticket_id = _stable_uuid(seed, idx, "conversations.id")
    ticket_number = (_stable_int(seed, idx, "conversations.num", bits=20) % 9000) + 1000
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
