"""HogQL resolution of a commit SHA or branch to the pull request(s) it belongs to.

Powers the cross-product commit/branch → PR link: another product (the LLM analytics UI)
turns a git ref into a PR detail link without re-deriving PostHog's PR↔CI attribution.

Two resolution paths, both embedding the curated builders as subqueries (via ``_curated``):

- **SHA path** — a commit's PR is found through the workflow runs it triggered. Each run
  carries its ``pull_requests`` association (surfaced as the curated ``pr_number``), which
  survives every push; the current-state PR snapshot keeps only the latest head SHA, so a
  ``head_sha`` join against the snapshot would drop every earlier push (SPEC §7). Runs whose
  ``head_sha`` starts with the given prefix yield the attributed ``pr_number``, enriched with
  title/state from the PR snapshot (null when the PR has since aged out of the snapshot).
- **Branch path** — matched directly against the PR snapshot's source branch
  (``head_branch`` = ``head.ref`` on the curated PR source), open PRs first then most recently
  updated. A branch is reused across PRs over time, so ordering surfaces the current one first.

Only run the branch path when the SHA path found nothing (or no SHA was given): a SHA is the
precise key, a branch the fallback. Both paths cap results — a commit can head several PRs and a
short SHA prefix can span commits, so the return is a possibly-empty, possibly-multi set.
"""

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import CommitPRMatch
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# A ref usually resolves to one PR; cap low so a short-prefix SHA or reused branch stays bounded.
_LIMIT = 5

# SHA path: runs matching the prefix carry the attribution key; the PR snapshot enriches title/state.
_SHA_SELECT = f"""
    SELECT
        r.repo_owner AS repo_owner,
        r.repo_name AS repo_name,
        r.pr_number AS pr_number,
        any(pr.title) AS title,
        any(pr.state) AS state
    FROM __RUNS_SOURCE__ AS r
    LEFT JOIN __PR_SOURCE__ AS pr
        ON pr.number = r.pr_number AND pr.repo_owner = r.repo_owner AND pr.repo_name = r.repo_name
    WHERE startsWith(r.head_sha, {{sha}}) AND r.pr_number > 0 __REPO__
    GROUP BY r.repo_owner, r.repo_name, r.pr_number
    ORDER BY pr_number DESC
    LIMIT {_LIMIT}
"""

# Branch path: match the PR snapshot's source branch directly; open first, then most recently updated.
_BRANCH_SELECT = f"""
    SELECT
        pr.repo_owner AS repo_owner,
        pr.repo_name AS repo_name,
        pr.number AS number,
        pr.title AS title,
        pr.state AS state
    FROM __PR_SOURCE__ AS pr
    WHERE pr.head_branch = {{branch}} __REPO__
    ORDER BY pr.state = 'open' DESC, pr.updated_at DESC
    LIMIT {_LIMIT}
"""


def query_resolve_commit(
    *,
    curated: CuratedGitHubSource,
    sha: str | None,
    branch: str | None,
    repo_owner: str | None,
    repo_name: str | None,
) -> list[CommitPRMatch]:
    matches: list[CommitPRMatch] = []
    if sha:
        matches = _resolve_by_sha(curated=curated, sha=sha, repo_owner=repo_owner, repo_name=repo_name)
    if not matches and branch:
        matches = _resolve_by_branch(curated=curated, branch=branch, repo_owner=repo_owner, repo_name=repo_name)
    return matches


def _resolve_by_sha(
    *, curated: CuratedGitHubSource, sha: str, repo_owner: str | None, repo_name: str | None
) -> list[CommitPRMatch]:
    placeholders: dict[str, ast.Expr] = {"sha": ast.Constant(value=sha)}
    repo_clause = _repo_clause("r", repo_owner, repo_name, placeholders)
    response = curated.run(
        _SHA_SELECT.replace("__RUNS_SOURCE__", curated.run_source())
        .replace("__PR_SOURCE__", curated.pr_source())
        .replace("__REPO__", repo_clause),
        query_type="engineering_analytics.resolve_commit.sha",
        placeholders=placeholders,
    )
    return [_to_match(row) for row in (response.results or [])]


def _resolve_by_branch(
    *, curated: CuratedGitHubSource, branch: str, repo_owner: str | None, repo_name: str | None
) -> list[CommitPRMatch]:
    placeholders: dict[str, ast.Expr] = {"branch": ast.Constant(value=branch)}
    repo_clause = _repo_clause("pr", repo_owner, repo_name, placeholders)
    response = curated.run(
        _BRANCH_SELECT.replace("__PR_SOURCE__", curated.pr_source()).replace("__REPO__", repo_clause),
        query_type="engineering_analytics.resolve_commit.branch",
        placeholders=placeholders,
    )
    return [_to_match(row) for row in (response.results or [])]


def _repo_clause(alias: str, repo_owner: str | None, repo_name: str | None, placeholders: dict[str, ast.Expr]) -> str:
    """Optional 'owner/name' narrowing on the given alias; a no-op filter when no repo was passed."""
    if not (repo_owner and repo_name):
        return ""
    placeholders["repo_owner"] = ast.Constant(value=repo_owner)
    placeholders["repo_name"] = ast.Constant(value=repo_name)
    return f"AND {alias}.repo_owner = {{repo_owner}} AND {alias}.repo_name = {{repo_name}}"


def _to_match(row: tuple) -> CommitPRMatch:
    repo_owner, repo_name, number, title, state = row
    return CommitPRMatch(
        repo=f"{repo_owner}/{repo_name}",
        number=int(number),
        # LEFT JOIN misses (and the '' state default) come back null/empty — normalize to None.
        title=title or None,
        state=state or None,
    )
