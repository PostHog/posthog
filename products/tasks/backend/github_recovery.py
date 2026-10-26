from datetime import datetime
from typing import Literal

from posthog.dataclasses import frozen

GITHUB_BLOCKED_REASON = "github_blocked_reason"
GITHUB_RECOVERY_DEADLINE = "github_recovery_deadline"
GITHUB_RECOVERY_STATE_KEYS = (GITHUB_BLOCKED_REASON, GITHUB_RECOVERY_DEADLINE)
GITHUB_ACCESS_RESTORED_SIGNAL = "github_access_restored"


@frozen
class GitHubRecoveryCheck:
    status: Literal["ready", "retry", "suspended", "cancelled", "expired"]
    retry_until: datetime | None = None
