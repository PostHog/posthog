from __future__ import annotations

from typing import TypedDict

from django.conf import settings

import structlog
import posthoganalytics

from posthog.models import Team, User
from posthog.sync import database_sync_to_async

from products.signals.backend.cursor_dispatch import (
    SIGNALS_CURSOR_DISPATCH_FLAG,
    CursorDispatchError,
    dispatch_report_to_cursor,
    resolve_cursor_api_key,
)
from products.signals.backend.models import (
    CodingAgent,
    SignalReport,
    SignalReportTask,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
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


def _cursor_flag_enabled(distinct_id: str | None, organization_id: str) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            SIGNALS_CURSOR_DISPATCH_FLAG,
            str(distinct_id),
            groups={"organization": organization_id},
            send_feature_flag_events=False,
        )
    )


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

    # Single query: fetch users who have an autonomy config, joined eagerly
    users_with_config = {
        u.id: u
        for u in User.objects.filter(
            id__in=candidate_user_ids,
            signal_autonomy_config__isnull=False,
            teams__id=team_id,
        ).select_related("signal_autonomy_config")
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


def start_internal_implementation_task(
    *,
    team: Team,
    report_id: str,
    title: str,
    summary: str,
    repository: str,
    assignee: User,
    priority: PriorityAssessment | None = None,
) -> Task:
    """Create and run an internal implementation Task (the PostHog Code runner) for a report.

    Shared by the autonomy auto-start path and the manual dispatch endpoint so both produce
    an identical Task + SignalReportTask(IMPLEMENTATION) link, surfaced via implementation-PR tracking.
    """
    task = Task.create_and_run(
        team=team,
        title=title,
        description=_build_autostart_task_description(
            report_id=report_id, summary=summary, repository=repository, priority=priority
        ),
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        user_id=assignee.id,
        repository=repository,
        signal_report_id=report_id,
        posthog_mcp_scopes="read_only",
        interaction_origin="signal_report",  # Makes the agent auto-push and open a draft PR
    )
    task_run = task.runs.order_by("-created_at").first()
    if task_run is None:
        raise RuntimeError(f"Task {task.id} started without producing a TaskRun")

    SignalReportTask.objects.create(
        team_id=team.id,
        report_id=report_id,
        task=task,
        relationship=SignalReportTask.Relationship.IMPLEMENTATION,
    )
    return task


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

    # Route by the team's chosen agent, NOT by Cursor connection state. Cursor being connected
    # must not silently redirect autonomy — a team only routes to Cursor once it sets the default.
    team_default_agent = team_config.default_coding_agent if team_config else CodingAgent.POSTHOG_CODE
    if team_default_agent == CodingAgent.CURSOR and _cursor_flag_enabled(
        task_user.distinct_id, str(team.organization_id)
    ):
        cursor_api_key = await database_sync_to_async(resolve_cursor_api_key, thread_sensitive=False)(team)
        if cursor_api_key:
            report = await SignalReport.objects.aget(id=report_id)
            try:
                # No SignalReportTask is created for the Cursor path: its `task` FK requires an
                # internal Task. Dedup is handled by Cursor returning 409 on a duplicate agentId,
                # which dispatch_report_to_cursor treats as already_dispatched.
                await database_sync_to_async(dispatch_report_to_cursor, thread_sensitive=False)(
                    report, api_key=cursor_api_key, site_url=settings.SITE_URL
                )
            except CursorDispatchError as error:
                logger.warning(
                    "signals auto-start cursor dispatch failed",
                    report_id=report_id,
                    team_id=team_id,
                    repository=repository,
                    error=str(error),
                )
            return
        logger.warning(
            "signals auto-start defaulted to cursor but no key resolved; falling back to internal",
            report_id=report_id,
            team_id=team_id,
        )

    await database_sync_to_async(start_internal_implementation_task, thread_sensitive=False)(
        team=team,
        report_id=report_id,
        title=title,
        summary=summary,
        repository=repository,
        assignee=task_user,
        priority=priority,
    )
