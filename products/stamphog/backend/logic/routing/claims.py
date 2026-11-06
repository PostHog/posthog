"""When a reviewer routing claim on `PullRequest.routing` counts as abandoned.

Kept apart from the routing service, so the facade can report a claim's age without importing the
GitHub, model and ownership clients that a routing run needs.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

# A claim older than this counts as abandoned, so a task that died does not block the pull request
# for good. It sits far above the time a task needs to finish, retries included.
CLAIM_STALE_AFTER = timedelta(hours=2)


def is_stale_claim(record: Mapping[str, Any]) -> bool:
    try:
        claimed_at = datetime.fromisoformat(str(record.get("claimed_at") or ""))
    except ValueError:
        return True
    return datetime.now(UTC) - claimed_at > CLAIM_STALE_AFTER
