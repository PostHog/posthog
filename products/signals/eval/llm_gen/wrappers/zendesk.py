import json
import hashlib
from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal


def _stable_int(seed: int, idx: int, salt: str, *, bits: int = 48) -> int:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return int(h[: bits // 4], 16)


def wrap_as_zendesk_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    ticket_id = (_stable_int(seed, idx, "zendesk.id", bits=24) % 900000) + 100000
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "id": str(ticket_id),
        "subject": signal.title,
        "description": signal.body,
        "url": f"https://posthoghelp.zendesk.com/api/v2/tickets/{ticket_id}.json",
        "type": "question",
        "tags": json.dumps(["llm_gen"]),
        "created_at": now,
        "priority": "normal",
        "status": "open",
    }
