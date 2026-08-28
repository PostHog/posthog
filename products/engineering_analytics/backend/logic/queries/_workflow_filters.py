"""Shared predicates for curated workflow-run window queries.

Clauses qualify columns with ``r`` — every consuming template reads the runs
source as ``FROM __RUNS_SOURCE__ AS r`` (or joins it as ``r``).
"""

from datetime import datetime, timedelta

from posthog.hogql import ast

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope

# Trunk's merge-queue batch branches. Trunk-specific and hardcoded like KNOWN_BOT_HANDLES;
# defined once here so every surface breaks queue spend out with the same key.
MERGE_QUEUE_BRANCH_PREFIX = "trunk-merge/"


def merge_queue_branch_predicate(branch_sql: str) -> str:
    """True when the branch expression names a merge-queue batch branch."""
    return f"startsWith({branch_sql}, '{MERGE_QUEUE_BRANCH_PREFIX}')"


# The base duration-percentile population, for runs and jobs alike: successful instances
# only. Cancelled/skipped (superseded) and failed instances end early, so including them
# answers "how long until CI stopped", not "how long does CI take to pass". Jobs use this
# as-is — a seconds-long job (the gate job itself) is a legitimate duration sample.
DURATION_PERCENTILE_CONDITION = "status = 'completed' AND conclusion = 'success'"

# A run that settled in under this many seconds with a benign conclusion did no real CI work — the
# common shape is a gate job deciding the rest of the workflow should be skipped (path filters,
# eligibility checks). The run-activity chart query sorts these AFTER real runs so its row cap fills
# with real executions first, then drops them when enough real runs remain (see
# ``workflow_run_activity``) — duration alone can't tell a gate no-op from an intentionally fast
# workflow, so an all-fast workflow keeps its history instead of an empty chart. Mirrors ``isNoOpRun``
# in ``frontend/lib/runHealth.ts`` (keep the two in sync): decisive failures and attention-needing
# conclusions (``action_required``, ``startup_failure``) are never no-ops — failing in seconds is
# signal, not noise.
NO_OP_RUN_MAX_SECONDS = 10
NO_OP_RUN_FLAG = (
    # ifNull keeps the flag NULL-free: an in-flight run (NULL duration) and a completed row with a
    # NULL conclusion (the column is nullable; conclusions can lag the sync) would each turn the AND
    # into NULL — both must read as real (0), never as no-ops.
    f"ifNull(r.duration_seconds < {NO_OP_RUN_MAX_SECONDS} "
    "AND r.conclusion IN ('success', 'skipped', 'neutral', 'completed', 'cancelled'), 0)"
)

# Run duration percentiles additionally exclude no-op gate runs: a workflow that mostly "succeeds"
# in seconds without doing real work would otherwise report a seconds-long p50 on every surface.
RUN_DURATION_PERCENTILE_CONDITION = f"{DURATION_PERCENTILE_CONDITION} AND NOT {NO_OP_RUN_FLAG}"


def run_duration_percentile_expr(quantile: float) -> str:
    """Bare (unaliased) duration percentile over successful non-no-op runs, per aggregate group.
    Falls back to every successful run when the group has no real samples — duration alone can't
    tell a gate no-op from an intentionally fast workflow — mirroring the activity endpoint and
    the frontend ``computeHealthSummary``."""
    return (
        f"if(countIf({RUN_DURATION_PERCENTILE_CONDITION}) > 0, "
        f"quantileIf({quantile})(duration_seconds, {RUN_DURATION_PERCENTILE_CONDITION}), "
        f"quantileIf({quantile})(duration_seconds, {DURATION_PERCENTILE_CONDITION}))"
    )


# The one "failing right now" signal, per workflow: did the latest completed run fail?
# Ordered by (run_started_at, id) so a same-second tie resolves deterministically to the
# later-created run. argMaxIf defaults to 0 (false) over zero matching rows, so consumers must
# pair it with a completed-run count to tell "latest run passed" apart from "no completed run yet".
LATEST_COMPLETED_RUN_FAILED = (
    "argMaxIf(conclusion IN ('failure', 'timed_out'), (run_started_at, id), status = 'completed')"
)


def run_started_floor_constant(window_start: datetime) -> ast.Constant:
    """Raw-string scan floor for the runs builder's {run_started_floor} placeholder: a date-only
    string one day below the window start. Compares lexicographically below every in-window
    ISO timestamp ('2026-07-11' < '2026-07-11T...'), and the one-day slack absorbs any timezone
    offset between the window's zone and the UTC strings GitHub lands, so the coarse floor can
    never cut rows the precise parsed {date_from} filter would keep."""
    return ast.Constant(value=(window_start - timedelta(days=1)).strftime("%Y-%m-%d"))


# How far below a window start the jobs-scan floor sits, by what the window actually filters.
#
# ON_JOB_CREATED: the query bounds the job's own created_at, so the floor only has to absorb the
# timezone offset between the window's zone and the UTC strings GitHub lands — one day, exactly like
# run_started_floor_constant.
#
# ON_RUN_STARTED: the query bounds the RUN's start instead, and the two clocks come apart on a re-run.
# The runs snapshot upserts by id, so a re-run carries only its NEWEST attempt's run_started_at while
# its earlier attempts' job rows were created back when those attempts ran — and those are the rows
# that actually executed (a later attempt mostly re-lists them; see the workflow_jobs builder). A
# one-day floor would cut exactly those, silently under-reporting the re-run's cost. A week covers
# realistic re-run latency ("re-run on Monday what failed on Friday") and still turns an all-time jobs
# scan into a bounded one. It is a bound, not a proof: a re-run older than this loses its earlier
# attempts from the window's cost, which is the coarseness the floor trades for the scan.
#
# The same wide floor applies to any query that EXCLUDES re-run copies, whichever clock it windows:
# the copy is only recognisable while its original attempt is inside the scan, so a tight floor under a
# late re-run would turn the copy back into an execution. Queries that keep copies (red/green reads)
# can use the tight floor.
_JOB_FLOOR_SLACK_ON_JOB_CREATED = timedelta(days=1)
_JOB_FLOOR_SLACK_ON_RUN_STARTED = timedelta(days=7)


def _date_floor(window_start: datetime, slack: timedelta) -> ast.Constant:
    """A date-only string ``slack`` below the window start. Date-only on purpose: it compares
    lexicographically below every in-window ISO timestamp ('2026-07-11' < '2026-07-11T...')."""
    return ast.Constant(value=(window_start - slack).strftime("%Y-%m-%d"))


def job_created_floor_constant(window_start: datetime) -> ast.Constant:
    """Raw-string scan floor for the jobs builder's {job_created_floor} placeholder, for a query that
    windows the job's own ``created_at``. See ``_JOB_FLOOR_SLACK_ON_JOB_CREATED``."""
    return _date_floor(window_start, _JOB_FLOOR_SLACK_ON_JOB_CREATED)


def run_windowed_job_created_floor_constant(window_start: datetime) -> ast.Constant:
    """Raw-string scan floor for the jobs builder's {job_created_floor} placeholder, for a query that
    windows the RUN's start (every cost surface does). Wider than the job-created floor because a
    re-run's earlier attempts were created before its run_started_at — see
    ``_JOB_FLOOR_SLACK_ON_RUN_STARTED``."""
    return _date_floor(window_start, _JOB_FLOOR_SLACK_ON_RUN_STARTED)


def branch_filter_clause(
    branch: str | None, placeholders: dict[str, ast.Expr], *, column: str = "r.head_branch"
) -> str:
    """Exact head-branch filter; registers its ``{branch}`` placeholder.

    An empty/whitespace branch is "no filter", not a literal match on ''. ``column`` lets the cost
    queries point the same filter at the job cost source's ``c.run_head_branch`` (the run's branch,
    kept distinct from the per-job ``head_branch``) instead of the run source's ``r.head_branch``.
    """
    value = branch.strip() if branch else ""
    if not value:
        return ""
    placeholders["branch"] = ast.Constant(value=value)
    return f"AND {column} = {{branch}}"


def date_to_filter_clause(
    date_to: datetime | None, placeholders: dict[str, ast.Expr], *, column: str = "r.run_started_at"
) -> str:
    """Optional window end; registers its ``{date_to}`` placeholder. ``column`` retargets it at the
    cost source's ``c.run_started_at`` for the cost queries."""
    if date_to is None:
        return ""
    placeholders["date_to"] = ast.Constant(value=date_to)
    return f"AND {column} <= {{date_to}}"


@frozen
class WindowPredicates:
    current: str
    previous: str


def window_pair_predicates(column: str, *, date_to: datetime | None) -> WindowPredicates:
    """The current/previous window predicates every with-prev aggregate splits on.

    Half-open at ``{date_from}``: a row exactly on the boundary is current, never both. Callers
    register ``{date_from}``/``{prev_from}`` (and ``{date_to}`` when set) themselves; the pair is
    the one place the boundary semantics live, not the placeholder bookkeeping.
    """
    return WindowPredicates(
        current=f"({column} >= {{date_from}}" + (f" AND {column} <= {{date_to}})" if date_to is not None else ")"),
        previous=f"({column} >= {{prev_from}} AND {column} < {{date_from}})",
    )


def non_default_branch_predicate(branch_column: str = "r.head_branch") -> str:
    """True when the branch expression names a branch other than the repo's default. The source
    doesn't record which branch that is, so this excludes the common default names — the same
    approximation ``repo_overview.query_default_branch`` resolves per-repo, not reused here
    because it costs an extra query."""
    return f"{branch_column} NOT IN ('master', 'main')"


def run_scope_filter_clause(
    run_scope: WorkflowHealthRunScope,
    *,
    branch_column: str = "r.head_branch",
    attributed_predicate: str = "r.pr_number > 0",
) -> str:
    if run_scope == WorkflowHealthRunScope.PULL_REQUEST:
        # A default-branch run can still carry a PR association (its SHA matches an open PR), so
        # attribution alone (pr_number > 0 — see the workflow_runs builder docstring) doesn't keep
        # trunk runs out; the scope needs both predicates.
        # The cost queries pass the cost source's columns; there pr_number is 0→NULL normalized, so
        # "attributed" becomes ``c.pr_number IS NOT NULL`` rather than ``> 0``.
        # Merge-queue gate runs stay in this scope on purpose: a gate run is CI the PR paid for on
        # its way to landing, and the runs builder already credits it to that PR rather than to the
        # throwaway PR the queue opened. ``is_merge_queue`` splits the two populations, on the cost
        # view and the job-history view alike.
        return f"AND {non_default_branch_predicate(branch_column)} AND {attributed_predicate}"
    return ""
