import json
import hashlib
from datetime import UTC, datetime
from typing import Any

from products.signals.eval.llm_gen.client import CanonicalSignal


def _stable_int(seed: int, idx: int, salt: str, *, bits: int = 48) -> int:
    h = hashlib.sha256(f"{salt}:{seed}:{idx}".encode()).hexdigest()
    return int(h[: bits // 4], 16)


def wrap_as_github_issue(signal: CanonicalSignal, idx: int, seed: int) -> dict[str, Any]:
    issue_id = _stable_int(seed, idx, "github.id")
    issue_number = (_stable_int(seed, idx, "github.num", bits=20) % 100000) + 900000
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "id": str(issue_id),
        "title": signal.title,
        "body": signal.body,
        "html_url": f"https://github.com/PostHog/posthog/issues/{issue_number}",
        "number": issue_number,
        "labels": json.dumps(
            [
                {
                    "color": "a2eeef",
                    "default": True,
                    "description": "New feature or request",
                    "id": _stable_int(seed, idx, "github.label"),
                    "name": "enhancement",
                    "node_id": "MDU6TGFiZWwxODA1NjA5ODgz",
                    "url": "https://api.github.com/repos/PostHog/posthog/labels/enhancement",
                }
            ]
        ),
        "created_at": now,
        "updated_at": now,
        "locked": False,
        "state": "open",
    }
