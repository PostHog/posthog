"""Shared predicates for curated workflow-run window queries.

Clauses qualify columns with ``r`` — every consuming template reads the runs
source as ``FROM __RUNS_SOURCE__ AS r`` (or joins it as ``r``).
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope

# The one duration-percentile population, for runs and jobs alike: successful instances
# only. Cancelled/skipped (superseded) and failed instances end early, so including them
# answers "how long until CI stopped", not "how long does CI take to pass".
DURATION_PERCENTILE_CONDITION = "status = 'completed' AND conclusion = 'success'"


def branch_filter_clause(branch: str | None, placeholders: dict[str, ast.Expr]) -> str:
    """Exact ``head_branch`` filter; registers its ``{branch}`` placeholder.

    An empty/whitespace branch is "no filter", not a literal match on ''.
    """
    value = branch.strip() if branch else ""
    if not value:
        return ""
    placeholders["branch"] = ast.Constant(value=value)
    return "AND r.head_branch = {branch}"


def date_to_filter_clause(date_to: datetime | None, placeholders: dict[str, ast.Expr]) -> str:
    """Optional window end; registers its ``{date_to}`` placeholder."""
    if date_to is None:
        return ""
    placeholders["date_to"] = ast.Constant(value=date_to)
    return "AND r.run_started_at <= {date_to}"


def run_scope_filter_clause(run_scope: WorkflowHealthRunScope) -> str:
    if run_scope == WorkflowHealthRunScope.PULL_REQUEST:
        # A default-branch run can still carry a PR association (its SHA matches an open PR),
        # so attribution (pr_number > 0 — see the workflow_runs builder docstring) alone doesn't
        # keep trunk runs out. The source doesn't record which branch is the repo's default, so
        # exclude the common default-branch names — the same approximation repo_overview's
        # query_default_branch resolves per-repo, not reused here because it costs an extra query.
        return "AND r.head_branch NOT IN ('master', 'main') AND r.pr_number > 0"
    return ""
