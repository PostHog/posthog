"""Shared predicates for curated workflow-run window queries."""

from products.engineering_analytics.backend.facade.contracts import WorkflowHealthRunScope


def normalized_branch(branch: str | None) -> str | None:
    value = branch.strip() if branch else ""
    return value or None


def branch_filter_clause(branch: str | None, *, alias: str = "") -> str:
    if normalized_branch(branch) is None:
        return ""
    return f"AND {_column(alias, 'head_branch')} = {{branch}}"


def run_scope_filter_clause(run_scope: WorkflowHealthRunScope, *, alias: str = "") -> str:
    if run_scope == WorkflowHealthRunScope.PULL_REQUEST:
        return f"AND {_column(alias, 'pr_number')} > 0 AND {_column(alias, 'head_branch')} != 'master'"
    return ""


def _column(alias: str, name: str) -> str:
    return f"{alias}.{name}" if alias else name
