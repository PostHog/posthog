"""Headline counts for the open-PR backlog. They describe current state, so they take no window."""

from products.engineering_analytics.backend.facade.contracts import CICardSummary
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource

_EMPTY = CICardSummary(open_prs=0, repos=0, stuck=0, failing_ci=0)

# query_ci_cards scopes the CI rollup to this predicate, so every _SELECT metric must be gated on it.
OPEN_PR_SQL = "state = 'open'"
FAILING_CI_SQL = "coalesce(ci.failing, 0) > 0"


def stuck_pr_sql(prefix: str) -> str:
    return (
        f"{prefix}{OPEN_PR_SQL} AND NOT {prefix}is_draft AND NOT {prefix}is_bot "
        f"AND {prefix}created_at < now() - INTERVAL 7 DAY"
    )


_SELECT = f"""
    SELECT
        countIf(pr.{OPEN_PR_SQL}) AS open_prs,
        count(DISTINCT if(pr.{OPEN_PR_SQL}, concat(pr.repo_owner, '/', pr.repo_name), NULL)) AS repos,
        countIf({stuck_pr_sql("pr.")}) AS stuck,
        countIf(pr.{OPEN_PR_SQL} AND {FAILING_CI_SQL}) AS failing_ci
    FROM __PR_SOURCE__ AS pr
    LEFT JOIN ci_rollup AS ci ON ci.head_sha = pr.head_sha
"""


def query_ci_cards(*, curated: CuratedGitHubSource) -> CICardSummary:
    response = curated.run(
        curated.pr_rollup_query(_SELECT, pr_scope_where=OPEN_PR_SQL),
        query_type="engineering_analytics.ci_cards",
    )
    if not response.results:
        return _EMPTY
    open_prs, repos, stuck, failing_ci = response.results[0]
    return CICardSummary(open_prs=open_prs, repos=repos, stuck=stuck, failing_ci=failing_ci)
