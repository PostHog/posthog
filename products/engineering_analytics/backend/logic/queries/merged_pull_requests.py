"""Curated query: pull requests merged since a cutoff, with their branch-tip head SHA.

The discovery seam behind ReviewHog telemetry — "which PRs merged recently, and the commit at each
branch tip". Embeds the curated pull-requests source (see ``logic.views.pull_requests``) as a
subquery and keeps only PRs that have merged (``merged_at`` is non-null exactly when a PR actually
merged — the same condition the source derives ``state = 'merged'`` from) at or after ``since``,
scoped to a single ``owner/name`` repository, newest merge first.

``head_sha`` is the run / branch-tip SHA (``head.sha``), never the ephemeral ``refs/pull/N/merge``
commit (SPEC §7). Repo matching is case-insensitive, like ``resolve_branch``: the curated repo
identity comes from ``base.repo.full_name`` and the caller's slug need not match GitHub's casing.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import MergedPullRequest
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# HogQL applies a default 100-row limit when a query names none, silently truncating the result; set
# an explicit ceiling so the recency-bounded set isn't capped at an arbitrary 100 (the caller's
# ``since`` is the real bound).
_LIMIT = 1000

_SELECT = f"""
    SELECT
        pr.number AS number,
        pr.head_sha AS head_sha,
        pr.merged_at AS merged_at
    FROM __PR_SOURCE__ AS pr
    WHERE pr.merged_at IS NOT NULL
        AND pr.merged_at >= {{since}}
        AND lower(pr.repo_owner) = {{repo_owner}}
        AND lower(pr.repo_name) = {{repo_name}}
    ORDER BY pr.merged_at DESC
    LIMIT {_LIMIT}
"""


def build_merged_pull_requests(*, curated: CuratedGitHubSource, repo: str, since: datetime) -> list[MergedPullRequest]:
    owner, _, name = repo.partition("/")
    # A half-specified repo (bare org, trailing/leading slash) would silently drop the scope and
    # return merges from every repo in the source — fail loudly instead.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    placeholders: dict[str, ast.Expr] = {
        "since": ast.Constant(value=since),
        "repo_owner": ast.Constant(value=owner.lower()),
        "repo_name": ast.Constant(value=name.lower()),
    }
    response = curated.run(
        _SELECT.replace("__PR_SOURCE__", curated.pr_source()),
        query_type="engineering_analytics.merged_pull_requests",
        placeholders=placeholders,
    )
    return [_to_merged_pr(row) for row in (response.results or [])]


def _to_merged_pr(row: tuple) -> MergedPullRequest:
    number, head_sha, merged_at = row
    return MergedPullRequest(number=int(number), head_sha=head_sha, merged_at=merged_at)
