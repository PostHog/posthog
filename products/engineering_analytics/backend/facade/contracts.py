"""Contract types for engineering_analytics.

Framework-free frozen dataclasses defining the canonical data model this product exposes (Author,
RepoRef, PullRequest, WorkflowRun) plus the ``pr_lifecycle`` deep-tool types. Every surface (MCP tools,
DRF endpoints, UI) returns these; the curated HogQL runs privately behind them. Deep-tool caveats ride
as a ``metric_quality`` field; aggregate endpoints carry theirs in honest field names.

Uses ``pydantic.dataclasses.dataclass`` (not stdlib) for runtime validation on construction, so a
mapper handing back the wrong shape fails at the facade boundary instead of emitting malformed JSON.
Provider-specific shapes never reach here — the read layer maps them in.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic.dataclasses import dataclass


class GitHubSourceNotConnectedError(Exception):
    """Raised when a team has no GitHub warehouse source. Surfaces as a 4xx so the UI prompts to
    connect a source rather than returning a misleading empty result. Framework-free; the presentation
    layer maps it to an HTTP response.
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
    """How much to trust a metric, surfaced on a deep-tool return so an autonomous caller can act
    without paraphrasing a caveat.

    - ``precise``: computed directly, no known approximation.
    - ``coarse``: usable approximation with a known systematic gap (e.g. ``open_to_merge_seconds``
      fuses draft and ready-for-review time).
    - ``partial``: real but incomplete because backing data hasn't landed (e.g. ``pr_lifecycle`` has
      no review/comment events).
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


class QuarantineMode(StrEnum):
    # "run": the test still executes but cannot fail the suite. "skip": not run at all.
    RUN = "run"
    SKIP = "skip"


class QuarantineLifecycle(StrEnum):
    """Where an entry sits relative to its expiry: ``active`` (more than 7 days
    left), ``expiring_soon`` (7 days or fewer left), ``in_grace`` (expired up to
    7 days ago — inert, but its removal is not yet mandatory), ``overdue``
    (expired beyond the 7-day grace period).
    """

    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    IN_GRACE = "in_grace"
    OVERDUE = "overdue"


class QuarantineSelectorKind(StrEnum):
    PRODUCT = "product"
    FILE = "file"
    DIRECTORY = "directory"
    TEST = "test"


@dataclass(frozen=True)
class GitHubSource:
    """A connected GitHub warehouse source. ``id`` is passed back as ``source_id`` to select it;
    ``repo`` and ``prefix`` are display labels so a picker can tell two sources apart.
    """

    id: str
    # Connected repository as 'owner/name' (from the source's job inputs), or '' if unknown.
    repo: str
    # User-chosen warehouse table-name prefix for this source, or '' when none was set.
    prefix: str


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
    # None while a run is still in progress.
    conclusion: WorkflowConclusion | None
    run_started_at: datetime
    updated_at: datetime
    # None until the run completes (duration is only computed for completed runs).
    duration_seconds: int | None


@dataclass(frozen=True)
class WorkflowRunDetail:
    """A single workflow run, for the run detail page. Run-level only — per-job/step data isn't in
    the warehouse yet (see WORKFLOW_JOBS_COLUMNS). ``pr_number`` is 0 when the run isn't attributed
    to a pull request (fork PR, or a push with no open PR); multi-PR runs credit the first only.
    """

    repo: RepoRef
    id: int
    workflow_name: str
    head_sha: str
    head_branch: str
    # Raw run status: 'queued', 'in_progress', 'completed', ... (passthrough).
    status: str
    # Raw conclusion passthrough ('success' / 'failure' / 'timed_out' / ...), or None while in progress.
    # A str not WorkflowConclusion because the data carries conclusions outside that enum.
    conclusion: str | None
    # None for a queued/barely-started run whose timestamp hasn't landed; the OrNull parse maps a sparse
    # row to None rather than failing.
    run_started_at: datetime | None
    updated_at: datetime | None
    # None until the run completes — duration is only computed for completed runs.
    duration_seconds: int | None
    # Re-run attempt number; 1 for the first attempt.
    run_attempt: int
    # Attributed pull request number, or 0 when unattributed.
    pr_number: int


@dataclass(frozen=True)
class WorkflowJob:
    """One job within a workflow run, for the run's expandable job breakdown. ``estimated_cost_usd``
    is derived from the runner tier (parsed from ``runner_label``) and the job's elapsed time via the
    cost model; None when the tier is unknown or the job hasn't finished.
    """

    id: int
    run_id: int
    name: str
    # Raw status / conclusion passthrough; conclusion is None while the job is still in progress.
    status: str
    conclusion: str | None
    # None while queued / running, respectively.
    started_at: datetime | None
    completed_at: datetime | None
    duration_seconds: int | None
    # Where the job ran: 'github_hosted' (free for open source), 'self_hosted' (billable), or 'unknown'.
    # Provider-neutral so other CI providers can slot in.
    runner_provider: str
    # The job's runner tier label, e.g. '16-core' (self-hosted) or 'ubuntu-latest' (GitHub-hosted).
    runner_label: str
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class WorkflowRunnerCost:
    """One runner tier's share of a workflow's CI spend — for the single-workflow "where the spend
    goes" breakdown. ``provider`` is 'self_hosted' (billable) / 'github_hosted' (free) / 'unknown';
    ``runner_label`` is the tier (e.g. '16-core', 'ubuntu-latest'). estimated_cost_usd is None for
    non-billable tiers (github-hosted / non-Linux), which still show their minutes + job count.
    """

    provider: str
    runner_label: str
    job_count: int
    billable_minutes: float
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class WorkflowCost:
    """One workflow's billable CI spend within a scope (a PR, or a window) — same shape as the per-PR
    rollup but keyed by ``workflow_name``, for the per-workflow cost column. Billable runners only.
    """

    workflow_name: str
    billable_minutes: float
    estimated_cost_usd: float | None
    costed_jobs: int
    unsettled_jobs: int
    excluded_jobs: int


@dataclass(frozen=True)
class RunCost:
    """One workflow run's billable CI spend within a PR — the per-run cost shown when a PR's workflow
    row is expanded to its runs. Keyed by ``(run_id, run_attempt)`` so a re-run's attempts stay
    distinct. Billable runners only; same exclusion rules as ``PRCostSummary``.
    """

    run_id: int
    run_attempt: int
    billable_minutes: float
    estimated_cost_usd: float | None


@dataclass(frozen=True)
class PRCostSummary:
    """Estimated CI spend for one PR, summed over the jobs of all its workflow runs.

    Billable runners only: provider-hosted (free GitHub-hosted) and non-Linux tiers carry no honest
    figure and land in ``excluded_jobs`` rather than mis-costed. ``jobs_available`` is False when the
    optional job-level source isn't synced (every figure then zero/None, UI hides the cost cards).
    ``estimated_cost_usd`` is None when nothing was costable, so a PR with only unsettled jobs reads as
    "no figure yet", not ``$0.00``.
    """

    jobs_available: bool
    # Wall-clock minutes consumed on billable (self-hosted) runners (sum of elapsed across costed jobs).
    billable_minutes: float
    # Estimated dollar cost (sum of per-job estimates), or None when no job was costable.
    estimated_cost_usd: float | None
    # Costed jobs (billable Linux runner, finished).
    costed_jobs: int
    # Billable Linux jobs still queued/running (no elapsed) — excluded from cost, surfaced as "unsettled".
    unsettled_jobs: int
    # Jobs on provider-hosted (GitHub-hosted, free) or non-Linux runners — outside the estimate.
    excluded_jobs: int
    # Same spend broken down per workflow, so the PR's per-workflow table can show a cost column.
    by_workflow: list[WorkflowCost]
    # Same spend broken down per workflow run, keyed by (run_id, run_attempt), so the expanded runs
    # table under a workflow can show a per-run cost column (rolling up to the per-workflow figure).
    by_run: list[RunCost]


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
    """A PR's CI, collapsed from the latest run per workflow on its head SHA. Counts can lag until the
    ``workflow_run`` webhook settles a late-completing run (SPEC §9) — treat ``pending`` as unsettled.
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
    # CI triggers attributed to this PR: distinct head SHAs across its workflow runs (a run
    # carries the PR it ran for in ``pull_requests``). Fork-PR runs are unattributed.
    pushes: int
    # Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run).
    rerun_cycles: int
    # Estimated CI cost in USD summed over this PR's jobs (billable runners only); None when nothing
    # was costable or the job-level source (``github_workflow_jobs``) isn't synced. See logic/cost.py.
    estimated_cost_usd: float | None = None
    # Billable (self-hosted) minutes summed over this PR's jobs; None when the job source isn't synced.
    billable_minutes: float | None = None


@dataclass(frozen=True)
class PullRequestList:
    """A page of the PR list plus a truncation signal. ``items`` is capped at ``limit`` (newest first);
    ``truncated`` is True when more match than the cap, so a consumer never mistakes a capped page for
    the whole set — ``CICardSummary`` counts can legitimately exceed ``len(items)``.
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
class WorkflowHealthBucket:
    """One time bucket of a workflow's run history; empty buckets are zero-filled. Bucket width
    (hour / day / week) is set per item in ``WorkflowHealthItem.granularity``. ``failures`` is decisive
    failures only (failure / timed_out) — skipped/cancelled/action_required are neither pass nor fail.
    """

    # Bucket start, aligned to the granularity (top of hour / midnight / Monday).
    bucket_start: datetime
    run_count: int
    completed: int
    successes: int
    failures: int


@dataclass(frozen=True)
class QuarantineEntry:
    """One selector from a repo's checked-in ``.test_quarantine.json``, enriched
    with read-side expiry classification."""

    id: str
    runner: str
    reason: str
    owner: str
    issue: str
    added: date
    expires: date
    mode: QuarantineMode
    lifecycle: QuarantineLifecycle
    # Negative once past expiry.
    days_until_expiry: int
    selector_kind: QuarantineSelectorKind


@dataclass(frozen=True)
class QuarantineFile:
    """A repo's parsed quarantine file. ``available`` is False when no file
    exists — that is not an error. Parsing is fail-open to match the enforcement
    readers: malformed entries land in ``parse_errors`` while well-formed ones
    are kept, and unknown entry fields only warn.
    """

    available: bool
    # Most urgent first (overdue, in_grace, expiring_soon, active), then by expiry.
    entries: list[QuarantineEntry]
    parse_errors: list[str]
    parse_warnings: list[str]
    # None in local-dev mode, where the server's own checkout is read.
    repo: RepoRef | None
    source_url: str
    generated_at: datetime


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
    # Whether the most recent completed run was a decisive failure (failure / timed_out); None when
    # nothing completed. Drives the OK/RED badge. A bool not the raw conclusion because the data carries
    # conclusions outside WorkflowConclusion (e.g. action_required) that would fail validation.
    latest_run_failed: bool | None
    # Raw conclusion of that run ('success' / 'cancelled' / 'skipped' / ...), so the UI can tell a real
    # pass from a cancelled/skipped run (both have latest_run_failed false). None when nothing completed.
    latest_run_conclusion: str | None
    # Bucket width of the history series, chosen to fit the window: 'hour', 'day', or 'week'.
    granularity: str
    # Run history across the whole window, oldest first, zero-filled, bucketed by `granularity`.
    buckets: list[WorkflowHealthBucket]
    # Billable (self-hosted) minutes + estimated cost over this workflow's jobs in the window; None when
    # the job-level source isn't synced (run-level health alone carries no runner tier).
    billable_minutes: float | None = None
    estimated_cost_usd: float | None = None
