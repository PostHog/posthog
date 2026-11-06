"""Delivery orchestration: a scope's delivery summary, its pull request timelines, and an author's
comparison with their team.

The summary and the timelines take one scope (see ``delivery_scope``) and compare it with the
repository. The author page is the first caller; a team page reads the same summary with a GitHub
team, and a pull request page reads one timeline and the comparison.
"""

from products.engineering_analytics.backend.facade.contracts import (
    DeliveryComparison,
    DeliveryScopeKind,
    DeliverySummary,
    PullRequestTimelines,
)
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.delivery_scope import DeliveryScope, SummaryScope
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.delivery_comparison import query_delivery_comparison
from products.engineering_analytics.backend.logic.queries.delivery_summary import query_delivery_summary
from products.engineering_analytics.backend.logic.queries.pull_request_timelines import query_pull_request_timelines


def build_delivery_summary(
    *,
    curated: CuratedGitHubSource,
    scope: SummaryScope,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DeliverySummary:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_delivery_summary(curated=curated, scope=scope, date_from=parsed_from, date_to=parsed_to)


def build_pull_request_timelines(
    *,
    curated: CuratedGitHubSource,
    scope: DeliveryScope,
    date_from: str | None = None,
    date_to: str | None = None,
) -> PullRequestTimelines:
    # A single pull request is shown whatever its age, so neither end of the window applies to it.
    single_pr = scope.kind == DeliveryScopeKind.PULL_REQUEST
    window_from = None if single_pr else date_from
    window_to = None if single_pr else date_to
    parsed_from, parsed_to = _parse_window(curated.team, window_from, window_to, default=_DEFAULT_WINDOW)
    return query_pull_request_timelines(curated=curated, scope=scope, date_from=parsed_from, date_to=parsed_to)


def build_delivery_comparison(
    *,
    curated: CuratedGitHubSource,
    author: str,
    focus_pr: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DeliveryComparison:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_delivery_comparison(
        curated=curated, author=author, focus_pr=focus_pr, date_from=parsed_from, date_to=parsed_to
    )
