"""Curated query: merged pull requests of one repository with their head SHA, newest merge first.

``since`` and ``numbers`` are alternatives: named PR numbers are returned whatever their merge date.
``head_sha`` is the branch-tip SHA (``head.sha``), never the ``refs/pull/N/merge`` commit.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import MergedPullRequest
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

# HogQL applies a default 100-row limit when a query names none. Past this ceiling the oldest merges
# are dropped, so a caller that needs specific PRs passes ``numbers``.
_LIMIT = 1000

_SELECT = f"""
    SELECT
        pr.number AS number,
        pr.head_sha AS head_sha,
        pr.merged_at AS merged_at
    FROM __PR_SOURCE__ AS pr
    WHERE pr.merged_at IS NOT NULL
        __SINCE_FILTER__
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
    *,
    curated: CuratedGitHubSource,
    repo_owner: str,
    repo_name: str,
    since: datetime | None = None,
    numbers: list[int] | None = None,
) -> list[MergedPullRequest]:
    if since is None and numbers is None:
        raise ValueError("query_merged_pull_requests needs either `since` or `numbers` to bound the read")
    placeholders: dict[str, ast.Expr] = {
        "repo_owner": ast.Constant(value=repo_owner.lower()),
        "repo_name": ast.Constant(value=repo_name.lower()),
    }
    # A by-number read ignores `since`, because `since` could only drop rows the caller named, and
    # the caller cannot tell that loss apart from a PR that never merged.
    since_filter = ""
    numbers_filter = ""
    if numbers is None:
        since_filter = "AND pr.merged_at >= {since}"
        placeholders["since"] = ast.Constant(value=since)
    else:
        numbers_filter = "AND pr.number IN {numbers}"
        placeholders["numbers"] = ast.Constant(value=numbers)
    response = curated.run(
        _SELECT.replace("__PR_SOURCE__", curated.pr_source())
        .replace("__SINCE_FILTER__", since_filter)
        .replace("__NUMBERS_FILTER__", numbers_filter),
        query_type="engineering_analytics.merged_pull_requests",
        placeholders=placeholders,
    )
    return [_to_merged_pr(row) for row in (response.results or [])]


def _to_merged_pr(row: tuple) -> MergedPullRequest:
    number, head_sha, merged_at = row
    return MergedPullRequest(number=int(number), head_sha=head_sha, merged_at=merged_at)
