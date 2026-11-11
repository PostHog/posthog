"""Resolves a git branch to the pull requests whose source branch it is.

A branch is reused across PRs over time, so the result can hold several PRs or none. Open PRs come
first, then the most recently updated. A ``timestamp`` ranks the PRs that were live at that moment
ahead of the others and never filters.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import BranchPRMatch
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.llm_spend import _LEAD_DAYS

_LIMIT = 5

# The window opens _LEAD_DAYS before created_at, because agent work and its trace start before the
# PR is opened. The lead must match the spend-attribution window in llm_spend.
_TS_RANK = (
    f"(pr.created_at - INTERVAL {_LEAD_DAYS} DAY <= {{ts}} "
    "AND {ts} <= coalesce(pr.merged_at, pr.closed_at, now())) DESC, "
)

# A caller resolves the branch of a recently captured trace, so a PR with no update for a year
# cannot be the one it means.
_BRANCH_SELECT = f"""
    SELECT
        pr.repo_owner AS repo_owner,
        pr.repo_name AS repo_name,
        pr.number AS number,
        pr.title AS title,
        pr.state AS state
    FROM __PR_SOURCE__ AS pr
    WHERE pr.head_branch = {{branch}} AND pr.updated_at >= now() - INTERVAL 1 YEAR __REPO__
    ORDER BY __TS_RANK__ pr.state = 'open' DESC, pr.updated_at DESC
    LIMIT {_LIMIT}
"""


def query_resolve_branch(
    *,
    curated: CuratedGitHubSource,
    branch: str,
    repo_owner: str | None,
    repo_name: str | None,
    timestamp: datetime | None = None,
) -> list[BranchPRMatch]:
    placeholders: dict[str, ast.Expr] = {"branch": ast.Constant(value=branch)}
    repo_clause = _repo_clause("pr", repo_owner, repo_name, placeholders)
    ts_rank = ""
    if timestamp is not None:
        placeholders["ts"] = ast.Constant(value=timestamp)
        ts_rank = _TS_RANK
    response = curated.run(
        _BRANCH_SELECT.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__REPO__", repo_clause)
        .replace("__TS_RANK__", ts_rank),
        query_type="engineering_analytics.resolve_branch",
        placeholders=placeholders,
    )
    return [_to_match(row) for row in (response.results or [])]


def _repo_clause(alias: str, repo_owner: str | None, repo_name: str | None, placeholders: dict[str, ast.Expr]) -> str:
    """An AND clause that narrows to one repo, or '' when no repo was passed.

    The match ignores case, because the caller's slug comes from a clone URL whose casing can
    differ from GitHub's ``full_name``.
    """
    if not (repo_owner and repo_name):
        return ""
    placeholders["repo_owner"] = ast.Constant(value=repo_owner.lower())
    placeholders["repo_name"] = ast.Constant(value=repo_name.lower())
    return f"AND lower({alias}.repo_owner) = {{repo_owner}} AND lower({alias}.repo_name) = {{repo_name}}"


def _to_match(row: tuple) -> BranchPRMatch:
    repo_owner, repo_name, number, title, state = row
    return BranchPRMatch(
        repo=f"{repo_owner}/{repo_name}",
        number=int(number),
        title=title or None,
        state=state or None,
    )
