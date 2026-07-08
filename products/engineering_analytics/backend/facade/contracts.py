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

from dataclasses import field
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


class QuarantineWriteError(Exception):
    """A quarantine write could not be completed — no GitHub App installed on the
    target repo, the App lives on a different org, a malformed quarantine file, or a
    failed GitHub call. Carries a message safe to show the user verbatim. Framework-free;
    the presentation layer maps it to a 400 so the UI explains what to fix.
    """

    def __init__(self, message: str) -> None:
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


class WorkflowHealthRunScope(StrEnum):
    ALL = "all"
    PULL_REQUEST = "pull_request"


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


class QuarantineRequestAction(StrEnum):
    """What a write to the quarantine file does. ``quarantine`` adds (or replaces) an
    entry and files a fresh tracking issue; ``extend`` re-stamps an existing entry's
    expiry, reusing its issue; ``remove`` deletes the entry. All three open a PR.
    """

    QUARANTINE = "quarantine"
    EXTEND = "extend"
    REMOVE = "remove"


@dataclass(frozen=True)
class GitHubSource:
    """A connected GitHub warehouse source the team can analyze. ``id`` is what a
    caller passes back as ``source_id`` to select this source; ``repo`` and
    ``prefix`` are display labels so a picker can tell two sources apart.
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
    # None while a run is still in progress — it has no conclusion yet.
    conclusion: WorkflowConclusion | None
    run_started_at: datetime
    updated_at: datetime
    # None until the run completes — the curated builder only computes a duration
    # for completed runs (see workflow_runs.build_query).
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
    # Raw conclusion passthrough ('success' / 'failure' / 'timed_out' / 'cancelled' / 'skipped' /
    # 'action_required' / ...), or None while still in progress. Kept as a str (not WorkflowConclusion)
    # because the data carries conclusions outside that enum.
    conclusion: str | None
    # None for a queued/barely-started run whose timestamp the warehouse hasn't landed yet — the curated
    # builder parses these with the OrNull variant, so a sparse row maps to None rather than failing.
    run_started_at: datetime | None
    updated_at: datetime | None
    # None until the run completes — duration is only computed for completed runs.
    duration_seconds: int | None
    # Re-run attempt number; 1 for the first attempt.
    run_attempt: int
    # Attributed pull request number, or 0 when unattributed.
    pr_number: int


@dataclass(frozen=True)
class WorkflowRunActivityPoint:
    """A single workflow run reduced to the fields the run-activity chart plots: start time, duration,
    conclusion, branch, and attributed PR. Deliberately leaner than ``WorkflowRunDetail`` so the chart can
    load far more runs across the full window (for the scatter, the in-flight band, and the focus-lens
    brush) than the capped run-detail table, without the per-row wire cost of the full detail shape.
    """

    run_id: int
    # Raw conclusion passthrough ('success' / 'failure' / 'timed_out' / ...), or None while still running.
    conclusion: str | None
    # Always set here (unlike the shared WorkflowRunDetail shape): the windowed query filters on
    # run_started_at, so a run with no parseable start timestamp is excluded — it can't be placed on the
    # chart's time axis anyway. Non-null keeps the contract honest for this chart-only endpoint.
    run_started_at: datetime
    # None until the run completes — duration is only computed for completed runs.
    duration_seconds: int | None
    head_branch: str
    # Attributed pull request number, or 0 when unattributed.
    pr_number: int
    # Head commit SHA — lets a chart point link to the commit (e.g. the repo-health bar → GitHub commit).
    head_sha: str


@dataclass(frozen=True)
class WorkflowRunActivity:
    """The run-activity chart's data for one workflow over a window: compact per-run points plus an
    explicit truncation signal. ``points`` is capped at ``limit`` (newest first); ``truncated`` is True
    when more runs matched than the cap, so the chart can label itself as covering only the most recent
    runs rather than the full window. Higher-capped than the run-detail table, so the chart still spans
    multiple days on busy workflows where the smaller table cap would collapse to a sliver.
    """

    points: list[WorkflowRunActivityPoint]
    truncated: bool
    limit: int


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

    Billable runners only: provider-hosted runners (free GitHub-hosted minutes) and non-Linux tiers
    carry no honest figure and are counted in ``excluded_jobs`` rather than mis-costed. The dollar
    figure comes from the (currently Depot-shaped) cost model in ``logic.cost``; the contract stays
    provider-neutral so other CI providers can slot in. ``jobs_available`` is False when the optional
    job-level source (``github_workflow_jobs``) isn't synced — every figure is then zero/None and the
    UI hides the cost cards. ``estimated_cost_usd`` is None when nothing was costable, so a PR with
    only unsettled jobs reads as "no figure yet", not ``$0.00``.
    """

    jobs_available: bool
    # Billable CI minutes: each costed (self-hosted) job's elapsed time, summed. Parallel jobs add up, so
    # this is compute time spent, not wall-clock run duration.
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
class CIFailureLogLine:
    """One line of a job's failure log. ``original_line`` is the line's 1-based position in the full
    pre-thinning log, or None for a ``... N lines omitted ...`` marker between kept blocks — the gap
    between consecutive ``original_line`` values is how many lines were elided. The number is the only
    durable anchor back to the original, which isn't stored and which GitHub expires.
    """

    original_line: int | None
    text: str


@dataclass(frozen=True)
class CIJobFailureLog:
    """One failed CI job's thinned failure log, as ordered lines. The worker fetches logs for failed
    jobs only, so every job here is a failure. ``lines`` is the thinned failure region (errors plus
    surrounding context, with omission markers) in order; capped per job, with ``truncated`` set when
    the job had more.
    """

    job_id: int
    run_id: int
    # Raw job conclusion passthrough ('failure' / 'timed_out' / ...).
    conclusion: str
    # Git branch the run was triggered on, or '' when unknown.
    branch: str
    # Total lines in the full job log before thinning — the denominator for each line's original_line;
    # 0 when unknown (a record emitted before orig_total stamping).
    original_total_lines: int
    line_count: int
    lines: list[CIFailureLogLine]
    truncated: bool


@dataclass(frozen=True)
class CIFailureLogs:
    """Thinned CI failure logs for one pull request, grouped by failed job.

    Attribution follows the locked rule (SPEC §7): the PR is resolved to its workflow runs via the
    ``pull_requests`` association (all pushes, never a head-SHA join that would drop earlier ones),
    then logs are joined by ``run_id``. ``runs_attributed`` is how many runs the PR resolved to;
    ``logs_available`` is False when no failure-log records were found for those runs — CI hasn't
    failed, the logs aged out of the short Logs retention, or (fork PRs) the runs carry no PR
    association to resolve.
    """

    pr_number: int
    repo: RepoRef
    runs_attributed: int
    logs_available: bool
    jobs: list[CIJobFailureLog]
    # True when the overall line cap across all jobs was hit.
    truncated: bool


# The one caveat that governs every flaky figure — defined once here (the canonical-types home)
# so the API/MCP description and any other consumer-facing copy read from it instead of drifting.
FLAKY_TEST_SIGNAL_CAVEAT = (
    "All figures are absolute counts, never rates: fast passing runs are not emitted, so denominators "
    "are biased. Pass-on-retry counts only flow from CI lanes running with reruns enabled; in other "
    "lanes a flake surfaces as a plain failure, which the distinct-PR count catches."
)


@dataclass(frozen=True)
class FlakyTestItem:
    """One flaky-test leaderboard row, aggregated from the per-test CI spans in the Traces store.

    See ``FLAKY_TEST_SIGNAL_CAVEAT`` for why these are absolute counts and how the two signals
    (pass-on-retry vs distinct-PR failures) divide the rerun-enabled and no-rerun lanes.
    """

    # Reconstructed pytest nodeid (the span name), e.g. 'posthog/api/test/test_x/TestX::test_y'.
    nodeid: str
    # Runnable pytest selector ('posthog/api/test/test_x.py::TestX::test_y'). Exact when the CI
    # reporter stamped it; reconstructed from the nodeid (file/class boundary guessed) for older spans.
    selector: str
    # Spans where the test failed first, then passed on an automatic retry.
    rerun_passed_count: int
    # Spans with outcome 'failed' or 'error' (the final outcome after any retries).
    failed_count: int
    # Distinct PRs among the failed/error spans; master/branch failures carry no PR and don't count.
    failed_pr_count: int
    # Distinct git branches across all of the test's signal spans in the window.
    branch_count: int
    # Spans where the test failed while quarantined (xfail) — already masked, still flaky.
    xfailed_count: int
    # Most recent signal span for this test in the window.
    last_seen_at: datetime


@dataclass(frozen=True)
class FlakyTestList:
    """The flaky-test leaderboard for a window: qualifying tests ranked by flakiness signal,
    capped at ``limit`` with an explicit truncation flag (same shape as ``PullRequestList``).
    A test qualifies when it passed on retry at least ``min_rerun_passes`` times OR failed on
    at least ``min_failed_prs`` distinct PRs in the window.
    """

    items: list[FlakyTestItem]
    truncated: bool
    limit: int


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
    # The workflow names behind `failing`, sorted — what the UI names under the CI tag.
    failing_workflows: list[str] = field(default_factory=list)


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
class WorkflowHealthBucket:
    """One time bucket of a workflow's run history; empty buckets are zero-filled. The
    bucket width (hour / day / week) is set per item in ``WorkflowHealthItem.granularity``
    to fit the window. ``failures`` is decisive failures only (failure / timed_out),
    matching the CI rollup — skipped, cancelled, and action_required runs are neither
    successes nor failures, so they must not be treated as non-passing.
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
class QuarantineRequest:
    """A request to mutate a repo's ``.test_quarantine.json`` via a PR. ``selector`` is
    required for every action. ``reason``/``owner``/``expires``/``mode`` drive
    ``quarantine`` and ``extend`` and are ignored by ``remove``; ``issue`` carries the
    existing tracking issue forward on ``extend`` (``quarantine`` files a new one and
    overrides it). ``repo`` is an optional ``owner/name`` override; it defaults to the
    team's most active repo, matching the read endpoint.
    """

    # Named 'operation', not 'action': a bare 'action' enum field collides with other
    # serializers' 'action' enums in the OpenAPI spec and churns their generated types.
    operation: QuarantineRequestAction
    selector: str
    repo: str | None = None
    reason: str = ""
    owner: str = ""
    issue: str = ""
    expires: date | None = None
    mode: QuarantineMode = QuarantineMode.RUN


@dataclass(frozen=True)
class QuarantineRequestResult:
    """Outcome of a quarantine write: the opened PR, the tracking issue (empty for
    ``extend``/``remove``), and the branch the PR was opened from.
    """

    pr_url: str
    issue_url: str
    branch: str


@dataclass(frozen=True)
class WorkflowHealthItem:
    """Per-workflow CI health over a window. ``success_rate`` is over completed runs;
    ``p50_seconds``/``p95_seconds`` are over successful runs only (cancelled, skipped,
    and failed runs end early and would bias a duration percentile low). Each is
    ``None`` when the window has no qualifying runs.
    """

    repo: RepoRef
    workflow_name: str
    run_count: int
    success_rate: float | None
    p50_seconds: float | None
    p95_seconds: float | None
    last_failure_at: datetime | None
    # Whether the most recent completed run was a decisive failure (failure / timed_out).
    # None when nothing has completed in the window. Drives the OK/RED status badge — a
    # bool, not the raw conclusion, because the data carries conclusions outside
    # WorkflowConclusion (e.g. action_required) that would fail validation here.
    latest_run_failed: bool | None
    # Raw conclusion of that most recent completed run ('success' / 'cancelled' / 'skipped' / ...), so the
    # UI can tell a real pass from a cancelled/skipped run (both have latest_run_failed false). None when
    # nothing has completed. A str, not WorkflowConclusion, because the data carries values outside the enum.
    latest_run_conclusion: str | None
    # Bucket width of the history series, chosen to fit the window: 'hour', 'day', or 'week'.
    granularity: str
    # Run history across the whole window, oldest first, zero-filled, bucketed by `granularity`.
    buckets: list[WorkflowHealthBucket]
    # Billable (self-hosted) minutes + estimated cost over this workflow's jobs in the window; None when
    # the job-level source isn't synced (run-level health alone carries no runner tier).
    billable_minutes: float | None = None
    estimated_cost_usd: float | None = None
    # Runs in the window that were a 2nd+ attempt.
    rerun_cycles: int = 0
    # Success rate over the equal-length window before date_from; None when it had no completed runs.
    success_rate_prev: float | None = None


@dataclass(frozen=True)
class CostPerMergeBucket:
    """One time bucket of the repo's CI cost normalized by merged PRs — the "is CI spend per shipped
    change trending up" series. ``cost_per_merge_usd`` is the headline: estimated Depot cost over a
    trailing window ending at this bucket (24 h / 7 d / 4 w to match the grain) divided by PRs merged
    in the same trailing window. The rolling ratio exists because a strict per-bucket division has a
    hole in every bucket that shipped nothing and pairs spend with merges that usually happened a
    bucket later. Cost counts by run start and merges by merge time — the same coarse alignment the
    daily depot tooling uses. ``estimated_cost_usd`` and ``merges`` stay bucket-local (the raw inputs);
    empty buckets are zero-filled: ``merges`` 0, cost None.
    """

    # Bucket start, aligned to the granularity (top of hour / midnight / Monday).
    bucket_start: datetime
    # Estimated Depot CI cost (USD) of all runs started in this bucket. None when nothing was costable
    # (no billable self-hosted Linux jobs, or the job source isn't synced).
    estimated_cost_usd: float | None
    # PRs merged in this bucket (all authors, bots included — matches the cost numerator's population).
    merges: int
    # Trailing-window cost / trailing-window merges (window sized to the grain). None when the trailing
    # window had no merges or no costable cost, so a dead stretch is never shown as an infinite or zero
    # cost-per-merge.
    cost_per_merge_usd: float | None


@dataclass(frozen=True)
class TimeToGreenBucket:
    """One time bucket of the repo's median time-to-green: the p50 wall-clock duration of *successful*
    CI runs attributed to pull requests (default-branch runs excluded), started in this bucket. Cancelled
    and failed runs end early and would bias the percentile low, so they are excluded — the same
    success-only population the workflow-health percentiles use. ``p50_seconds`` is None for a bucket with
    no successful PR run (a gap, not instant CI); the UI carries the last known value forward rather than
    dipping the trend to zero.
    """

    # Bucket start, aligned to the granularity (top of hour / midnight / Monday).
    bucket_start: datetime
    # Median wall-clock seconds of successful PR-attributed CI runs started in this bucket. None when the
    # bucket had no successful PR run.
    p50_seconds: float | None


@dataclass(frozen=True)
class RepoOverview:
    """Repo-level headline aggregates for the landing page, each with its previous-window twin
    so the UI renders honest deltas. The previous window has the same length as the current one
    and ends where it starts. Cost figures are None when the job-level source isn't synced
    (``jobs_available``); the PR merge median excludes bots and drafts per the locked recipe.
    """

    run_count: int
    run_count_prev: int
    success_rate: float | None
    success_rate_prev: float | None
    rerun_cycles: int
    rerun_cycles_prev: int
    # Coarse by design: merged_at - created_at (draft + ready time fused), median over PRs merged in the window.
    median_open_to_merge_seconds: float | None
    median_open_to_merge_seconds_prev: float | None
    billable_minutes: float | None
    billable_minutes_prev: float | None
    estimated_cost_usd: float | None
    estimated_cost_usd_prev: float | None
    jobs_available: bool
    # 'master' or 'main', picked by observed run volume in the current window.
    default_branch: str
    # Cost-per-merged-PR trend across the window, oldest first, zero-filled, bucketed by
    # `cost_series_granularity`. Empty when the job-level source isn't synced.
    cost_series: list[CostPerMergeBucket]
    # Bucket width of `cost_series`, chosen to fit the window: 'hour', 'day', or 'week'.
    cost_series_granularity: str
    # Time-to-green trend: median CI duration of successful PR-attributed runs per bucket, oldest first,
    # bucketed by `time_to_green_series_granularity`. Empty buckets carry None (no successful PR run).
    time_to_green_series: list[TimeToGreenBucket]
    # Bucket width of `time_to_green_series`, chosen to fit the window: 'hour', 'day', or 'week'.
    time_to_green_series_granularity: str


@dataclass(frozen=True)
class MasterFailureGroup:
    """One group of default-branch failures: a (workflow, de-sharded failing job) signature with
    its run count and first/last seen — the error-tracking-style triage row. ``failed_job`` is ''
    when the job-level source isn't synced and the group degrades to workflow level.
    """

    repo: RepoRef
    workflow_name: str
    failed_job: str
    run_count: int
    first_seen: datetime
    last_seen: datetime
    # The most recent failing run in the group — the drill-down anchor.
    latest_run_id: int


@dataclass(frozen=True)
class RunFailureLogs:
    """Thinned CI failure logs for a single workflow run, grouped by failed job. Same log substrate
    as ``CIFailureLogs`` but keyed directly by run id, for surfaces that aren't PR-scoped (the
    default-branch failures feed and the run page). ``logs_available`` is False when no failure-log
    records exist for the run — it didn't fail, or the logs aged out of the short Logs retention.
    """

    run_id: int
    logs_available: bool
    jobs: list[CIJobFailureLog]
    truncated: bool


@dataclass(frozen=True)
class WorkflowJobAggregate:
    """Per-job aggregates for one workflow over a window, one row per de-sharded job name
    (matrix ``(G/N)`` suffix stripped; unexpanded ``${{ matrix.* }}`` templates collapsed).
    ``failure_rate`` is over completed jobs; ``p50_seconds``/``p95_seconds`` are over
    successful jobs only (cancelled and failed instances end early and would bias a
    duration percentile low); cost is None when every instance ran on an unknown tier."""

    job_name: str
    # Job instances observed in the window (all shards, all attempts).
    job_count: int
    # Distinct raw job names inside the group — the observed matrix width.
    shard_count: int
    # Distinct workflow runs the job appeared in.
    runs_in: int
    # runs_in / the workflow's total runs in the window — below 1.0 means the job is conditional.
    run_share: float | None
    queue_p50_seconds: float | None
    p50_seconds: float | None
    p95_seconds: float | None
    failure_rate: float | None
    # Job instances that ran on a 2nd+ run attempt.
    retry_job_count: int
    billable_minutes: float | None
    estimated_cost_usd: float | None
