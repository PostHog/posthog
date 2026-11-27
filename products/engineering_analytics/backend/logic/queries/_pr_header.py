"""The newest snapshot row of one pull request, shared by the per-PR queries."""

from posthog.hogql import ast

# Duplicate snapshot rows of one PR share created_at, so updated_at picks the freshest row.
# created_at stays the secondary key because updated_at can be NULL on a malformed snapshot.
_TAIL = """
    FROM __PR_SOURCE__ AS pr
    WHERE number = {pr_number} AND repo_owner = {repo_owner} AND repo_name = {repo_name}
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 1
"""


def pr_header_query(select_clause: str) -> str:
    """A query for the newest row of one PR. The caller fills ``__PR_SOURCE__`` and binds
    ``pr_header_placeholders``."""
    return f"SELECT {select_clause}\n{_TAIL}"


def pr_header_placeholders(*, pr_number: int, repo_owner: str, repo_name: str) -> dict[str, ast.Expr]:
    return {
        "pr_number": ast.Constant(value=pr_number),
        "repo_owner": ast.Constant(value=repo_owner),
        "repo_name": ast.Constant(value=repo_name),
    }
