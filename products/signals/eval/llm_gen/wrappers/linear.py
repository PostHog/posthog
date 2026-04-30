import json
from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal
from products.signals.eval.llm_gen.wrappers.utils import stable_int, stable_uuid


def wrap_as_linear_issue(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    number = (stable_int(seed, idx, "linear.num", bits=20) % 9000) + 1000
    identifier = f"POS-{number}"
    issue_id = stable_uuid(seed, idx, "linear.id")
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    slug = signal.title.lower().replace(" ", "-")[:80]
    return {
        "id": issue_id,
        "identifier": identifier,
        "number": number,
        "title": signal.title,
        "description": signal.body,
        "priority": 2,
        "priority_label": "Normal",
        "url": f"https://linear.app/posthog/issue/{identifier}/{slug}",
        "created_at": now,
        "updated_at": now,
        "state": json.dumps({"id": stable_uuid(seed, idx, "linear.state"), "name": "Triage", "type": "triage"}),
        "team": json.dumps({"id": stable_uuid(seed, 0, "linear.team"), "key": "POS", "name": "PostHog"}),
        "labels": json.dumps({"nodes": []}),
    }
