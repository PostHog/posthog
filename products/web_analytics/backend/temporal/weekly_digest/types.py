import dataclasses
from enum import StrEnum


class DigestOutcome(StrEnum):
    """Outcome of attempting to send a single digest email to a single user."""

    SENT = "sent"
    DRY_RUN = "dry_run"
    SKIPPED_OPTOUT = "skipped_optout"
    SKIPPED_NO_DATA = "skipped_no_data"
    FAILED = "failed"


@dataclasses.dataclass
class OrgDigestCounts:
    """`skipped_reason` is set when the org was skipped before any email attempt
    (no teams, no targeted members, etc.) — present means the org should be
    counted as skipped, not processed.
    """

    sent: int = 0
    skipped_optout: int = 0
    skipped_no_data: int = 0
    failed: int = 0
    team_count: int = 0
    build_duration: float = 0.0
    send_duration: float = 0.0
    skipped_reason: str | None = None


@dataclasses.dataclass
class WAWeeklyDigestInput:
    dry_run: bool = False
    batch_size: int = 25
    max_concurrent: int = 4
    failure_threshold: float = 0.2
    active_since_days: int | None = 30
    org_ids: list[str] | None = None


@dataclasses.dataclass
class OrgBatchPageInput:
    workflow_input: WAWeeklyDigestInput
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
class DigestBatchInput:
    org_ids: list[str]
    dry_run: bool = False


@dataclasses.dataclass
class DigestBatchResult:
    """`failure_rate` excludes `orgs_skipped`: digest skips are benign
    pre-processing exclusions (no targeted members, no teams, race-deleted
    org), not detector errors, so they shouldn't trip the workflow's threshold
    alarm.
    """

    batch_size: int = 0
    orgs_processed: int = 0
    orgs_skipped: int = 0
    orgs_failed: int = 0
    emails_sent: int = 0
    emails_skipped_optout: int = 0
    emails_skipped_no_data: int = 0
    emails_failed: int = 0
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
class SendTestDigestInput:
    """Input for the test activity.

    Two modes:
    - email only: send the user's full real digest (one email per org they're in)
    - email + team_id: preview that single team's digest as if the user were receiving it

    Bypasses notification settings and feature flags. Always enforces org membership
    and team access.
    """

    email: str
    team_id: int | None = None


WA_DIGEST_THRESHOLD_EXCEEDED_TYPE = "WADigestThresholdExceeded"
WA_DIGEST_EMAIL_UNAVAILABLE_TYPE = "WADigestEmailUnavailable"
