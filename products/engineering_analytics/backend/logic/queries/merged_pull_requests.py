"""Curated query: pull requests merged since a cutoff, with their branch-tip head SHA.

The discovery seam behind ReviewHog telemetry — "which PRs merged recently, and the commit at each
branch tip". Embeds the curated pull-requests source (see ``logic.views.pull_requests``) as a
subquery and keeps only PRs that have merged (``merged_at`` is non-null exactly when a PR actually
merged — the same condition the source derives ``state = 'merged'`` from) at or after ``since``,
carry a branch-tip SHA (a malformed snapshot without one is excluded, never surfaced empty), scoped
to a single ``owner/name`` repository, newest merge first.

``head_sha`` is the run / branch-tip SHA (``head.sha``), never the ephemeral ``refs/pull/N/merge``
commit (SPEC §7). Repo matching is case-insensitive, like ``resolve_branch``: the curated repo
identity comes from ``base.repo.full_name`` and the caller's slug need not match GitHub's casing.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import MergedPullRequest
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# HogQL applies a default 100-row limit when a query names none, silently truncating the result; set
# an explicit ceiling so the recency-bounded set isn't capped at an arbitrary 100. In a repo merging
# more than this many PRs inside the window, the ceiling drops the oldest merges — callers that need
# specific PRs pass ``numbers`` so the result is bounded by their ask instead.
_LIMIT = 1000

_SELECT = f"""
    SELECT
        pr.number AS number,
        pr.head_sha AS head_sha,
        pr.merged_at AS merged_at
    FROM __PR_SOURCE__ AS pr
    WHERE pr.merged_at IS NOT NULL
        AND pr.merged_at >= {{since}}
        -- head_sha is raw JSONExtractString over the Nullable `head` blob: NULL when the blob is
        -- NULL, '' when the JSON lacks 'sha'. Either way the row is useless to this read (callers
        -- feed the SHA to a GitHub compare) and a NULL would fail MergedPullRequest's non-null
        -- contract for the whole batch — exclude it so the contract holds by construction.
        AND ifNull(pr.head_sha, '') != ''
        AND lower(pr.repo_owner) = {{repo_owner}}
        AND lower(pr.repo_name) = {{repo_name}}
        __NUMBERS_FILTER__
    ORDER BY pr.merged_at DESC
    LIMIT {_LIMIT}
"""


def query_merged_pull_requests(
    *, curated: CuratedGitHubSource, repo_owner: str, repo_name: str, since: datetime, numbers: list[int] | None = None
) -> list[MergedPullRequest]:
    placeholders: dict[str, ast.Expr] = {
        "since": ast.Constant(value=since),
        "repo_owner": ast.Constant(value=repo_owner.lower()),
        "repo_name": ast.Constant(value=repo_name.lower()),
    }
    numbers_filter = ""
    if numbers is not None:
        numbers_filter = "AND pr.number IN {numbers}"
        placeholders["numbers"] = ast.Constant(value=numbers)
    response = curated.run(
        _SELECT.replace("__PR_SOURCE__", curated.pr_source()).replace("__NUMBERS_FILTER__", numbers_filter),
        query_type="engineering_analytics.merged_pull_requests",
        placeholders=placeholders,
    )
    return [_to_merged_pr(row) for row in (response.results or [])]


def _to_merged_pr(row: tuple) -> MergedPullRequest:
    number, head_sha, merged_at = row
    return MergedPullRequest(number=int(number), head_sha=head_sha, merged_at=merged_at)
