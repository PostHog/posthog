"""Orchestration for engineering_analytics.

Resolves caller inputs (PostHog-convention date strings, ``owner/name`` repo) and binds the
team to its curated GitHub read layer (``CuratedGitHubSource``, which resolves the warehouse
table names), then returns canonical contract types. The curated query builders
(``backend/logic/views``) own all GitHub-shaped mapping and domain rules; this layer deals
only in canonical types.
"""

from datetime import datetime

from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    PRLifecycle,
    PullRequestList,
    WorkflowHealthItem,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.ci_cards import query_ci_cards
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health

# Default recency window when a caller omits date_from. Relative strings (-30d) and
# ISO8601 are both accepted and resolved against the team's timezone.
_DEFAULT_WINDOW = "-30d"

# workflow_health zero-fills one daily entry per workflow per day in the window, so an
# unbounded range would materialize an enormous response. A year is plenty for trends.
_MAX_WINDOW_DAYS = 366


# Inputs are validated before the GitHub source is resolved, so a bad date or malformed
# repo fails with its own clear error rather than being masked by the no-source error.
# CuratedGitHubSource.for_team resolves the warehouse tables exactly once per request.
def build_pr_lifecycle(
    *, team: Team, pr_number: int, repo: str | None, source_id: str | None = None
) -> PRLifecycle | None:
    owner, name = _split_repo(repo)
    curated = CuratedGitHubSource.for_team(team, source_id=source_id)
    return query_pr_lifecycle(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_ci_cards(*, team: Team, source_id: str | None = None) -> CICardSummary:
    return query_ci_cards(curated=CuratedGitHubSource.for_team(team, source_id=source_id))


def build_pull_request_list(
    *, team: Team, date_from: str | None = None, source_id: str | None = None
) -> PullRequestList:
    parsed_from = _parse_date(team, date_from or _DEFAULT_WINDOW)
    return query_pull_request_list(
        curated=CuratedGitHubSource.for_team(team, source_id=source_id), date_from=parsed_from
    )


def build_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
) -> list[WorkflowHealthItem]:
    parsed_from = _parse_date(team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    curated = CuratedGitHubSource.for_team(team, source_id=source_id)
    return query_workflow_health(curated=curated, date_from=parsed_from, date_to=parsed_to)


def _parse_date(team: Team, value: str) -> datetime:
    return relative_date_parse(value, team.timezone_info)


def _split_repo(repo: str | None) -> tuple[str | None, str | None]:
    if not repo:
        return None, None
    owner, _, name = repo.partition("/")
    # A half-specified repo (bare org, trailing/leading slash) would otherwise drop
    # the filter silently and return a PR from the wrong repo — fail loudly instead.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return owner, name
