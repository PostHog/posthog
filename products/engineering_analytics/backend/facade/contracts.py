"""Contract types for engineering_analytics.

Framework-free frozen dataclasses that define the canonical data model this
product exposes — Author, RepoRef, PullRequest, WorkflowRun — plus the
tool-specific return types (WorkflowReport, TimeToMerge, PRLifecycle). No Django
imports. See SPEC.md section 4.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant: same
``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps working) but
with runtime validation on construction, so a mapper that hands back the wrong
shape fails at the facade boundary instead of producing malformed JSON later.

Provider-specific shapes (GitHub column names, nesting) never reach here — the
query layer maps them into these types. Reviewers, deploys, and file paths are
intentionally absent until the warehouse data that backs them lands (SPEC.md
sections 4 and 8).
"""

from datetime import datetime
from enum import StrEnum

from pydantic.dataclasses import dataclass


class PRState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class WorkflowConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    NEUTRAL = "neutral"


class MetricQuality(StrEnum):
    """How much to trust a metric, surfaced on every tool return so an
    autonomous caller can act on the result without paraphrasing a caveat.

    - ``precise``: computed directly from the data, no known approximation.
    - ``coarse``: a usable approximation with a known systematic gap (e.g.
      ``time_to_merge`` combines draft and ready-for-review time).
    - ``partial``: real but incomplete, because backing data hasn't landed yet
      (e.g. ``pr_lifecycle`` has no review/comment events).
    """

    PRECISE = "precise"
    COARSE = "coarse"
    PARTIAL = "partial"


class BucketKind(StrEnum):
    ALL = "all"
    AUTHOR = "author"


class PRLifecycleEventKind(StrEnum):
    OPENED = "opened"
    CI_STARTED = "ci_started"
    CI_FINISHED = "ci_finished"
    MERGED = "merged"
    CLOSED = "closed"


@dataclass(frozen=True)
class RepoRef:
    provider: str
    owner: str
    name: str


@dataclass(frozen=True)
class Author:
    handle: str
    display_name: str
    avatar_url: str
    is_bot: bool


@dataclass(frozen=True)
class PullRequest:
    id: int
    number: int
    title: str
    author: Author
    repo: RepoRef
    state: PRState
    is_draft: bool
    created_at: datetime
    merged_at: datetime | None
    closed_at: datetime | None


@dataclass(frozen=True)
class WorkflowRun:
    id: int
    workflow_name: str
    head_sha: str
    # None while a run is still in progress — it has no conclusion yet.
    conclusion: WorkflowConclusion | None
    run_started_at: datetime
    updated_at: datetime
    duration_seconds: int


@dataclass(frozen=True)
class WorkflowReportRow:
    workflow_name: str
    total_runs: int
    success_rate: float
    median_duration_seconds: float
    p95_duration_seconds: float
    last_failed_at: datetime | None


@dataclass(frozen=True)
class WorkflowReport:
    rows: list[WorkflowReportRow]
    date_from: str
    date_to: str | None
    repo: RepoRef | None
    metric_quality: MetricQuality = MetricQuality.PRECISE


@dataclass(frozen=True)
class TimeToMergeRow:
    bucket: str
    bucket_kind: BucketKind
    pr_count: int
    median_seconds: float
    p95_seconds: float


@dataclass(frozen=True)
class TimeToMerge:
    rows: list[TimeToMergeRow]
    date_from: str
    date_to: str | None
    repo: RepoRef | None
    group_by_author: bool
    metric_quality: MetricQuality = MetricQuality.COARSE


@dataclass(frozen=True)
class PRLifecycleEvent:
    kind: PRLifecycleEventKind
    at: datetime
    detail: str | None = None


@dataclass(frozen=True)
class PRLifecycle:
    pull_request: PullRequest
    events: list[PRLifecycleEvent]
    metric_quality: MetricQuality = MetricQuality.PARTIAL
