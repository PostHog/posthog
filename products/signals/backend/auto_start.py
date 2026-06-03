from __future__ import annotations

from typing import TypedDict

import structlog

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReportTask, SignalTeamConfig, SignalUserAutonomyConfig
from products.signals.backend.report_generation.research import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
)
from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users
from products.signals.backend.slack_inbox_notifications import POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME
from products.tasks.backend.models import Task

logger = structlog.get_logger(__name__)


class ReviewerContent(TypedDict):
    github_login: str
    github_name: str | None
    relevant_commits: list[dict]


_PRIORITY_RANK: dict[Priority, int] = {
    Priority.P0: 0,
    Priority.P1: 1,
    Priority.P2: 2,
    Priority.P3: 3,
    Priority.P4: 4,
}


def _priority_rank(priority: Priority) -> int:
    return _PRIORITY_RANK[priority]


def _build_autostart_task_description(
    *, report_id: str, summary: str, repository: str, priority: PriorityAssessment | None
) -> str:
    priority_line = f"Priority: {priority.priority.value}\nReason: {priority.explanation}\n\n" if priority else ""
    report_deep_link = f"{POSTHOG_CODE_INBOX_DEEP_LINK_SCHEME}://inbox/{report_id}"
    return (
        f"{summary}\n\n"
        f"{priority_line}"
        f"Repository: {repository}\n\n"
        "Act on this signal report. Investigate the root cause, implement the fix, and open a PR if appropriate.\n\n"
        "When opening the PR, include this report deep link in the description footer, "
        "making the footer '*Created with [PostHog Code](https://posthog.com/code?ref=pr) "
        f"from [an inbox report]({report_deep_link}).' - "
        "so the human reviewer can jump straight to it."
    )


def _resolve_autostart_assignee(
    team_id: int,
    report_priority: Priority,
    reviewers_content: list[ReviewerContent],
    team_default_priority: Priority,
) -> User | None:
    """Return the first suggested reviewer whose effective priority threshold allows auto-start.

    Walks *reviewers_content* in order (most relevant first). For each reviewer
    that maps to an org member with an autonomy config, resolves their effective
    threshold (personal setting, falling back to the team default) and checks
    whether the report's priority is high enough (lower rank = higher priority).
    Returns the first matching ``User``, or ``None`` if nobody qualifies.
    """
    login_to_user = resolve_org_github_login_to_users(
        team_id, (str(r["github_login"]) for r in reviewers_content if r.get("github_login"))
    )
    report_rank = _priority_rank(report_priority)

    # Map reviewer github logins to user IDs (preserving reviewer order)
    candidate_user_ids: list[int] = []
    for reviewer in reviewers_content:
        login = reviewer.get("github_login")
        if not login:
            continue
        login = login.lower()
        candidate = login_to_user.get(login)
        if isinstance(candidate, User):
            candidate_user_ids.append(candidate.id)

    if not candidate_user_ids:
        return None

    # Single query: fetch users who have an autonomy config, joined eagerly.
    # Scope to the team's org via reverse relations — both hops use the explicit
    # singular related_query_name (organization/team), not the related_name accessors
    # (organizations/teams), which Django's filter resolver does not accept.
    users_with_config = {
        u.id: u
        for u in User.objects.filter(
            id__in=candidate_user_ids,
            signal_autonomy_config__isnull=False,
            organization__team=team_id,
        )
        .select_related("signal_autonomy_config")
        .distinct()
    }

    # Walk in reviewer order (most relevant first)
    for uid in candidate_user_ids:
        user = users_with_config.get(uid)
        if user is None:
            continue
        config: SignalUserAutonomyConfig = user.signal_autonomy_config
        effective_threshold = (
            Priority(config.autostart_priority) if config.autostart_priority else team_default_priority
        )
        if report_rank <= _priority_rank(effective_threshold):
            return user

    return None


async def maybe_autostart_implementation_task(
    *,
    team_id: int,
    report_id: str,
    repository: str,
    title: str,
    summary: str,
    actionability: ActionabilityAssessment,
    reviewers_content: list[ReviewerContent],
    priority: PriorityAssessment | None,
) -> None:
    """Start an implementation Task for a SignalReport if autonomy + priority allow it.

    Idempotent: skipped if an IMPLEMENTATION task already exists for the report,
    if the report is not immediately actionable, if it's already addressed, if
    priority is missing, if there are no suggested reviewers, or if no reviewer's
    autonomy threshold is met.

    Both the agentic signals pipeline (``temporal/agentic/report.py``) and the
    custom agent activity (``temporal/custom_agent.py``) call this after persisting
    their report and artefacts. Callers should wrap this in try/except so an
    autostart failure does not fail the report itself.
    """
    task_exists = await SignalReportTask.objects.filter(
        team_id=team_id, report_id=report_id, relationship=SignalReportTask.Relationship.IMPLEMENTATION
    ).aexists()
    if (
        actionability.actionability != ActionabilityChoice.IMMEDIATELY_ACTIONABLE
        or actionability.already_addressed
        or priority is None
        or not reviewers_content
        or task_exists
    ):
        return

    team = await Team.objects.select_related("organization").aget(id=team_id)
    team_config = await SignalTeamConfig.objects.filter(team_id=team_id).afirst()
    team_default_priority = Priority(team_config.default_autostart_priority) if team_config else Priority.P0

    task_user = await database_sync_to_async(_resolve_autostart_assignee, thread_sensitive=False)(
        team_id, priority.priority, reviewers_content, team_default_priority
    )
    if task_user is None:
        return

    task = await database_sync_to_async(Task.create_and_run, thread_sensitive=False)(
        team=team,
        title=title,
        description=_build_autostart_task_description(
            report_id=report_id, summary=summary, repository=repository, priority=priority
        ),
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        user_id=task_user.id,
        repository=repository,
        signal_report_id=report_id,
        posthog_mcp_scopes="read_only",
        interaction_origin="signal_report",  # Makes the agent auto-push and open a draft PR
    )
    task_run = await task.runs.order_by("-created_at").afirst()
    if task_run is None:
        raise RuntimeError(f"Task {task.id} auto-started without producing a TaskRun")

    await SignalReportTask.objects.acreate(
        team_id=team_id,
        report_id=report_id,
        task=task,
        relationship=SignalReportTask.Relationship.IMPLEMENTATION,
    )
