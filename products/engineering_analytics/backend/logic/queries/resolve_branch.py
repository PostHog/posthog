"""HogQL resolution of a git branch to the pull request(s) it belongs to.

Powers the cross-product branch → PR link: another product (the LLM analytics UI)
turns a git branch into a PR detail link without re-deriving PostHog's PR↔CI attribution.

Matched directly against the PR snapshot's source branch (``head_branch`` = ``head.ref`` on
the curated PR source), open PRs first then most recently updated. A branch is reused across
PRs over time, so ordering surfaces the current one first, and the scan is time-bounded (a
resolving trace is recent). Results are capped — a reused branch can span several PRs, so the
return is a possibly-empty, possibly-multi set.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import BranchPRMatch
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# A branch usually resolves to one PR; cap low so a reused branch stays bounded.
_LIMIT = 5

# Match the PR snapshot's source branch directly; open first, then most recently updated. The
# recency bound keeps the snapshot scan cheap — a trace resolving here was captured recently, so a
# PR untouched for over a year can't be the one it means.
_BRANCH_SELECT = f"""
    SELECT
        pr.repo_owner AS repo_owner,
        pr.repo_name AS repo_name,
        pr.number AS number,
        pr.title AS title,
        pr.state AS state
    FROM __PR_SOURCE__ AS pr
    WHERE pr.head_branch = {{branch}} AND pr.updated_at >= now() - INTERVAL 1 YEAR __REPO__
    ORDER BY pr.state = 'open' DESC, pr.updated_at DESC
    LIMIT {_LIMIT}
"""


def query_resolve_branch(
    *,
    curated: CuratedGitHubSource,
    branch: str,
    repo_owner: str | None,
    repo_name: str | None,
) -> list[BranchPRMatch]:
    placeholders: dict[str, ast.Expr] = {"branch": ast.Constant(value=branch)}
    repo_clause = _repo_clause("pr", repo_owner, repo_name, placeholders)
    response = curated.run(
        _BRANCH_SELECT.replace("__PR_SOURCE__", curated.pr_source()).replace("__REPO__", repo_clause),
        query_type="engineering_analytics.resolve_branch",
        placeholders=placeholders,
    )
    return [_to_match(row) for row in (response.results or [])]


def _repo_clause(alias: str, repo_owner: str | None, repo_name: str | None, placeholders: dict[str, ast.Expr]) -> str:
    """Optional 'owner/name' narrowing on the given alias; a no-op filter when no repo was passed.

    Case-insensitive: GitHub repo names are, and the caller's slug comes from a clone URL whose
    casing need not match GitHub's canonical ``full_name``.
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
        # The '' state default comes back empty — normalize to None.
        title=title or None,
        state=state or None,
    )
