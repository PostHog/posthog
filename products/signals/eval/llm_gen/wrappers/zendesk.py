import json
from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import stable_int


def wrap_as_zendesk_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    ticket_id = (stable_int(seed, idx, "zendesk.id", bits=24) % 900000) + 100000
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
