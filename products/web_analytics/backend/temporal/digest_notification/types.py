import dataclasses
from enum import StrEnum

from posthog.temporal.common.digest import DigestBatchTotals


class NotificationDigestOutcome(StrEnum):
    SENT = "sent"
    CONTROL = "control"
    DRY_RUN = "dry_run"
    SKIPPED_NO_DATA = "skipped_no_data"
    FAILED = "failed"


@dataclasses.dataclass
class WADigestNotificationInput:
    dry_run: bool = False
    batch_size: int = 25
    max_concurrent: int = 4
    failure_threshold: float = 0.2
    flag_key: str = "web-analytics-digest-notification"
    org_ids: list[str] | None = None


@dataclasses.dataclass
class OrgBatchPageInput:
    workflow_input: WADigestNotificationInput
    cursor: str | None = None
    page_size: int = 5000


@dataclasses.dataclass(frozen=False)
class OrgDigestNotificationCounts:
    sent: int = 0
    control: int = 0
    skipped_no_data: int = 0
    failed: int = 0
    team_count: int = 0
    teams_failed: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0
    skipped_reason: str | None = None


@dataclasses.dataclass
class DigestBatchInput:
    org_ids: list[str]
    dry_run: bool = False
    flag_key: str = "web-analytics-digest-notification"


@dataclasses.dataclass(frozen=False)
class DigestBatchResult(DigestBatchTotals):
    notifications_sent: int = 0
    control_exposed: int = 0
    skipped_no_data: int = 0
    failed: int = 0


@dataclasses.dataclass
class SendTestDigestNotificationInput:
    email: str
    team_id: int | None = None


WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE = "WADigestNotificationThresholdExceeded"
