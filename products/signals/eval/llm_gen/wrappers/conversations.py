import copy
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import load_template, now_iso, stable_int, stable_uuid


def wrap_as_conversations_ticket(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    record = copy.deepcopy(load_template("conversations_tickets.json"))
    record["email_subject"] = signal.title
    # `messages` is a list of [author, content] pairs; collapse to one customer message
    # so the LLM body becomes the ticket content.
    record["messages"] = [["customer", signal.body]]
    record["id"] = stable_uuid(seed, idx, "conversations.id")
    record["ticket_number"] = (stable_int(seed, idx, "conversations.num", bits=20) % 9000) + 1000
    record["created_at"] = now_iso()
    return record
