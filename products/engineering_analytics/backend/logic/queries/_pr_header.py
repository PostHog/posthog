"""Shared fetch-one-PR-row query used by the per-PR queries.

``pr_lifecycle`` and ``llm_spend`` both pull the newest matching PR row keyed on
``(number, repo_owner, repo_name)`` and differ only in the columns they select. Centralizing the
WHERE/ORDER/LIMIT tail and the placeholders (same idea as ``_run_detail``'s column list) keeps the
row-selection rule — the newest-first tie-break — defined once, so a future change can't drift
between the two call sites.
"""

from posthog.hogql import ast

# The newest PR row for (number, repo_owner, repo_name). Callers pass their own SELECT column list and
# fill __PR_SOURCE__ with the curated subquery. {value} placeholders survive for parse_select.
_TAIL = """
    FROM __PR_SOURCE__ AS pr
    WHERE number = {pr_number} AND repo_owner = {repo_owner} AND repo_name = {repo_name}
    ORDER BY created_at DESC
    LIMIT 1
"""


def pr_header_query(select_clause: str) -> str:
    """Wrap a SELECT column list into the shared newest-PR-row fetch (WHERE/ORDER/LIMIT)."""
    return f"SELECT {select_clause}\n{_TAIL}"


def pr_header_placeholders(*, pr_number: int, repo_owner: str, repo_name: str) -> dict[str, ast.Expr]:
    return {
        "pr_number": ast.Constant(value=pr_number),
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
    }
