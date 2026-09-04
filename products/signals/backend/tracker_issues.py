"""Tracker issues for self-driving pull requests.

Some teams cannot merge a pull request unless a tracked work item points at it, which is a
standard change-management control. When a team names an issue tracker in its self-driving
settings, every auto-started run opens an issue there first, and the pull request and the issue
then reference each other. Nothing here may stop a run: an issue that cannot be opened is
recorded as a failure on the report instead, so the team can see the gap and fix it by hand.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone

import structlog
from rest_framework.exceptions import ValidationError as DRFValidationError

from posthog.dataclasses import frozen
from posthog.models.github_integration_base import GitHubIntegrationBase
from posthog.models.integration import (
    SUPPORTED_EXTERNAL_ISSUE_PROVIDERS,
    GitHubIntegration,
    GitLabIntegration,
    Integration,
    JiraIntegration,
    LinearIntegration,
    external_issue_url,
)

from products.signals.backend.models import SignalReport, SignalReportTrackerIssue, SignalTeamConfig

logger = structlog.get_logger(__name__)

# Target fields the team must supply per provider, on top of what the integration itself carries.
# GitLab needs none: its integration is already bound to one project.
TRACKER_TARGET_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    Integration.IntegrationKind.GITHUB.value: ("repository",),
    Integration.IntegrationKind.GITLAB.value: (),
    Integration.IntegrationKind.LINEAR.value: ("team_id",),
    Integration.IntegrationKind.JIRA.value: ("project_key",),
}

# Hidden in the rendered description, so re-running the cross-link never appends a second block.
PR_BODY_MARKER = "<!-- posthog-self-driving-tracker-issue -->"

# Enough to name the cause (expired token, deleted team) without turning a provider error body
# into an unbounded column.
MAX_FAILURE_REASON_LENGTH = 300


@frozen
class TrackerIssueTarget:
    """Where a team wants its self-driving tracker issues to land."""

    integration: Integration
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

    if kind == Integration.IntegrationKind.GITHUB:
        config: dict[str, Any] = {"repository": target.config["repository"], "title": title, "body": body}
        if label:
            config["labels"] = [label]
        return GitHubIntegration(target.integration).create_issue(config)

    if kind == Integration.IntegrationKind.GITLAB:
        return GitLabIntegration(target.integration).create_issue({"title": title, "body": body})

    if kind == Integration.IntegrationKind.LINEAR:
        # Linear's client attaches the report link to the new issue itself, so the auditor can
        # walk issue → report without the description.
        return LinearIntegration(target.integration).create_issue(
            report_url,
            {"team_id": target.config["team_id"], "title": title, "description": body},
        )

    if kind == Integration.IntegrationKind.JIRA:
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
            "integration": target.integration,
            "provider": target.integration.kind,
            "status": SignalReportTrackerIssue.Status.PENDING,
        },
    )
    if created:
        return claim
    if claim.status == SignalReportTrackerIssue.Status.FAILED:
        claim.status = SignalReportTrackerIssue.Status.PENDING
        claim.integration = target.integration
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

        report_url = f"{settings.SITE_URL}/project/{team_id}/inbox/reports/{report_id}"
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
    identifier = context.get("id") or context.get("key")
    if identifier:
        return str(identifier)
    number = context.get("number") or context.get("issue_id")
    return f"#{number}" if number else None


def branch_identifier(tracker: SignalReportTrackerIssue | None) -> str | None:
    """The identifier to fold into the pull request's head branch name.

    Only Linear reads one: its GitHub integration links a pull request whose branch name carries
    the issue identifier, so that link needs no API call and does not depend on the agent writing
    the right text.
    """
    if tracker is None or tracker.status != SignalReportTrackerIssue.Status.CREATED:
        return None
    if tracker.provider != Integration.IntegrationKind.LINEAR:
        return None
    identifier = (tracker.external_context or {}).get("id")
    return str(identifier) if identifier else None


def _pr_body_reference(tracker: SignalReportTrackerIssue, *, pr_repository: str) -> str | None:
    """The line appended to the pull request body so the pull request names its tracker issue."""
    context = tracker.external_context or {}

    if tracker.provider == Integration.IntegrationKind.GITHUB:
        repository, number = context.get("repository"), context.get("number")
        if not repository or not number:
            return None
        # "Closes #n" only resolves inside the pull request's own repository. Anywhere else GitHub
        # needs the owner-qualified form.
        qualified = f"{pr_repository.split('/')[0]}/{repository}"
        reference = f"#{number}" if qualified.lower() == pr_repository.lower() else f"{qualified}#{number}"
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

        parsed = GitHubIntegrationBase.parse_pull_request_url(pr_url)
        if parsed is None:
            return False
        github = GitHubIntegration.first_for_team_repository(team_id, parsed.repository)
        if github is None:
            logger.info("signals.tracker_issue_link_no_integration", report_id=report_id, pr_url=pr_url)
            return False

        pull_request = github.get_pull_request(parsed.repository, parsed.number)
        if not pull_request.get("success"):
            logger.warning(
                "signals.tracker_issue_link_pr_fetch_failed",
                report_id=report_id,
                pr_url=pr_url,
                error=pull_request.get("error"),
            )
            return False

        body = pull_request.get("body") or ""
        if PR_BODY_MARKER not in body:
            reference = _pr_body_reference(tracker, pr_repository=parsed.repository)
            if reference is None:
                return False
            outcome = github.update_pull_request_body(
                parsed.repository, parsed.number, f"{body.rstrip()}\n\n{PR_BODY_MARKER}\n{reference}\n"
            )
            if not outcome.get("success"):
                logger.warning(
                    "signals.tracker_issue_link_pr_update_failed",
                    report_id=report_id,
                    pr_url=pr_url,
                    error=outcome.get("error"),
                )
                return False

        if tracker.provider == Integration.IntegrationKind.LINEAR and tracker.integration is not None:
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


def _close_provider_issue(tracker: SignalReportTrackerIssue) -> None:
    integration = tracker.integration
    if integration is None:
        raise ValueError("Tracker issue has no integration left to close it through")
    context = tracker.external_context or {}

    if tracker.provider == Integration.IntegrationKind.GITHUB:
        GitHubIntegration(integration).close_issue(context["repository"], int(context["number"]))
    elif tracker.provider == Integration.IntegrationKind.GITLAB:
        GitLabIntegration(integration).close_issue(int(context["issue_id"]))
    elif tracker.provider == Integration.IntegrationKind.LINEAR:
        LinearIntegration(integration).cancel_issue(str(context["id"]))
    elif tracker.provider == Integration.IntegrationKind.JIRA:
        JiraIntegration(integration).close_issue(str(context["key"]))
    else:
        raise ValueError(f"Unsupported tracker provider {tracker.provider}")


def close_tracker_issue_for_report(*, team_id: int, report_id: str) -> bool:
    """Close the report's tracker issue once the report is dismissed. Never raises.

    A dismissed report will not produce a pull request, so its work item is finished. Leaving it
    open would grow a backlog of tracker issues that no pull request will ever answer.
    """
    try:
        tracker = (
            SignalReportTrackerIssue.objects.for_team(team_id)
            .select_related("integration")
            .filter(report_id=report_id, status=SignalReportTrackerIssue.Status.CREATED)
            .first()
        )
        if tracker is None or tracker.closed_at is not None:
            return False

        _close_provider_issue(tracker)
        tracker.closed_at = timezone.now()
        tracker.save(update_fields=["closed_at", "updated_at"])
        return True
    except Exception:
        logger.warning("signals.tracker_issue_close_failed", report_id=report_id, team_id=team_id, exc_info=True)
        return False
