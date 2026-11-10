"""Run-window predicates. They qualify columns with ``r``, so a query must alias the runs source as ``r``."""

from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope

# HogQL caps a query that names no LIMIT at 100 rows and clamps any larger LIMIT to this ceiling.
UNPAGED_SCAN_LIMIT = MAX_SELECT_RETURNED_ROWS

# Mirrors DECISIVE_FAILURE_CONCLUSIONS in frontend/lib/lifecycle.ts (keep the two in sync).
DECISIVE_FAILURE_CONCLUSIONS = ("failure", "timed_out", "startup_failure", "stale")
DECISIVE_FAILURE_CONCLUSIONS_SQL = ", ".join(f"'{conclusion}'" for conclusion in DECISIVE_FAILURE_CONCLUSIONS)
SUCCESSFUL_RUN_CONDITION = "status = 'completed' AND conclusion = 'success'"
FAILED_RUN_CONDITION = f"status = 'completed' AND conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL})"
CONCLUSIVE_RUN_CONDITION = f"status = 'completed' AND conclusion IN ('success', {DECISIVE_FAILURE_CONCLUSIONS_SQL})"

# Cancelled, skipped, and failed instances end early, so only successful ones are duration samples.
DURATION_PERCENTILE_CONDITION = SUCCESSFUL_RUN_CONDITION


def success_rate_expr(scope: str | None = None) -> str:
    """Unaliased pass rate: successful runs over conclusive runs, NULL when no run reached a verdict.
    ``scope`` ANDs an extra predicate into both counts."""
    guard = f" AND {scope}" if scope else ""
    return f"countIf({SUCCESSFUL_RUN_CONDITION}{guard}) / nullIf(countIf({CONCLUSIVE_RUN_CONDITION}{guard}), 0)"


def failure_rate_expr(scope: str | None = None) -> str:
    """The complement of ``success_rate_expr`` over the same denominator."""
    guard = f" AND {scope}" if scope else ""
    return f"countIf({FAILED_RUN_CONDITION}{guard}) / nullIf(countIf({CONCLUSIVE_RUN_CONDITION}{guard}), 0)"


# A run that settled this fast with a benign conclusion did no CI work. Usually a gate job skipped the
# rest of the workflow. A run that failed in seconds is never a no-op. Mirrors ``isNoOpRun`` in
# ``frontend/lib/runHealth.ts`` (keep the two in sync).
NO_OP_RUN_MAX_SECONDS = 10
NO_OP_RUN_FLAG = (
    # A NULL duration (in-flight run) or a NULL conclusion must read as a real run, not as a no-op.
    f"ifNull(r.duration_seconds < {NO_OP_RUN_MAX_SECONDS} "
    "AND r.conclusion IN ('success', 'skipped', 'neutral', 'completed', 'cancelled'), 0)"
)

RUN_DURATION_PERCENTILE_CONDITION = f"{DURATION_PERCENTILE_CONDITION} AND NOT {NO_OP_RUN_FLAG}"


def run_duration_percentile_expr(quantile: float) -> str:
    """Unaliased duration percentile over successful runs that are not no-ops. Falls back to every
    successful run when the group has no other samples, because duration alone cannot tell a gate
    no-op from an intentionally fast workflow. The frontend ``computeHealthSummary`` does the same."""
    return (
        f"if(countIf({RUN_DURATION_PERCENTILE_CONDITION}) > 0, "
        f"quantileIf({quantile})(duration_seconds, {RUN_DURATION_PERCENTILE_CONDITION}), "
        f"quantileIf({quantile})(duration_seconds, {DURATION_PERCENTILE_CONDITION}))"
    )


# The engine and the id make a same-second tie resolve deterministically.
LATEST_RUN_ORDER = "(run_started_at, ci_engine, id)"

# argMaxIf returns 0 over zero matching rows, so a consumer must pair this with a completed-run
# count to tell "latest run passed" from "no completed run yet".
LATEST_COMPLETED_RUN_FAILED = (
    f"argMaxIf(conclusion IN ({DECISIVE_FAILURE_CONCLUSIONS_SQL}), {LATEST_RUN_ORDER}, status = 'completed')"
)

# Absorbs the offset between the window's timezone and the UTC strings the source lands.
_DATE_FLOOR_SLACK = timedelta(days=1)

# A date-only floor reaches back past the slack it subtracts: up to a day for the day rounding, and up
# to a day more for the window's offset from the UTC strings it compares with.
_DATE_FLOOR_REACH = timedelta(days=2)


def run_started_floor_constant(window_start: datetime) -> ast.Constant:
    """Scan floor for a {run_started_floor} or {event_created_floor} placeholder. It never cuts a row
    that the parsed window filter would keep."""
    return _date_floor(window_start, _DATE_FLOOR_SLACK)


_JOB_FLOOR_SLACK_ON_JOB_CREATED = _DATE_FLOOR_SLACK

# For a query that windows the run's start, or that excludes re-run copies. The runs snapshot keeps
# only a re-run's newest run_started_at, while the job rows of its earlier attempts were created when
# those attempts ran. A copy is also recognisable only while its original attempt is inside the scan.
# A re-run later than this slack loses its earlier attempts from the window.
JOB_FLOOR_SLACK_ON_RUN_STARTED = timedelta(days=7)

# The furthest any scan floor reaches below its window start. The stored CI rows serve a read only
# when its window starts at least this far after their coverage start.
WIDEST_SCAN_FLOOR_SLACK = JOB_FLOOR_SLACK_ON_RUN_STARTED + _DATE_FLOOR_REACH


def _date_floor(window_start: datetime, slack: timedelta) -> ast.Constant:
    """A date-only string ``slack`` below the window start. It compares lexicographically below
    every in-window ISO timestamp, so it works against the raw string columns."""
    return ast.Constant(value=(window_start - slack).strftime("%Y-%m-%d"))


def job_created_floor_constant(window_start: datetime) -> ast.Constant:
    """{job_created_floor} for a query that windows the job's own ``created_at``."""
    return _date_floor(window_start, _JOB_FLOOR_SLACK_ON_JOB_CREATED)


def run_windowed_job_created_floor_constant(window_start: datetime) -> ast.Constant:
    """{job_created_floor} for a query that windows the run's start, or that excludes re-run copies."""
    return _date_floor(window_start, JOB_FLOOR_SLACK_ON_RUN_STARTED)


def branch_filter_clause(
    branch: str | None, placeholders: dict[str, ast.Expr], *, column: str = "r.head_branch"
) -> str:
    """Exact head-branch filter that registers ``{branch}``. An empty or whitespace branch means no filter."""
    value = branch.strip() if branch else ""
    if not value:
        return ""
    placeholders["branch"] = ast.Constant(value=value)
    return f"AND {column} = {{branch}}"


def workflow_name_filter_clause(
    workflow_name: str | None, placeholders: dict[str, ast.Expr], *, column: str = "r.workflow_name"
) -> str:
    """Exact workflow-name filter that registers ``{workflow_name}``. The name binds unstripped."""
    if not (workflow_name or "").strip():
        return ""
    placeholders["workflow_name"] = ast.Constant(value=workflow_name)
    return f"AND {column} = {{workflow_name}}"


def date_to_filter_clause(
    date_to: datetime | None, placeholders: dict[str, ast.Expr], *, column: str = "r.run_started_at"
) -> str:
    """Inclusive window end that registers ``{date_to}``, or '' when ``date_to`` is None."""
    if date_to is None:
        return ""
    placeholders["date_to"] = ast.Constant(value=date_to)
    return f"AND {column} <= {{date_to}}"


@frozen
class WindowPredicates:
    current: str
    previous: str


def window_pair_predicates(column: str, *, date_to: datetime | None) -> WindowPredicates:
    """The current and previous window predicates. A row exactly on ``{date_from}`` is current only.
    The caller registers ``{date_from}``, ``{prev_from}``, and ``{date_to}`` when set."""
    return WindowPredicates(
        current=f"({column} >= {{date_from}}" + (f" AND {column} <= {{date_to}})" if date_to is not None else ")"),
        previous=f"({column} >= {{prev_from}} AND {column} < {{date_from}})",
    )


def default_branch_predicate(branch_column: str = "r.head_branch") -> str:
    """Treats ``master`` and ``main`` as the default branch, because the runs source does not record it.
    ``default_branches.query_default_branches`` reads GitHub's value from the PR snapshot."""
    return f"{branch_column} IN ('master', 'main')"


def run_scope_filter_clause(
    run_scope: WorkflowHealthRunScope,
    *,
    branch_column: str = "r.head_branch",
    attributed_predicate: str = "r.pr_number > 0",
    merge_queue_predicate: str = "r.is_merge_queue",
) -> str:
    """The WHERE fragment for one ``WorkflowHealthRunScope``, or '' for ``all``. ``pull_request`` needs
    all three predicates: a default-branch run can still carry a PR association, and gate runs belong to
    ``merge_queue``."""
    if run_scope == WorkflowHealthRunScope.DEFAULT_BRANCH:
        return f"AND {default_branch_predicate(branch_column)}"
    if run_scope == WorkflowHealthRunScope.PULL_REQUEST:
        return (
            f"AND NOT {default_branch_predicate(branch_column)} AND {attributed_predicate} "
            f"AND NOT {merge_queue_predicate}"
        )
    if run_scope == WorkflowHealthRunScope.MERGE_QUEUE:
        return f"AND {merge_queue_predicate}"
    return ""


def cost_run_scope_filter_clause(run_scope: WorkflowHealthRunScope, *, alias: str = "c") -> str:
    """``run_scope_filter_clause`` against the job cost source, which names the run's branch
    ``run_head_branch`` and holds NULL, not 0, for a missing ``pr_number``."""
    return run_scope_filter_clause(
        run_scope,
        branch_column=f"{alias}.run_head_branch",
        attributed_predicate=f"{alias}.pr_number IS NOT NULL",
        merge_queue_predicate=f"{alias}.is_merge_queue",
    )
