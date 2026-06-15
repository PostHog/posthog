"""Orchestration for engineering_analytics.

Resolves caller inputs (PostHog-convention date strings, ``owner/name`` repo) and the
team's GitHub warehouse table names (``logic.sources``) into the values the query layer
needs, then returns canonical contract types. The curated query builders
(``backend/logic/views``) own all GitHub-shaped mapping and domain rules; this layer
deals only in canonical types.
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
from products.engineering_analytics.backend.logic.queries.ci_cards import query_ci_cards
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health
from products.engineering_analytics.backend.logic.sources import resolve_github_tables

# Default recency window when a caller omits date_from. Relative strings (-30d) and
# ISO8601 are both accepted and resolved against the team's timezone.
_DEFAULT_WINDOW = "-30d"

# workflow_health zero-fills one daily entry per workflow per day in the window, so an
# unbounded range would materialize an enormous response. A year is plenty for trends.
_MAX_WINDOW_DAYS = 366


# Inputs are validated before the warehouse tables are resolved, so a bad date or
# malformed repo fails with its own clear error rather than being masked by the
# no-source error. The tables are resolved exactly once per request and passed down.
def build_pr_lifecycle(*, team: Team, pr_number: int, repo: str | None) -> PRLifecycle | None:
    owner, name = _split_repo(repo)
    tables = resolve_github_tables(team=team)
    return query_pr_lifecycle(team=team, tables=tables, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_ci_cards(*, team: Team) -> CICardSummary:
    tables = resolve_github_tables(team=team)
    return query_ci_cards(team=team, tables=tables)


def build_pull_request_list(*, team: Team, date_from: str | None = None) -> PullRequestList:
    parsed_from = _parse_date(team, date_from or _DEFAULT_WINDOW)
    tables = resolve_github_tables(team=team)
    return query_pull_request_list(team=team, tables=tables, date_from=parsed_from)


def build_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[WorkflowHealthItem]:
    parsed_from = _parse_date(team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    tables = resolve_github_tables(team=team)
    return query_workflow_health(team=team, tables=tables, date_from=parsed_from, date_to=parsed_to)


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
