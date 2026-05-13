import copy
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import load_template, now_iso, stable_int


def wrap_as_zendesk_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    record = copy.deepcopy(load_template("zendesk_tickets.json"))
    record["subject"] = signal.title
    record["description"] = signal.body
    ticket_id = (stable_int(seed, idx, "zendesk.id", bits=24) % 900000) + 100000
    record["id"] = str(ticket_id)
    record["url"] = f"https://posthoghelp.zendesk.com/api/v2/tickets/{ticket_id}.json"
    record["created_at"] = now_iso()
    return record
