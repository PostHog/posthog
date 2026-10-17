import json
from urllib.parse import urlencode

from django.utils import timezone

from products.error_tracking.backend.facade.api import (
    count_weekly_active_users,
    count_weekly_exceptions,
    list_new_unassigned_issue_activity,
    list_quiet_issues_assigned_to,
)
from products.error_tracking.backend.facade.contracts import NewIssueActivity

from ...facade.enums import HighlightLabel
from ..highlight_rules import human, short, users, uses_product
from ..highlight_types import Candidate, Context, Found, Source

NEW_CLIENT_ERROR = "{users} saw the new error ‘{issue}’"
NEW_CLIENT_ERROR_DETAIL = "{started} · {share} of active users · No owner"
NEW_SERVER_ERROR = "New server error ‘{issue}’ is {share} of all errors"
NEW_SERVER_ERROR_DETAIL = "{started} · {events} events in the last 7 days · No owner"
ASSIGNED_QUIET_ONE = "Your issue ‘{issue}’ had no events in the last 14 days"
ASSIGNED_QUIET_ONE_DETAIL = "Resolve it if the fix is live"
ASSIGNED_QUIET_MANY = "{n} of your issues had no events in the last 14 days"
AND_MORE = "‘{issue}’ and {n} more"

NEW_ISSUE_CANDIDATES = 50
QUIET_DAYS = 14
QUIET_ISSUES = 500
MIN_CLIENT_USERS = 50
MIN_CLIENT_SHARE = 0.002
MIN_SERVER_SHARE = 0.02


def find(context: Context) -> Found:
    none: list[Candidate] = []
    new = context.guard("errors_new", lambda: _new_errors(context), none)
    quiet = context.guard("errors_quiet", lambda: _quiet_assigned(context), none)
    return Found(items=(*new, *quiet))


def _issue_name(name: str | None, description: str | None) -> str:
    return f"{name or 'Issue'}: {description}" if description else name or "Issue"


def _new_errors(context: Context) -> list[Candidate]:
    issues = list_new_unassigned_issue_activity(context.team, context.user, limit=NEW_ISSUE_CANDIDATES)
    if not issues:
        return []
    active_users = 0
    if any(_is_client(issue) for issue in issues):
        active_users = context.guard(
            "errors_active_users",
            lambda: context.daily("weekly_active_users", lambda: count_weekly_active_users(context.team, context.user)),
            0,
        )
    exceptions = 0
    if any(_is_server(issue) for issue in issues):
        exceptions = context.guard(
            "errors_weekly_exceptions", lambda: count_weekly_exceptions(context.team, context.user), 0
        )
    relevant = uses_product(context, "Error tracking")
    candidates = [_new_error(context, issue, exceptions, active_users, relevant) for issue in issues]
    return [candidate for candidate in candidates if candidate is not None]


def _is_client(issue: NewIssueActivity) -> bool:
    return issue.client_share >= 0.8 and issue.users >= MIN_CLIENT_USERS


def _is_server(issue: NewIssueActivity) -> bool:
    return issue.client_share < 0.2


def _new_error(
    context: Context, issue: NewIssueActivity, exceptions: int, active_users: int, relevant: bool
) -> Candidate | None:
    name = short(_issue_name(issue.name, issue.description))
    started = f"Since {timezone.localtime(issue.first_seen, context.team.timezone_info).strftime('%b %-d')}"
    if _is_client(issue) and issue.users <= active_users:
        share = issue.users / active_users
        if share < MIN_CLIENT_SHARE:
            return None
        importance = min(1.0, 0.5 + share / 0.02)
        title = NEW_CLIENT_ERROR.format(issue=name, users=users(issue.users))
        detail = NEW_CLIENT_ERROR_DETAIL.format(started=started, share=f"{share * 100:.1f}%")
    elif _is_server(issue) and exceptions:
        share = issue.occurrences / exceptions
        if share < MIN_SERVER_SHARE:
            return None
        importance = min(1.0, 0.4 + share / 0.1)
        title = NEW_SERVER_ERROR.format(issue=name, share=f"{share * 100:.0f}%")
        detail = NEW_SERVER_ERROR_DETAIL.format(started=started, events=human(issue.occurrences))
    else:
        return None
    if not relevant and importance < 0.9:
        return None
    return Candidate(
        key=f"new_error:{issue.id}",
        label=HighlightLabel.RISK,
        family="errors",
        importance=importance,
        relevance=1.0 if relevant else 0.0,
        title=title,
        detail=detail,
        url=f"/error_tracking/{issue.id}",
        ref=str(issue.id),
    )


def _assigned_issues_url(context: Context) -> str:
    query = {
        "assignee": json.dumps({"id": context.user.id, "type": "user"}),
        "status": "active",
        "dateRange": json.dumps({"date_from": "all"}),
    }
    return f"/error_tracking?{urlencode(query)}"


def _quiet_assigned(context: Context) -> list[Candidate]:
    issues = list_quiet_issues_assigned_to(context.team, context.user, quiet_days=QUIET_DAYS, limit=QUIET_ISSUES)
    if not issues:
        return []
    name = short(_issue_name(issues[0].name, issues[0].description), 50)
    one = len(issues) == 1
    return [
        Candidate(
            key="assigned_quiet",
            label=HighlightLabel.OPPORTUNITY,
            family="errors",
            importance=0.35,
            relevance=1.0,
            title=ASSIGNED_QUIET_ONE.format(issue=name) if one else ASSIGNED_QUIET_MANY.format(n=len(issues)),
            detail=ASSIGNED_QUIET_ONE_DETAIL if one else AND_MORE.format(issue=name, n=len(issues) - 1),
            url=f"/error_tracking/{issues[0].id}" if one else _assigned_issues_url(context),
        )
    ]


SOURCE = Source(name="errors", find=find, scopes=("error_tracking:read",))
