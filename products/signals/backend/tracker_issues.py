"""Tracker issues for self-driving pull requests.

Some teams cannot merge a pull request unless a tracked work item points at it, which is a
standard change-management control. When a team names an issue tracker in its self-driving
settings, every auto-started run opens an issue there first, and the pull request and the issue
then reference each other. Nothing here may stop a run: an issue that cannot be opened is
recorded as a failure on the report instead, so the team can see the gap and fix it by hand.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from django.db import models
from django.utils import timezone

import structlog
from redis.exceptions import RedisError
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationKind, IntegrationRecord
from posthog.models.integration import (
    SUPPORTED_EXTERNAL_ISSUE_PROVIDERS,
    GitHubIntegration,
    GitLabIntegration,
    JiraIntegration,
    LinearIntegration,
    external_issue_url,
)
from posthog.redis import get_client

from products.signals.backend.github_actor import github_mention_for_user
from products.signals.backend.implementation_pr import close_implementation_pr_for_report
from products.signals.backend.models import (
    SignalReport,
    SignalReportMonitoringAttempt,
    SignalReportTrackerIssue,
    SignalTeamConfig,
)
from products.signals.backend.pull_request_body import BodyEditOutcome, edit_pull_request_body
from products.signals.backend.report_urls import ReportLinkSource, build_report_url

logger = structlog.get_logger(__name__)

# Target fields the team must supply per provider, on top of what the integration itself carries.
# GitLab needs none: its integration is already bound to one project.
TRACKER_TARGET_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    IntegrationKind.GITHUB.value: ("repository",),
    IntegrationKind.GITLAB.value: (),
    IntegrationKind.LINEAR.value: ("team_id",),
    IntegrationKind.JIRA.value: ("project_key",),
}

# A GitHub repository name is interpolated into the issues path, so anything holding a path or
# query character could steer an authenticated write to another endpoint. GitHub itself allows
# only these characters in an owner or repository name.
GITHUB_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)?$")

# Hidden in the rendered description, so re-running the cross-link never appends a second block.
PR_BODY_MARKER_PREFIX = "posthog-self-driving-tracker-issue"
PR_BODY_MARKER = f"<!-- {PR_BODY_MARKER_PREFIX}"

# Enough to name the cause (expired token, deleted team) without turning a provider error body
# into an unbounded column.
MAX_FAILURE_REASON_LENGTH = 300
PENDING_CLAIM_TIMEOUT = timedelta(minutes=15)
ABANDONED_CLAIM_REASON = "Tracker issue creation stopped before it returned a result. Check the tracker manually."


@frozen
class TrackerIssueTarget:
    """Where a team wants its self-driving tracker issues to land."""

    integration: IntegrationRecord
    config: dict[str, Any]

    @property
    def label(self) -> str | None:
        """Optional label for created issues. Only the GitHub client takes one today."""
        label = self.config.get("label")
        return label.strip() if isinstance(label, str) and label.strip() else None


def tracker_issue_target_for_team(team_id: int) -> TrackerIssueTarget | None:
    """The team's configured tracker, or ``None`` when the team does not want tracker issues."""
    team_config = SignalTeamConfig.objects.select_related("issue_tracking_integration").filter(team_id=team_id).first()
    if team_config is None:
        return None
    integration = team_config.issue_tracking_integration
    if integration is None or integration.kind not in SUPPORTED_EXTERNAL_ISSUE_PROVIDERS:
        return None
    config = team_config.issue_tracking_config if isinstance(team_config.issue_tracking_config, dict) else {}
    return TrackerIssueTarget(integration=integration, config=config)


def validated_github_repository(repository: str) -> str:
    """The configured repository, or a validation error before any authenticated call goes out."""
    name = str(repository).strip()
    if not GITHUB_REPOSITORY_PATTERN.match(name):
        raise DRFValidationError(
            f"'{repository}' is not a GitHub repository name. Use 'repository' or 'organization/repository'."
        )
    return name


def _issue_body(*, summary: str, report_url: str, repository: str) -> str:
    return (
        f"{summary}\n\n"
        f"PostHog self-driving is implementing this. The pull request will open against "
        f"`{repository}` and will link back to this issue.\n\n"
        f"Report: {report_url}"
    )


def _create_provider_issue(target: TrackerIssueTarget, *, title: str, body: str, report_url: str) -> dict[str, Any]:
    kind = target.integration.kind
    label = target.label

    if kind == IntegrationKind.GITHUB:
        config: dict[str, Any] = {
            "repository": validated_github_repository(target.config["repository"]),
            "title": title,
            "body": body,
        }
        if label:
            config["labels"] = [label]
        github = GitHubIntegration(target.integration, source="signals_tracker_issues", priority=Priority.CRITICAL)
        context = dict(github.create_issue(config))
        repository = str(context["repository"])
        context["repository"] = repository if "/" in repository else f"{github.organization()}/{repository}"
        return context

    if kind == IntegrationKind.GITLAB:
        return GitLabIntegration(target.integration).create_issue({"title": title, "body": body})

    if kind == IntegrationKind.LINEAR:
        # Linear's client attaches the report link to the new issue itself, so the auditor can
        # walk issue → report without the description.
        return LinearIntegration(target.integration).create_issue(
            report_url,
            {"team_id": target.config["team_id"], "title": title, "description": body},
        )

    if kind == IntegrationKind.JIRA:
        return JiraIntegration(target.integration).create_issue(
            {"project_key": target.config["project_key"], "title": title, "description": body}
        )

    raise ValueError(f"Unsupported tracker provider {kind}")


def _failure_reason(error: Exception) -> str:
    """A short, readable cause for the inbox to show next to the pull request."""
    if isinstance(error, KeyError):
        return f"The tracker target is missing {error.args[0]}. Check the self-driving settings."
    if isinstance(error, DRFValidationError):
        detail = error.detail
        text = "; ".join(str(item) for item in detail) if isinstance(detail, list) else str(detail)
    else:
        text = str(error)
    return (text or error.__class__.__name__)[:MAX_FAILURE_REASON_LENGTH]


def _claim_tracker_issue(
    *, team_id: int, report_id: str, target: TrackerIssueTarget
) -> SignalReportTrackerIssue | None:
    """Take the one row that lets this evaluation call the provider, or ``None`` if it cannot.

    Auto-start is re-evaluated from several paths at once and the provider call happens outside the
    report lock, so without this claim two evaluations would each open an issue for one report. The
    row is unique per report, so exactly one claim wins. A row that already holds an issue is
    returned as it is; a row left by a failed attempt is retried.
    """
    # for_team scopes the lookup; get_or_create still needs team_id in the defaults, because a
    # queryset filter does not propagate into the row it creates.
    claim, created = SignalReportTrackerIssue.objects.for_team(team_id).get_or_create(
        report_id=report_id,
        defaults={
            "team_id": team_id,
            "integration_id": target.integration.id,
            "provider": target.integration.kind,
            "status": SignalReportTrackerIssue.Status.PENDING,
        },
    )
    if created:
        return claim
    if claim.status == SignalReportTrackerIssue.Status.PENDING:
        if claim.updated_at <= timezone.now() - PENDING_CLAIM_TIMEOUT:
            claim.status = SignalReportTrackerIssue.Status.FAILED
            claim.failure_reason = ABANDONED_CLAIM_REASON
            claim.save(update_fields=["status", "failure_reason", "updated_at"])
        return None
    if claim.status == SignalReportTrackerIssue.Status.FAILED:
        if claim.failure_reason == ABANDONED_CLAIM_REASON:
            return None
        claim.status = SignalReportTrackerIssue.Status.PENDING
        claim.integration_id = target.integration.id
        claim.provider = target.integration.kind
        claim.save(update_fields=["status", "integration", "provider", "updated_at"])
        return claim
    return None


def create_tracker_issue_for_report(
    *, team_id: int, report_id: str, repository: str
) -> SignalReportTrackerIssue | None:
    """Open the tracker issue for a report's upcoming pull request.

    The issue reads from the report itself, not from the task description the agent gets: an
    auditor opening the issue wants the finding, not the run's instructions.

    Returns the row, or ``None`` when the team wants no tracker issue. Never raises: a provider
    failure is stored on the row so the report can show it, and the run continues either way.
    """
    try:
        target = tracker_issue_target_for_team(team_id)
        if target is None:
            return None

        report = SignalReport.objects.filter(id=report_id, team_id=team_id).only("title", "summary").first()
        if report is None:
            return None

        tracker = _claim_tracker_issue(team_id=team_id, report_id=report_id, target=target)
        if tracker is None:
            return SignalReportTrackerIssue.objects.for_team(team_id).filter(report_id=report_id).first()

        report_url = build_report_url(team_id, report_id, ReportLinkSource.TRACKER)
        try:
            external_context = _create_provider_issue(
                target,
                # A report can reach dispatch before its research run writes a title.
                title=report.title or "PostHog self-driving change",
                body=_issue_body(summary=report.summary or "", report_url=report_url, repository=repository),
                report_url=report_url,
            )
        except Exception as error:
            logger.warning(
                "signals.tracker_issue_create_failed",
                report_id=report_id,
                team_id=team_id,
                provider=target.integration.kind,
                exc_info=True,
            )
            tracker.status = SignalReportTrackerIssue.Status.FAILED
            tracker.failure_reason = _failure_reason(error)
        else:
            tracker.status = SignalReportTrackerIssue.Status.CREATED
            tracker.failure_reason = None
            tracker.external_context = external_context
            tracker.issue_url = external_issue_url(target.integration, external_context) or None
        tracker.save(update_fields=["status", "failure_reason", "external_context", "issue_url", "updated_at"])
        return tracker
    except Exception:
        logger.exception("signals.tracker_issue_create_unexpected_error", report_id=report_id, team_id=team_id)
        return None


def issue_reference(tracker: SignalReportTrackerIssue) -> str | None:
    """How the issue reads in its provider, for example "#12" or "ENG-123"."""
    context = tracker.external_context or {}
    identifier = context.get("key") or context.get("id")
    if identifier:
        return str(identifier)
    number = context.get("number") or context.get("issue_id")
    return f"#{number}" if number else None


def _pr_body_reference(tracker: SignalReportTrackerIssue, *, pr_repository: str) -> str | None:
    """The line appended to the pull request body so the pull request names its tracker issue."""
    context = tracker.external_context or {}

    if tracker.provider == IntegrationKind.GITHUB:
        repository, number = context.get("repository"), context.get("number")
        if not repository or not number:
            return None
        # "Closes #n" only resolves inside the pull request's own repository. Anywhere else GitHub
        # needs the owner-qualified form.
        reference = f"#{number}" if repository.lower() == pr_repository.lower() else f"{repository}#{number}"
        return f"Closes {reference}"

    identifier = issue_reference(tracker)
    if identifier and tracker.issue_url:
        return f"Tracked in [{identifier}]({tracker.issue_url})"
    if tracker.issue_url:
        return f"Tracked in {tracker.issue_url}"
    return None


def link_pull_request_to_tracker_issue(*, team_id: int, report_id: str, pr_url: str) -> bool:
    """Cross-reference an opened pull request and the report's tracker issue.

    Edits the pull request description rather than trusting the agent to write the reference, and
    attaches the pull request to a Linear issue so the link reads in both directions. Returns
    whether the pull request now carries the reference. Never raises.
    """
    try:
        tracker = (
            SignalReportTrackerIssue.objects.for_team(team_id)
            .select_related("integration")
            .filter(report_id=report_id, status=SignalReportTrackerIssue.Status.CREATED)
            .first()
        )
        if tracker is None or tracker.pr_linked_at is not None:
            return False

        marker = f"{PR_BODY_MARKER}:{report_id} -->"

        def add_reference(body: str, repository: str) -> str | None:
            if marker in body:
                return body
            reference = _pr_body_reference(tracker, pr_repository=repository)
            if reference is None:
                return None
            return f"{body.rstrip()}\n\n{marker}\n{reference}\n"

        outcome = edit_pull_request_body(
            team_id=team_id,
            report_id=report_id,
            pr_url=pr_url,
            edit=add_reference,
            log_event="signals.tracker_issue_link",
        )
        if outcome != BodyEditOutcome.WRITTEN:
            return False

        if tracker.provider == IntegrationKind.LINEAR and tracker.integration is not None:
            # Best-effort: the description reference already links the two, and this attachment
            # needs a Linear scope the team may not have granted.
            try:
                LinearIntegration(tracker.integration).create_attachment(
                    str((tracker.external_context or {}).get("id")), pr_url
                )
            except Exception:
                logger.warning("signals.tracker_issue_linear_attachment_failed", report_id=report_id, exc_info=True)

        tracker.pr_linked_at = timezone.now()
        tracker.save(update_fields=["pr_linked_at", "updated_at"])
        return True
    except Exception:
        logger.exception("signals.tracker_issue_link_unexpected_error", report_id=report_id, team_id=team_id)
        return False


def _close_notice(*, report_link: str, actor_mention: str | None) -> str:
    """What the issue says about its own close.

    One wording covers every close, because the ``completed`` flag alone cannot name the verb: an
    uncompleted close is a dismissal, a delete, or a resolve that needed no pull request. The
    report page holds the detail, and the mention names the person GitHub cannot — the close goes
    out under the team's GitHub App.
    """
    if actor_mention:
        return f"🔕 {actor_mention} closed the {report_link} in PostHog, so this issue is closed too."
    return f"🔕 The {report_link} was closed in PostHog, so this issue is closed too."


def _comment_before_close(
    tracker: SignalReportTrackerIssue, *, report_link: str, actor_mention: str | None, priority: Priority
) -> None:
    """Best-effort note on the issue naming who closed the report. Only GitHub takes one today.

    Explain first, close second, as the implementation pull request does. A failed comment must
    not stop the close: an issue left open would grow the backlog this close exists to prevent,
    while a missing comment costs only the attribution.
    """
    if (
        tracker.provider != IntegrationKind.GITHUB
        or tracker.integration is None
        or tracker.close_comment_posted_at is not None
    ):
        return
    context = tracker.external_context or {}
    try:
        result = GitHubIntegration(
            tracker.integration, source="signals_tracker_issues", priority=Priority.BATCH
        ).comment_on_issue(
            context["repository"],
            int(context["number"]),
            _close_notice(report_link=report_link, actor_mention=actor_mention),
        )
        if result.get("success"):
            tracker.close_comment_posted_at = timezone.now()
            tracker.save(update_fields=["close_comment_posted_at", "updated_at"])
    except (GitHubEgressBudgetExhausted, GitHubRateLimitError):
        if priority == Priority.BATCH:
            raise
    except Exception:
        logger.warning("signals.tracker_issue_close_comment_failed", tracker_id=str(tracker.id), exc_info=True)


def _close_provider_issue(tracker: SignalReportTrackerIssue, *, completed: bool, priority: Priority) -> None:
    integration = tracker.integration
    if integration is None:
        raise ValueError("Tracker issue has no integration left to close it through")
    context = tracker.external_context or {}

    if tracker.provider == IntegrationKind.GITHUB:
        GitHubIntegration(integration, source="signals_tracker_issues", priority=priority).close_issue(
            context["repository"], int(context["number"]), completed=completed
        )
    elif tracker.provider == IntegrationKind.GITLAB:
        GitLabIntegration(integration).close_issue(int(context["issue_id"]))
    elif tracker.provider == IntegrationKind.LINEAR:
        LinearIntegration(integration).close_issue(str(context["id"]), completed=completed)
    elif tracker.provider == IntegrationKind.JIRA:
        JiraIntegration(integration).close_issue(str(context["key"]))
    else:
        raise ValueError(f"Unsupported tracker provider {tracker.provider}")


def _current_completion_attempt(
    *, team_id: int, report_id: str, monitoring_attempt_id: str
) -> SignalReportMonitoringAttempt | None:
    return (
        SignalReportMonitoringAttempt.objects.for_team(team_id)
        .filter(
            id=monitoring_attempt_id,
            report_id=report_id,
            aggregation_state="passed",
            tracker_issue_close_processed_at__isnull=True,
            monitoring_started_at=models.F("report__monitoring_started_at"),
        )
        .filter(
            models.Q(report__status=SignalReport.Status.RESOLVED)
            | models.Q(
                report__status=SignalReport.Status.SUPPRESSED,
                report__status_before_suppression=SignalReport.Status.RESOLVED,
            )
        )
        .first()
    )


def _close_tracker_issue_for_report(
    *,
    team_id: int,
    report_id: str,
    completed: bool,
    actor_user_id: int | None,
    monitoring_attempt_id: str | None,
    priority: Priority,
) -> bool:
    """Close the report's tracker issue once the report is dismissed or completed.

    A dismissed report will not produce a pull request, so its work item is finished. Leaving it
    open would grow a backlog of tracker issues that no pull request will ever answer. Batch rate
    limits propagate so the sweep can honor the provider's retry window.
    """

    def can_complete() -> bool:
        return (
            monitoring_attempt_id is None
            or _current_completion_attempt(
                team_id=team_id, report_id=report_id, monitoring_attempt_id=monitoring_attempt_id
            )
            is not None
        )

    try:
        pr_completed = True
        if monitoring_attempt_id is not None:
            attempt = _current_completion_attempt(
                team_id=team_id, report_id=report_id, monitoring_attempt_id=monitoring_attempt_id
            )
            if attempt is None:
                return True
            if attempt.close_pr_on_resolve:
                pr_completed = close_implementation_pr_for_report(
                    team_id,
                    report_id,
                    reason="resolved",
                    actor_user_id=actor_user_id,
                    comment_marker=f"<!-- monitoring-completion:{attempt.id} -->",
                    before_close=can_complete,
                    priority=priority,
                    require_all=True,
                )
        tracker = (
            SignalReportTrackerIssue.objects.for_team(team_id)
            .select_related("integration")
            .filter(
                report_id=report_id,
                status__in=[SignalReportTrackerIssue.Status.PENDING, SignalReportTrackerIssue.Status.CREATED],
            )
            .first()
        )
        if tracker is None or tracker.closed_at is not None:
            return monitoring_attempt_id is not None and pr_completed
        if tracker.status == SignalReportTrackerIssue.Status.PENDING:
            return False

        if not can_complete():
            return True
        report_url = build_report_url(team_id, report_id, ReportLinkSource.TRACKER)
        _comment_before_close(
            tracker,
            report_link=f"[linked PostHog report]({report_url})",
            actor_mention=github_mention_for_user(actor_user_id),
            priority=priority,
        )
        if not can_complete():
            return True
        _close_provider_issue(tracker, completed=completed, priority=priority)
        tracker.closed_at = timezone.now()
        tracker.save(update_fields=["closed_at", "updated_at"])
        return pr_completed
    except (GitHubEgressBudgetExhausted, GitHubRateLimitError):
        if priority == Priority.BATCH:
            raise
        return False
    except Exception:
        logger.warning("signals.tracker_issue_close_failed", report_id=report_id, team_id=team_id, exc_info=True)
        return False


@contextmanager
def tracker_issue_completion_lock(*, team_id: int, report_id: str) -> Iterator[bool]:
    lock = None
    acquired = False
    try:
        lock = get_client().lock(f"signals:tracker-close:{team_id}:{report_id}", timeout=120)
        acquired = lock.acquire(blocking=False)
    except RedisError:
        logger.warning("signals.tracker_issue_close_lock_failed", report_id=report_id, team_id=team_id, exc_info=True)
        yield False
        return
    try:
        yield acquired
    finally:
        if acquired and lock is not None:
            try:
                lock.release()
            except RedisError:
                logger.warning("signals.tracker_issue_close_lock_release_failed", report_id=report_id, exc_info=True)


def close_tracker_issue_for_report(
    *,
    team_id: int,
    report_id: str,
    completed: bool = False,
    actor_user_id: int | None = None,
    monitoring_attempt_id: str | None = None,
    priority: Priority = Priority.CRITICAL,
) -> bool:
    with tracker_issue_completion_lock(team_id=team_id, report_id=report_id) as acquired:
        if not acquired:
            return False
        return _close_tracker_issue_for_report(
            team_id=team_id,
            report_id=report_id,
            completed=completed,
            actor_user_id=actor_user_id,
            monitoring_attempt_id=monitoring_attempt_id,
            priority=priority,
        )


def complete_monitoring_tracker_issues(*, deadline: float, limit: int = 100) -> None:
    now = timezone.now()
    due = models.Q(tracker_issue_close_next_attempt_at__isnull=True) | models.Q(
        tracker_issue_close_next_attempt_at__lte=now
    )
    attempts = (
        SignalReportMonitoringAttempt.objects.unscoped()
        .filter(tracker_issue_close_requested_at__isnull=False, tracker_issue_close_processed_at__isnull=True)
        .filter(due)
        .order_by(
            models.F("tracker_issue_close_next_attempt_at").asc(nulls_first=True),
            "tracker_issue_close_requested_at",
            "id",
        )[:limit]
    )
    for attempt in attempts:
        if time.monotonic() >= deadline:
            break
        claimed = (
            SignalReportMonitoringAttempt.objects.for_team(attempt.team_id)
            .filter(id=attempt.id, tracker_issue_close_processed_at__isnull=True)
            .filter(due)
            .update(tracker_issue_close_next_attempt_at=now + timedelta(minutes=5))
        )
        if not claimed:
            continue
        try:
            completed = close_tracker_issue_for_report(
                team_id=attempt.team_id,
                report_id=str(attempt.report_id),
                completed=True,
                monitoring_attempt_id=str(attempt.id),
                priority=Priority.BATCH,
            )
        except (GitHubEgressBudgetExhausted, GitHubRateLimitError) as error:
            retry_after = 300
            if isinstance(error, GitHubRateLimitError):
                retry_after = max(retry_after, error.retry_after or 0, (error.reset_at or 0) - int(time.time()))
            SignalReportMonitoringAttempt.objects.for_team(attempt.team_id).filter(
                id=attempt.id, tracker_issue_close_processed_at__isnull=True
            ).update(tracker_issue_close_next_attempt_at=timezone.now() + timedelta(seconds=retry_after))
            return
        if completed:
            SignalReportMonitoringAttempt.objects.for_team(attempt.team_id).filter(id=attempt.id).update(
                tracker_issue_close_processed_at=timezone.now()
            )
