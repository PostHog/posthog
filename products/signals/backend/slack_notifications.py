"""Slack DM notifications for signal report assignees.

Piggybacks on the team-level Slack `Integration` — no per-user Slack OAuth required.
Resolution flow: SUGGESTED_REVIEWERS artefact (github_login list) → org member User
→ user with `signal_autonomy_config.notify_on_slack_when_assigned=True` → DM via
`SlackIntegration.send_dm_to_email()` (`users.lookupByEmail` + `conversations.open`).

Idempotency: `SignalReport.slack_notified_at` is claimed atomically before any DM is sent,
so retries / re-promotion-then-ready can't re-DM users for the same report.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction
from django.utils import timezone

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.utils import absolute_uri

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalUserAutonomyConfig
from products.signals.backend.report_generation.resolve_reviewers import (
    normalized_github_logins_from_suggested_reviewer_artefacts,
    resolve_org_github_login_to_users,
)

logger = logging.getLogger(__name__)


def _signal_report_url(team_id: int, report_id: str) -> str:
    return absolute_uri(f"/project/{team_id}/inbox/{report_id}")


def _is_actionable(report_id: str) -> bool:
    """Mirror the list view's `is_suggested_reviewer` actionability gate.

    Returns False only when the latest ACTIONABILITY_JUDGMENT artefact says `not_actionable`.
    Reports without an actionability artefact yet are treated as actionable (consistent with
    the list view where missing-judgment means the report still merits review).
    """
    artefact = (
        SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
        )
        .order_by("-created_at")
        .only("content")
        .first()
    )
    if artefact is None:
        return True
    try:
        parsed = json.loads(artefact.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return True
    return isinstance(parsed, dict) and parsed.get("actionability") != "not_actionable"


def _claim_notification_slot(team_id: int, report_id: str) -> SignalReport | None:
    """Atomically mark the report as notified-now. Returns the report if we won the claim.

    Returns None if another caller already notified, the report doesn't exist, or it isn't READY.
    """
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(id=report_id, team_id=team_id)
            .only("id", "title", "status", "slack_notified_at")
            .first()
        )
        if report is None or report.status != SignalReport.Status.READY:
            return None
        if report.slack_notified_at is not None:
            return None
        report.slack_notified_at = timezone.now()
        report.save(update_fields=["slack_notified_at"])
        return report


def notify_assignees_on_slack_for_ready_report(team_id: int, report_id: str) -> None:
    """Send opt-in Slack DMs to suggested reviewers whose autonomy config has the toggle on.

    Best-effort: any failure is logged and swallowed — notifications must never block the
    report-ready transition. Idempotent across retries via `SignalReport.slack_notified_at`.
    """
    try:
        # Skip reports the list view itself wouldn't surface for review.
        if not _is_actionable(report_id):
            return

        artefacts = SignalReportArtefact.objects.filter(
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        )
        logins = normalized_github_logins_from_suggested_reviewer_artefacts(artefacts)
        if not logins:
            return

        login_to_user = resolve_org_github_login_to_users(team_id, logins)
        if not login_to_user:
            return

        candidate_user_ids = [u.id for u in login_to_user.values()]
        opted_in_user_ids = set(
            SignalUserAutonomyConfig.objects.filter(
                user_id__in=candidate_user_ids,
                notify_on_slack_when_assigned=True,
            ).values_list("user_id", flat=True)
        )
        if not opted_in_user_ids:
            return

        # Multiple workspaces on one team is rare; first-by-id keeps behavior deterministic.
        slack_integration = Integration.objects.filter(team_id=team_id, kind="slack").order_by("id").first()
        if slack_integration is None:
            return

        # Claim the notification slot atomically — anyone who arrives after us short-circuits.
        report = _claim_notification_slot(team_id, report_id)
        if report is None:
            return

        slack = SlackIntegration(slack_integration)
        url = _signal_report_url(team_id, report_id)
        title = report.title or "Untitled report"
        text = f"You've been assigned a signal report: {title}\n{url}"
        blocks: list[dict] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*You've been assigned a signal report*\n<{url}|{title}>",
                },
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Manage notifications in your Signals autonomy settings.",
                    }
                ],
            },
        ]

        for user in login_to_user.values():
            if user.id not in opted_in_user_ids or not user.email:
                continue
            try:
                slack.send_dm_to_email(user.email, text=text, blocks=blocks)
            except SlackApiError:
                logger.exception(
                    "Slack API error while sending DM for ready signal report",
                    extra={"team_id": team_id, "report_id": report_id, "user_id": user.id},
                )
    except (SlackApiError, SignalReport.DoesNotExist):
        logger.exception(
            "Failed to notify assignees on Slack",
            extra={"team_id": team_id, "report_id": report_id},
        )
