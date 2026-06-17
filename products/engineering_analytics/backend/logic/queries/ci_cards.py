"""Curated query: headline counts for the open-PR backlog.

Open PRs joined to their head-SHA CI rollup, collapsed into four counts. ``stuck``
is a fixed rule (open, non-draft, non-bot, older than 7 days), so there is no
window parameter.
"""

from products.engineering_analytics.backend.facade.contracts import CICardSummary
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_EMPTY = CICardSummary(open_prs=0, repos=0, stuck=0, failing_ci=0)

_SELECT = """
    SELECT
        countIf(pr.state = 'open') AS open_prs,
        count(DISTINCT if(pr.state = 'open', concat(pr.repo_owner, '/', pr.repo_name), NULL)) AS repos,
        countIf(
            pr.state = 'open' AND NOT pr.is_draft AND NOT pr.is_bot AND pr.created_at < now() - INTERVAL 7 DAY
        ) AS stuck,
        countIf(pr.state = 'open' AND coalesce(ci.failing, 0) > 0) AS failing_ci
    FROM __PR_SOURCE__ AS pr
    LEFT JOIN ci_rollup AS ci ON ci.head_sha = pr.head_sha
"""


def query_ci_cards(*, curated: CuratedGitHubSource) -> CICardSummary:
    response = curated.run(curated.pr_rollup_query(_SELECT), query_type="engineering_analytics.ci_cards")
    if not response.results:
        return _EMPTY
    open_prs, repos, stuck, failing_ci = response.results[0]
    return CICardSummary(open_prs=open_prs, repos=repos, stuck=stuck, failing_ci=failing_ci)
