import dataclasses
from enum import StrEnum


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


@dataclasses.dataclass
class OrgBatchPageResult:
    batches: list[list[str]]
    cursor: str | None

    @property
    def org_count(self) -> int:
        return sum(len(batch) for batch in self.batches)

    @property
    def batch_count(self) -> int:
        return len(self.batches)


@dataclasses.dataclass
class OrgDigestNotificationCounts:
    sent: int = 0
    control: int = 0
    skipped_no_data: int = 0
    failed: int = 0
    team_count: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0
    skipped_reason: str | None = None


@dataclasses.dataclass
class DigestBatchInput:
    org_ids: list[str]
    dry_run: bool = False
    flag_key: str = "web-analytics-digest-notification"


@dataclasses.dataclass
class DigestBatchResult:
    batch_size: int = 0
    orgs_processed: int = 0
    orgs_skipped: int = 0
    orgs_failed: int = 0
    notifications_sent: int = 0
    control_exposed: int = 0
    skipped_no_data: int = 0
    failed: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0

    @property
    def total_duration(self) -> float:
        return self.build_duration + self.send_duration

    @property
    def failure_rate(self) -> float:
        attempted = self.orgs_processed + self.orgs_failed
        return self.orgs_failed / attempted if attempted > 0 else 0.0

    def __iadd__(self, other: "DigestBatchResult") -> "DigestBatchResult":
        for f in dataclasses.fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        return self


@dataclasses.dataclass
class SendTestDigestNotificationInput:
    email: str
    team_id: int | None = None


WA_DIGEST_NOTIF_THRESHOLD_EXCEEDED_TYPE = "WADigestNotificationThresholdExceeded"
