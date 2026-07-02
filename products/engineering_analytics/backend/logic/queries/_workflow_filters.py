"""Shared predicates for curated workflow-run window queries.

Clauses qualify columns with ``r`` — every consuming template reads the runs
source as ``FROM __RUNS_SOURCE__ AS r`` (or joins it as ``r``).
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope


def branch_filter_clause(branch: str | None, placeholders: dict[str, ast.Expr]) -> str:
    """Exact ``head_branch`` filter; registers its ``{branch}`` placeholder.

    An empty/whitespace branch is "no filter", not a literal match on ''.
    """
    value = branch.strip() if branch else ""
    if not value:
        return ""
    placeholders["branch"] = ast.Constant(value=value)
    return "AND r.head_branch = {branch}"


def run_scope_filter_clause(run_scope: WorkflowHealthRunScope) -> str:
    if run_scope == WorkflowHealthRunScope.PULL_REQUEST:
        # A default-branch run can still carry a PR association (its SHA matches an open PR),
        # so PR attribution alone doesn't keep trunk runs out. The warehouse source doesn't
        # sync the repo's default branch, so exclude the common default-branch names instead —
        # cheap string check first, short-circuiting the JSON-derived pr_number.
        return "AND r.head_branch NOT IN ('master', 'main') AND r.pr_number > 0"
    return ""
