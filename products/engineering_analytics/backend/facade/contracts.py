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

from posthog.hogql.database.models import FieldOrTable


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


class BrokenTestState(StrEnum):
    """How a live CI-failure fingerprint is behaving right now — the broken-tests classifier's
    verdict, ordered by triage urgency (``breaking_master`` on top, ``pr_only`` last). Inferred
    from the failure fingerprints and the latest default-branch job status; see
    ``logic/queries/broken_tests.py`` for the thresholds.

    - ``breaking_master``: has failed on the default branch and that job's latest completed run
      is still red — trunk is broken by this right now.
    - ``novel_burst``: first seen within the last day and already spreading across several PR
      branches, not on the default branch yet — a new failure catching on.
    - ``potentially_resolved``: hit the default branch but that job's latest run is green again —
      probably already fixed.
    - ``flaky``: sporadic across two or more branches over more than a day, never on the default
      branch — a recurring flake, not a trunk break.
    - ``pr_only``: confined to a single branch — one PR's own problem, the lowest signal.
    """

    BREAKING_MASTER = "breaking_master"
    NOVEL_BURST = "novel_burst"
    POTENTIALLY_RESOLVED = "potentially_resolved"
    FLAKY = "flaky"
    PR_ONLY = "pr_only"


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
class ExpectedWarehouseView:
    """A code-generated warehouse view this product exposes as a team-scoped DataWarehouse saved
    query. data_modeling adapts it into its own ``ExpectedView`` without importing this product's
    internals (avoids a dependency cycle). ``query`` is the HogQL SELECT body; ``fields`` maps column
    name -> a ``FieldOrTable`` instance, from which data_modeling derives the stored
    ``{"hogql": <field class>, "clickhouse": <type>, "valid": True}`` metadata via its shared
    ``_get_columns_from_fields`` path (the same one revenue analytics uses) — so the type strings are
    never hand-written here and can't drift from the real field classes.
    """

    name: str
    query: str
    fields: dict[str, FieldOrTable]


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
class PRLLMSpend:
    """Agent LLM token spend attributed to one PR, summed over the ``$ai_generation`` events stamped
    with the PR's git branch (``$ai_git_branch``).

    Attribution is by branch, not head SHA: a coding agent stamps the branch at capture time — before
    the PR exists — and the ``github_pull_requests`` snapshot keeps only the latest head, so a SHA join
    would drop every push but the last. Surfaced as ``PRCostSummary.llm_spend``, and None there when no
    generation matched (so the UI hides the row rather than showing a $0 line).
    """

    cost_usd: float
    input_tokens: int
    output_tokens: int
    generations: int


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
    # Agent LLM token spend attributed to this PR by git branch ($ai_git_branch), or None when no
    # $ai_generation matched — independent of the CI cost figures above, so it can be present even when
    # jobs_available is False (the two spend sources sync separately).
    llm_spend: PRLLMSpend | None = None


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


# The one caveat that governs every flaky figure, defined once here (the canonical-types home)
# so the API/MCP description and any other consumer-facing copy read from it instead of drifting.
FLAKY_TEST_SIGNAL_CAVEAT = (
    "Counts are absolute, never rates: CI emits a span for every failure but only for passes slow "
    "enough to clear the emitter's duration threshold, so there is no execution denominator. "
    "'suspected_regression' means no same-commit recovery was recorded, not that none exists."
)


class FlakyTestClassification(StrEnum):
    # One commit both failed and passed the test.
    CONFIRMED_FLAKE = "confirmed_flake"
    # Only failures recorded, which is absence of proof, not proof of a regression.
    SUSPECTED_REGRESSION = "suspected_regression"
    # Failing while masked as xfail.
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class FlakyTestItem:
    """One test in the active test-health queue, aggregated from the per-test CI spans in the Traces store.

    Evidence is counted per CI run, never per span or run attempt: a re-run re-reports the shards it
    did not re-execute, so only the run grain counts one failure once. See
    ``FLAKY_TEST_SIGNAL_CAVEAT`` for why every figure is an absolute count.
    """

    # Reconstructed pytest nodeid (the span name), e.g. 'posthog/api/test/test_x/TestX::test_y'.
    nodeid: str
    # Runnable pytest selector ('posthog/api/test/test_x.py::TestX::test_y'). Exact when the CI
    # reporter stamped it; reconstructed from the nodeid (file/class boundary guessed) for older spans.
    selector: str
    classification: FlakyTestClassification
    # Runs where one commit both failed and passed: a later attempt going green, or an in-job retry.
    # A pass in a different run is a different commit and proves nothing, hence the name.
    same_commit_recovery_run_count: int
    failed_run_count: int
    # Master/branch failures carry no PR number and don't count here.
    failed_pr_count: int
    # master/main approximation: the source doesn't record the default branch.
    master_failed_run_count: int
    quarantined_failed_run_count: int
    last_signal_at: datetime


@dataclass(frozen=True)
class FlakyTestList:
    """The active test-health queue for a window: tests with a live failure signal, ranked by blast
    radius (trunk first, then PRs, then runs), capped at ``limit`` with an explicit truncation flag
    (same shape as ``PullRequestList``). A test qualifies on any same-commit recovery, any
    default-branch failure, failures on at least ``min_failed_prs`` distinct PRs, or an xfail.
    """

    items: list[FlakyTestItem]
    truncated: bool
    limit: int


@dataclass(frozen=True)
class TeamCIHealthItem:
    """One owning team's rollup of the CI test surfaces it owns, with equal-length
    previous-window twins so a caller can render honest deltas.

    Ownership rides on the spans themselves (the CI emitter stamps ``test.owner_team``
    from the repo's ownership map at emission time); spans with no stamp aggregate
    under the literal team ``'unowned'``. See ``FLAKY_TEST_SIGNAL_CAVEAT`` for why
    every figure is an absolute count, never a rate.
    """

    # Owning team slug (CODEOWNERS handle minus '@PostHog/'), or 'unowned' for unstamped spans.
    owner_team: str
    # Owned tests a commit was seen both failing and passing: the same proof, and the same word,
    # the test-health queue's `confirmed_flake` uses.
    flaky_test_count: int
    flaky_test_count_prior: int
    # Owned tests that failed with no such proof and still hit the blast-radius bar. Not flakes.
    regression_test_count: int
    regression_test_count_prior: int
    # Runs (not spans) where an owned test's recorded outcome was failed or error.
    failed_run_count: int
    failed_run_count_prior: int
    same_commit_recovery_run_count: int
    same_commit_recovery_run_count_prior: int
    # Runs where an owned test failed while quarantined (xfail): already masked, still failing.
    quarantined_failed_run_count: int
    quarantined_failed_run_count_prior: int
    # Most recent failure, recovery, or xfail run across the team's owned tests, either window.
    last_seen_at: datetime


@dataclass(frozen=True)
class TeamCIHealthList:
    """The per-team CI health roster over a window (same {items, truncated, limit} shape as
    ``FlakyTestList``). Teams compare as organizational owners of code surfaces; this list
    never aggregates by author.
    """

    items: list[TeamCIHealthItem]
    truncated: bool
    limit: int


@dataclass(frozen=True)
class TeamTestSignal:
    """One owned test's flaky signal across the current window and its equal-length prior
    window, the pair behind a before-vs-after slope reading. Signal = failed + error +
    pass-on-retry spans (xfail excluded: already-quarantined noise).
    """

    nodeid: str
    selector: str
    signal_count: int
    signal_count_prior: int
    last_seen_at: datetime


@dataclass(frozen=True)
class TeamCIActivity:
    """One team's detail assembly: the per-test current-vs-prior signal pairs over the
    window and its equal-length prior twin, capped at the test limit.
    """

    owner_team: str
    tests: list[TeamTestSignal]
    truncated_tests: bool


@dataclass(frozen=True)
class TeamMergeTrendPoint:
    """One day of the team's merged-PR timing: the median and average open→merge over the
    PRs the team's members merged that day. Both are None on a day the team merged nothing;
    ``merged_count`` says how many merges back them.
    """

    day: datetime
    median_seconds: float | None
    average_seconds: float | None
    merged_count: int


@dataclass(frozen=True)
class TeamMergeTrend:
    """A team's time-to-merge trend over the window. Attribution is PR author login →
    GitHub org team membership (the ``team_members`` snapshot); only team-level medians
    are surfaced, never per-member figures or cross-team rankings (SPEC §2/§7).
    """

    owner_team: str
    # False when the source has no team_members snapshot synced: the chart has no honest
    # team attribution, as opposed to "synced but this team merged nothing".
    has_membership_data: bool
    points: list[TeamMergeTrendPoint]


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
class PushCISample:
    """One CI round (push) on a pull request, for the compact push-history sparkline:
    when the round started, its wall-clock CI time, and its verdict.
    """

    head_sha: str
    # Earliest run start on this push.
    started_at: datetime
    # First run start → last completed run end on this push; None while nothing has completed.
    wall_seconds: int | None
    # Any latest-per-workflow run on this push concluded 'failure' or 'timed_out'.
    failed: bool
    # Any latest-per-workflow run on this push hasn't completed yet.
    pending: bool


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
    # This PR's CI rounds oldest-first, capped to the most recent pushes (see the list query) — the
    # push-history sparkline. ``pushes`` stays the uncapped count.
    push_history: list[PushCISample] = field(default_factory=list)


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
class BranchPRMatch:
    """A pull request a git branch resolves to — the cross-product link seam so a caller
    (e.g. the LLM analytics UI) can turn a git branch into a PR detail link. ``repo`` is 'owner/name'.
    ``title`` / ``state`` are null only when the snapshot carries no value for them.
    """

    repo: str
    number: int
    title: str | None
    state: str | None


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
class PassRateBucket:
    """One time bucket of the repo's CI pass rate: the fraction of completed runs (all branches) started in
    this bucket that succeeded. ``success_rate`` is None for a bucket with no completed run (a gap, not a
    0% pass rate); the UI carries the last known value forward rather than dipping the trend to zero.
    """

    # Bucket start, aligned to the granularity (top of hour / midnight / Monday).
    bucket_start: datetime
    # Fraction (0-1) of completed runs started in this bucket that succeeded. None when none completed.
    success_rate: float | None


@dataclass(frozen=True)
class OpenToMergeBucket:
    """One time bucket of the repo's median time-to-merge: the p50 of ``merged_at - created_at`` over PRs
    merged in this bucket, bots and drafts excluded (the locked cycle-time recipe). Coarse by design (draft
    and ready time fused). ``p50_seconds`` is None for a bucket where nothing merged (a gap, not instant
    merges); the UI carries the last known value forward rather than dipping the trend to zero.
    """

    # Bucket start, aligned to the granularity (top of hour / midnight / Monday). Keyed on merge time.
    bucket_start: datetime
    # Median merged_at - created_at seconds over PRs merged in this bucket. None when nothing merged.
    p50_seconds: float | None


@dataclass(frozen=True)
class RepoOverview:
    """Repo-level headline aggregates for the landing page, each with its previous-window twin
    so the UI renders honest deltas. The previous window has the same length as the current one
    and ends where it starts. Cost figures are None when the job-level source isn't synced
    (``jobs_available``); the PR merge median excludes bots and drafts per the locked recipe.
    The chart series are empty when the caller asked to skip them (``include_series=false``) —
    headline-only consumers like the weekly digest shouldn't pay for chart queries they never read.
    """

    run_count: int
    run_count_prev: int
    success_rate: float | None
    success_rate_prev: float | None
    rerun_cycles: int
    rerun_cycles_prev: int
    # All merged PRs in the window, bots included — the merge population that triggered the CI spend,
    # so cost-per-merge ratios use the same denominator as the cost series' bucket-local merges.
    merged_pr_count: int
    merged_pr_count_prev: int
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
    # Pass-rate trend: fraction of completed runs (all branches) that succeeded per bucket, oldest first,
    # bucketed by `success_rate_series_granularity`. Empty buckets carry None (no completed run).
    success_rate_series: list[PassRateBucket]
    # Bucket width of `success_rate_series`, chosen to fit the window: 'hour', 'day', or 'week'.
    success_rate_series_granularity: str
    # Time-to-merge trend: median open_to_merge_seconds over PRs merged per bucket (bots/drafts excluded),
    # oldest first, bucketed by `open_to_merge_series_granularity`. Empty buckets carry None (nothing merged).
    open_to_merge_series: list[OpenToMergeBucket]
    # Bucket width of `open_to_merge_series`, chosen to fit the window: 'hour', 'day', or 'week'.
    open_to_merge_series_granularity: str


@dataclass(frozen=True)
class CurrentBranchHealth:
    """Current default-branch CI verdict over the last 24 hours.

    Counts cover every workflow with a completed run; names are a bounded preview for UI copy.
    """

    default_branch: str
    settled_workflows: int
    failing_workflows: int
    failing_workflow_names: list[str]


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


# The sparkline is a fixed-width hourly histogram; the width is the contract so a caller can render
# it without inspecting the array length. 24 slots = the last 24 hours, oldest first.
BROKEN_TEST_SPARKLINE_HOURS = 24


@dataclass(frozen=True)
class BrokenTestRow:
    """One classified CI-failure fingerprint — a distinct failing test/error, with its recent
    behavior and the classifier's verdict. Aggregated from the fingerprinted failure lines
    (``engineering_analytics_ci_failures``) over the analysis window, joined to the latest
    default-branch job status for the ``state``.

    ``trend_24h`` is a ``BROKEN_TEST_SPARKLINE_HOURS``-slot hourly failure count (oldest first)
    for the row sparkline — all zeros when nothing failed in the last day. ``latest_run_id`` is the
    most recent failing run, the anchor a drill-down passes to ``run_failure_logs`` for the log lines.
    """

    fingerprint: str
    # The pytest node id from the FAILED line (the failing test's identity).
    test_id: str
    # The normalized trailing failure detail shared across runs of the same failure; '' when none.
    error_signature: str
    # The CI job the failure most recently came from — the key joined to default-branch job status.
    job_name: str
    # 'owner/name' the failure belongs to.
    repo: str
    state: BrokenTestState
    first_seen: datetime
    last_seen: datetime
    # Total failure lines for this fingerprint in the window (absolute count, never a rate).
    occurrences: int
    # Distinct branches the failure appeared on.
    branches: int
    # Failure lines on the default branch (master/main) — 0 means it never hit trunk.
    master_hits: int
    latest_run_id: int
    latest_branch: str
    trend_24h: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class BrokenTestsResult:
    """The broken-tests panel payload: classified failure fingerprints ranked by triage urgency
    (breaking trunk first), plus the default-branch jobs whose latest completed run is red — the
    "what's on fire right now" summary. ``rows`` is capped at ``limit`` with a ``truncated`` flag,
    same shape as ``FlakyTestList``. ``window_days`` is the analysis window the counts cover.
    """

    rows: list[BrokenTestRow]
    # Default-branch job names whose latest completed run is failing — drives the summary banner.
    breaking_master_jobs: list[str]
    window_days: int
    truncated: bool
    limit: int


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
