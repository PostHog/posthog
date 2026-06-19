"""Contract types for engineering_analytics.

Framework-free frozen dataclasses that define the canonical data model this
product exposes — Author, RepoRef, PullRequest, WorkflowRun — plus the
``pr_lifecycle`` deep-tool return types. No Django imports.

Every surface — the named MCP tools, the DRF read endpoints, and the UI — returns
these typed contracts. The product runs its curated HogQL privately behind them;
nothing is registered as a global view. Where a caveat is load-bearing on a deep
tool it rides as a ``metric_quality`` field (``pr_lifecycle``); the aggregate
endpoints carry their caveats in honest field names (``open_to_merge_seconds``)
and serializer/tool docs.

These use ``pydantic.dataclasses.dataclass`` rather than the stdlib variant: same
``is_dataclass()`` compatibility (so ``DataclassSerializer`` keeps working) but
with runtime validation on construction, so a mapper that hands back the wrong
shape fails at the facade boundary instead of producing malformed JSON later.

Provider-specific shapes (GitHub column names, nesting) never reach here — the
read layer maps them into these types. Reviewers, deploys, and file paths are
intentionally absent until the warehouse data that backs them lands.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic.dataclasses import dataclass


class GitHubSourceNotConnectedError(Exception):
    """Raised when a team has no GitHub warehouse source — the curated queries
    reference ``github_*`` tables that aren't in the catalog. Surfaces as a clear
    4xx so the UI prompts to connect a source and an agent gets an actionable
    error instead of a misleading empty result. Framework-free; the presentation
    layer translates it to an HTTP response.
    """

    DEFAULT_MESSAGE = "Connect a GitHub data warehouse source to use engineering analytics."

    def __init__(self, message: str = DEFAULT_MESSAGE) -> None:
        super().__init__(message)


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
    """How much to trust a metric, surfaced on a deep-tool return so an
    autonomous caller can act on the result without paraphrasing a caveat.

    - ``precise``: computed directly from the data, no known approximation.
    - ``coarse``: a usable approximation with a known systematic gap (e.g. the
      read layer's ``open_to_merge_seconds`` combines draft and ready-for-review
      time).
    - ``partial``: real but incomplete, because backing data hasn't landed yet
      (e.g. ``pr_lifecycle`` has no review/comment events).
    """

    PRECISE = "precise"
    COARSE = "coarse"
    PARTIAL = "partial"


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
    # None until the run completes — the curated builder only computes a duration
    # for completed runs (see workflow_runs.build_query).
    duration_seconds: int | None


@dataclass(frozen=True)
class PRLifecycleEvent:
    kind: PRLifecycleEventKind
    at: datetime
    detail: str | None = None
    # GitHub Actions run id for ci_* events — links straight to the run page.
    run_id: int | None = None


@dataclass(frozen=True)
class PRLifecycle:
    pull_request: PullRequest
    events: list[PRLifecycleEvent]
    metric_quality: MetricQuality = MetricQuality.PARTIAL


@dataclass(frozen=True)
class CIStatusRollup:
    """A PR's CI, collapsed from the latest workflow run per workflow on its head
    SHA. Counts can lag until the ``workflow_run`` webhook settles a run that
    completes after newer runs land (SPEC §9) — treat ``pending`` as unsettled.
    """

    runs: int
    passing: int
    failing: int
    pending: int


@dataclass(frozen=True)
class PullRequestListItem:
    """One row of the PR list: the PR plus its head-SHA CI rollup. No ``id`` or
    ``head_sha`` — this is a display/triage row, not the full ``PullRequest``.
    """

    number: int
    title: str
    author: Author
    repo: RepoRef
    state: PRState
    is_draft: bool
    created_at: datetime
    merged_at: datetime | None
    # merged_at - created_at; coarse (fuses draft + ready-for-review time). None until merged.
    open_to_merge_seconds: int | None
    labels: list[str]
    ci: CIStatusRollup


@dataclass(frozen=True)
class PullRequestList:
    """A page of the PR list plus an explicit truncation signal. ``items`` is capped
    at ``limit`` (newest first); ``truncated`` is True when more pull requests match
    than the cap. Surfaced so a consumer never mistakes a capped page for the whole
    set — the aggregate counts in ``CICardSummary`` can legitimately exceed
    ``len(items)`` when ``truncated`` is True.
    """

    items: list[PullRequestListItem]
    truncated: bool
    limit: int


@dataclass(frozen=True)
class CICardSummary:
    """Headline counts for the open-PR backlog. ``failing_ci`` rests on the
    head-SHA CI join and can lag (see ``CIStatusRollup``).
    """

    open_prs: int
    repos: int
    # Open, non-draft, non-bot PRs older than 7 days.
    stuck: int
    # Open PRs with at least one failing latest CI run.
    failing_ci: int


@dataclass(frozen=True)
class WorkflowHealthDay:
    """One day of a workflow's run history; days without runs are zero-filled."""

    day: date
    run_count: int
    completed: int
    successes: int


@dataclass(frozen=True)
class WorkflowHealthItem:
    """Per-workflow CI health over a window. Rates and percentiles are over
    completed runs only, so they are ``None`` when the window has none.
    """

    repo: RepoRef
    workflow_name: str
    run_count: int
    success_rate: float | None
    p50_seconds: float | None
    p95_seconds: float | None
    last_failure_at: datetime | None
    # Daily run history across the whole window, oldest first, zero-filled.
    daily: list[WorkflowHealthDay]
