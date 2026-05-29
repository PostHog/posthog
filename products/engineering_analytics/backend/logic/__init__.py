"""Orchestration for engineering_analytics.

Resolves caller inputs (relative date strings, ``owner/name`` repo strings) into
the concrete values the query layer needs, runs the queries, and wraps the rows
into contract types stamped with their ``metric_quality``. GitHub-shaped columns
never reach here — that is the query layer's job.
"""

from datetime import datetime

from django.utils import timezone as django_timezone

from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.engineering_analytics.backend.facade.contracts import PRLifecycle, RepoRef, TimeToMerge, WorkflowReport
from products.engineering_analytics.backend.logic.queries.pull_requests import query_pr_lifecycle, query_time_to_merge
from products.engineering_analytics.backend.logic.queries.workflow_runs import query_workflow_report

# PullRequest.repo is required, but v1 warehouse rows carry no repo identity.
# When the caller doesn't name a repo we echo this neutral ref rather than invent one.
_FALLBACK_REPO = RepoRef(provider="github", owner="", name="")


def build_workflow_report(
    *,
    team: Team,
    date_from: str,
    date_to: str | None,
    repo: str | None,
) -> WorkflowReport:
    start, end = _resolve_window(team, date_from, date_to)
    rows = query_workflow_report(team=team, date_from=start, date_to=end)
    return WorkflowReport(rows=rows, date_from=date_from, date_to=date_to, repo=_resolve_repo_ref(repo))


def build_time_to_merge(
    *,
    team: Team,
    date_from: str,
    date_to: str | None,
    repo: str | None,
    group_by_author: bool,
) -> TimeToMerge:
    start, end = _resolve_window(team, date_from, date_to)
    rows = query_time_to_merge(team=team, date_from=start, date_to=end, group_by_author=group_by_author)
    return TimeToMerge(
        rows=rows,
        date_from=date_from,
        date_to=date_to,
        repo=_resolve_repo_ref(repo),
        group_by_author=group_by_author,
    )


def build_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str | None,
) -> PRLifecycle | None:
    repo_ref = _resolve_repo_ref(repo) or _FALLBACK_REPO
    return query_pr_lifecycle(team=team, pr_number=pr_number, repo_ref=repo_ref)


def _resolve_window(team: Team, date_from: str, date_to: str | None) -> tuple[datetime, datetime]:
    now = django_timezone.now()
    start = relative_date_parse(date_from, team.timezone_info, now=now)
    end = relative_date_parse(date_to, team.timezone_info, now=now) if date_to else now
    return start, end


def _resolve_repo_ref(repo: str | None) -> RepoRef | None:
    # v1 dogfoods a single repo and the warehouse rows carry no repo column, so
    # this only populates the echoed RepoRef — it does not filter rows yet.
    if not repo:
        return None
    owner, _, name = repo.partition("/")
    return RepoRef(provider="github", owner=owner, name=name)
