import copy
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import load_template, now_iso, stable_int


def wrap_as_github_issue(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    record = copy.deepcopy(load_template("github_issues.json"))
    record["title"] = signal.title
    record["body"] = signal.body
    # Stub identity to make reruns deterministic and avoid colliding with real data.
    number = (stable_int(seed, idx, "github.num", bits=20) % 100000) + 900000
    record["id"] = str(stable_int(seed, idx, "github.id"))
    record["number"] = number
    record["html_url"] = f"https://github.com/PostHog/posthog/issues/{number}"
    now = now_iso()
    record["created_at"] = now
    record["updated_at"] = now
    return record
