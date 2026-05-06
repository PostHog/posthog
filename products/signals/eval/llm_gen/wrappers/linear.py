import copy
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import load_template, now_iso, stable_int, stable_uuid


def wrap_as_linear_issue(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    record = copy.deepcopy(load_template("linear_issues.json"))
    record["title"] = signal.title
    record["description"] = signal.body
    number = (stable_int(seed, idx, "linear.num", bits=20) % 9000) + 1000
    identifier = f"POS-{number}"
    slug = signal.title.lower().replace(" ", "-")[:80]
    record["id"] = stable_uuid(seed, idx, "linear.id")
    record["number"] = number
    record["identifier"] = identifier
    record["url"] = f"https://linear.app/posthog/issue/{identifier}/{slug}"
    now = now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    return record
