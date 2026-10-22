"""Mobile push notifications for inbox reports.

Reports notify when first visible to a suggested reviewer, when their pull requests become ready
for review, and at meaningful milestones of implementation or research work. Report pushes use the
Expo sender and the `posthog-code-mobile-push` feature flag. Task notification preferences and
source eligibility apply independently; ordinary task pushes do not require the report feature flag.

Recipients resolve on a worker after the triggering write commits, because a report born visible
gets its reviewers later in the same transaction, and the queries must not hold up a summary
activity or a pull request webhook. Best effort throughout: a push failure never fails the report
transition or the pull request sync that triggered it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q

import structlog
import posthoganalytics

from posthog.models.user import User
from posthog.push_notifications import MobilePushCategory, mobile_push_preference_enabled
from posthog.tasks.push_notifications import send_user_push

from products.signals.backend.artefact_schemas import (
    SIGNALS_PRODUCT,
    TASK_RUN_TYPE_IMPLEMENTATION,
    TASK_RUN_TYPE_RESEARCH,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_claims import get_active_claims, responsible_user
from products.signals.backend.scout_authorship import report_is_hidden_from_inbox
from products.signals.backend.slack_inbox_notifications import resolve_org_suggested_reviewer_user_ids
from products.tasks.backend.facade.api import (
    claim_mobile_push_cooldown,
    enqueue_task_mobile_pr_outcome,
    release_mobile_push_cooldown,
    task_mobile_push_suppressed_token_ids,
    task_mobile_push_user_ids,
)

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun

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
                dedupe_subject=f"pull_request:{pull_request.id}:ready",
                pull_request_id=str(pull_request.id),
            )
        )
    return pushed


def notify_report_task_update(
    *,
    task_run: TaskRun,
    kind: str,
    pull_request_url: str | None = None,
    on_enqueued: Callable[[], None] | None = None,
) -> bool:
    """Route meaningful milestones of actual report work through report preferences and links."""
    task = task_run.task
    reports = list(
        SignalReport.objects.filter(team_id=task.team_id)
        .filter(Q(id=task.signal_report_id) | SignalReport.reports_for_task_ids_filter([task.id], team_id=task.team_id))
        .select_related("team")
        .order_by("created_at", "id")
    )
    task_runs = SignalReport.associated_task_runs_for_reports(
        report_ids=[str(report.id) for report in reports], team_id=task.team_id
    )
    reports = [
        report
        for report in reports
        if any(
            run.task_id == str(task.id)
            and run.product == SIGNALS_PRODUCT
            and run.type in {TASK_RUN_TYPE_IMPLEMENTATION, TASK_RUN_TYPE_RESEARCH}
            for run in task_runs.get(str(report.id), [])
        )
    ]
    if not reports:
        return False
    if task.is_scout_experiment:
        return True
    report_ids = [str(report.id) for report in reports]
    reviewers = resolve_org_suggested_reviewer_user_ids(team_id=task.team_id, report_ids=report_ids)
    claims = get_active_claims(team_id=task.team_id, report_ids=report_ids)
    mobile_recipient_ids = task_mobile_push_user_ids(task_id=str(task.id), team_id=task.team_id)
    pushed: set[int] = set()
    for report in reports:
        if report.status in _HIDDEN_STATUSES or report.first_visible_at is None:
            continue
        recipient_ids = reviewers.get(str(report.id), set()) | mobile_recipient_ids
        claim = claims.get(str(report.id))
        claimant = responsible_user(claim) if claim is not None else None
        if claimant is not None:
            recipient_ids.add(claimant.id)
        if task.created_by_id is not None:
            recipient_ids.add(task.created_by_id)
        milestone = {
            "completed": "work finished",
            "turn_completed": "work finished",
            "failed": "work failed",
            "cancelled": "work was cancelled",
            "awaiting": "needs your input",
            "pr_merged": "pull request was merged",
            "pr_closed": "pull request was closed",
        }[kind]
        pushed.update(
            _push_report(
                report,
                list(report.team.all_users_with_access().filter(id__in=recipient_ids - pushed).order_by("id")),
                kind=f"report_{kind}",
                title="Report update",
                body=f'"{report.title or "Untitled report"}" {milestone}',
                dedupe_subject=(
                    f"pr:{task.id}:{hashlib.sha256(pull_request_url.encode()).hexdigest()}:{kind}"
                    if pull_request_url
                    else f"task_run:{task_run.id}:{kind}"
                ),
                cooldown_seconds=30 if kind in {"awaiting", "turn_completed"} else 600,
                task_run_id=str(task_run.id),
                pull_request_url=pull_request_url,
                task_id=str(task.id),
                on_enqueued=on_enqueued,
            )
        )
    return True


def _push_report(
    report: SignalReport,
    users: Collection[User],
    *,
    kind: str,
    title: str,
    body: str,
    dedupe_subject: str | None = None,
    cooldown_seconds: int = 600,
    task_run_id: str | None = None,
    pull_request_id: str | None = None,
    pull_request_url: str | None = None,
    task_id: str | None = None,
    on_enqueued: Callable[[], None] | None = None,
) -> list[int]:
    if not users or report_is_hidden_from_inbox(report.team_id, str(report.id)):
        return []
    data = {
        "type": "report",
        "report_id": str(report.id),
        "project_id": report.team_id,
        "notificationKind": kind,
        "url": f"posthog://inbox/{report.id}",
    }
    if task_run_id is not None:
        data["taskRunId"] = task_run_id
    if pull_request_id is not None:
        data["pullRequestId"] = pull_request_id
    if pull_request_url is not None:
        data["pullRequestUrl"] = pull_request_url
    pushed: list[int] = []
    # The project access check also covers a claimant who has since lost access to the project.
    for user in users:
        try:
            category: MobilePushCategory = "reports" if kind == "report_visible" else "report_updates"
            if not mobile_push_preference_enabled(user, category) or not _push_enabled(user):
                continue
            if not may_read_reports(user=user, team=report.team):
                continue
            subject = dedupe_subject or f"{report.id}:{kind}"
            cooldown_key = f"report_push:{subject}:{user.id}"

            def dispatch(user: User = user, cooldown_key: str = cooldown_key) -> bool:
                try:
                    if not claim_mobile_push_cooldown(cooldown_key, timeout_seconds=cooldown_seconds):
                        return False
                    try:

                        def enqueue() -> None:
                            if task_id is not None:
                                suppressed = task_mobile_push_suppressed_token_ids(
                                    user_id=user.id, task_id=task_id, team_id=report.team_id
                                )
                                send_user_push.delay(user.id, title, body, data, suppressed)
                            else:
                                send_user_push.delay(user.id, title, body, data)

                        if pull_request_url is not None and task_id is not None:
                            enqueued = enqueue_task_mobile_pr_outcome(
                                task_id=task_id,
                                team_id=report.team_id,
                                user_id=user.id,
                                pr_url=pull_request_url,
                                kind=kind,
                                enqueue=enqueue,
                            )
                        else:
                            enqueue()
                            enqueued = True
                        if enqueued and on_enqueued is not None:
                            on_enqueued()
                        return enqueued
                    except Exception:
                        release_mobile_push_cooldown(cooldown_key)
                        raise
                except Exception:
                    logger.warning(
                        "signals.inbox_push.enqueue_failed",
                        team_id=report.team_id,
                        report_id=str(report.id),
                        user_id=user.id,
                        kind=kind,
                        exc_info=True,
                    )
                    return False

            if kind in {"report_visible", "pull_request_ready"}:
                if not dispatch():
                    continue
            else:
                transaction.on_commit(dispatch, robust=True)
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
