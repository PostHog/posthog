"""Mobile push notifications for inbox reports.

Two events reach the PostHog mobile app: a report first surfaces with the person as a suggested
reviewer, and a report's pull request becomes ready for review. Both use the Expo sender and the
feature flag of the task-run pushes in `products.tasks.backend.push_dispatcher`, so one flag turns
all mobile pushes on or off for a person.

Recipients resolve on a worker after the triggering write commits, because a report born visible
gets its reviewers later in the same transaction, and the queries must not hold up a summary
activity or a pull request webhook. Best effort throughout: a push failure never fails the report
transition or the pull request sync that triggered it.
"""

from __future__ import annotations

from collections.abc import Collection

from django.db import transaction

import structlog
import posthoganalytics

from posthog.models.user import User
from posthog.tasks.push_notifications import send_user_push

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.report_claims import get_active_claims, responsible_user
from products.signals.backend.slack_inbox_notifications import resolve_org_suggested_reviewer_user_ids

logger = structlog.get_logger(__name__)

FEATURE_FLAG_KEY = "posthog-code-mobile-push"
REPORT_VISIBLE_TITLE = "New report for you"
PULL_REQUEST_READY_TITLE = "PR ready to review"

# A push for one of these would open a report the inbox no longer lists.
_HIDDEN_STATUSES = (SignalReport.Status.DELETED, SignalReport.Status.SUPPRESSED)


def schedule_report_visible_push(*, team_id: int, report_id: str) -> None:
    """Queue the "new report" push for after the current transaction commits.

    `robust=True` keeps a broker outage from failing the transition that already committed.
    """
    # Function-local because `tasks` imports this module for the task bodies.
    from products.signals.backend.tasks import send_report_visible_push  # noqa: PLC0415

    transaction.on_commit(
        lambda: send_report_visible_push.delay(team_id=team_id, report_id=report_id),
        robust=True,
    )


def schedule_pull_request_ready_push(pull_request: SignalReportPullRequest, *, previous_state: str) -> None:
    """Queue the "PR ready" push when this write moved the pull request into `open`.

    `previous_state` is the state the caller read under its row lock. Only the write that moves the
    pull request into `open` queues the push, because every later writer reads `open` there.
    """
    if previous_state == SignalReportPullRequest.State.OPEN or pull_request.state != SignalReportPullRequest.State.OPEN:
        return

    from products.signals.backend.tasks import send_pull_request_ready_push  # noqa: PLC0415

    team_id = pull_request.team_id
    pull_request_id = str(pull_request.id)
    transaction.on_commit(
        lambda: send_pull_request_ready_push.delay(team_id=team_id, pull_request_id=pull_request_id),
        robust=True,
    )


def notify_report_visible(*, team_id: int, report_id: str) -> list[int]:
    """Push the new report to its suggested reviewers. Returns the user ids a push was queued for.

    A report with no reviewer that resolves to a project member pushes to nobody, rather than to
    the whole team.
    """
    report = (
        SignalReport.objects.filter(team_id=team_id, id=report_id)
        .exclude(status__in=_HIDDEN_STATUSES)
        .select_related("team")
        .first()
    )
    if report is None:
        return []
    reviewer_ids = resolve_org_suggested_reviewer_user_ids(team_id=team_id, report_ids=[str(report.id)]).get(
        str(report.id), set()
    )
    if not reviewer_ids:
        return []
    return _push_report(
        report,
        list(report.team.all_users_with_access().filter(id__in=reviewer_ids).order_by("id")),
        kind="report_visible",
        title=REPORT_VISIBLE_TITLE,
        body=report.title or "Untitled report",
    )


def notify_pull_request_ready(*, team_id: int, pull_request_id: str) -> list[int]:
    """Push a ready pull request to each linked report's claimant and suggested reviewers.

    The claimant is the person who answers for the active claim of any kind, so a report handed to
    the agent pushes the person who started the agent's task.

    A person linked to several reports that share the pull request gets one push, for the oldest
    report. Returns the user ids a push was queued for.
    """
    pull_request = SignalReportPullRequest.objects.for_team(team_id).filter(id=pull_request_id).first()
    # Re-read on the worker, because the pull request can return to draft or get approved between
    # the transition and this task.
    if (
        pull_request is None
        or pull_request.state != SignalReportPullRequest.State.OPEN
        or pull_request.review_decision == SignalReportPullRequest.ReviewDecision.APPROVED
    ):
        return []

    linked_report_ids = SignalReportArtefact.objects.filter(team_id=team_id, pull_request_id=pull_request.id).values(
        "report_id"
    )
    reports = list(
        SignalReport.objects.filter(team_id=team_id, id__in=linked_report_ids)
        .exclude(status__in=_HIDDEN_STATUSES)
        .select_related("team")
        .order_by("created_at", "id")
    )
    if not reports:
        return []
    report_ids = [str(report.id) for report in reports]
    recipients_by_report = resolve_org_suggested_reviewer_user_ids(team_id=team_id, report_ids=report_ids)
    claims = get_active_claims(team_id=team_id, report_ids=report_ids)
    for report in reports:
        recipient_ids = recipients_by_report.setdefault(str(report.id), set())
        claim = claims.get(str(report.id))
        claimant = responsible_user(claim) if claim is not None else None
        if claimant is not None:
            recipient_ids.add(claimant.id)
    all_recipient_ids = set().union(*recipients_by_report.values())
    if not all_recipient_ids:
        return []
    # Calculate access once for the batch, including claimants who may have lost project access.
    users_by_id = {user.id: user for user in reports[0].team.all_users_with_access().filter(id__in=all_recipient_ids)}
    pushed: list[int] = []
    for report in reports:
        recipient_ids = recipients_by_report[str(report.id)] - set(pushed)
        pushed.extend(
            _push_report(
                report,
                [users_by_id[user_id] for user_id in sorted(recipient_ids) if user_id in users_by_id],
                kind="pull_request_ready",
                title=PULL_REQUEST_READY_TITLE,
                body=report.title or f"{pull_request.repository}#{pull_request.number}",
            )
        )
    return pushed


def _push_report(report: SignalReport, users: Collection[User], *, kind: str, title: str, body: str) -> list[int]:
    if not users:
        return []
    data = {
        "type": "report",
        "report_id": str(report.id),
        "project_id": report.team_id,
        "notificationKind": kind,
        "url": f"posthog://inbox/{report.id}",
    }
    pushed: list[int] = []
    for user in users:
        try:
            if not _push_enabled(user):
                continue
            send_user_push.delay(user.id, title, body, data)
            pushed.append(user.id)
        except Exception:
            logger.warning(
                "signals.inbox_push.enqueue_failed",
                team_id=report.team_id,
                report_id=str(report.id),
                user_id=user.id,
                kind=kind,
                exc_info=True,
            )
    return pushed


def _push_enabled(user: User) -> bool:
    try:
        return bool(
            posthoganalytics.feature_enabled(
                FEATURE_FLAG_KEY,
                user.distinct_id or f"user_{user.id}",
                send_feature_flag_events=False,
            )
        )
    except Exception:
        # Fail closed, so a flag service outage cannot turn pushes on for every user.
        logger.warning("signals.inbox_push.flag_check_failed", user_id=user.id, exc_info=True)
        return False
