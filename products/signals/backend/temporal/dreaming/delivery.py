"""Delivery of the Dreaming Agent's nightly briefing into the inbox and Slack.

The briefing is delivered two ways:

1. **Inbox** — persisted as a dedicated `SignalReport` (status ``READY``) so it appears in
   the web inbox alongside normal reports. It is tagged via its title and a marker artefact
   so each night's briefing replaces the previous one (one live briefing per team) rather
   than piling up.
2. **Slack** — posted to the team's default inbox-notification channel via the existing
   Slack integration. Briefings have no suggested reviewers, so they bypass the reviewer
   routing in ``slack_inbox_notifications`` and go straight to the team channel.

Both are best-effort: a Slack failure never blocks the inbox write, and the dreaming run
never fails because a briefing couldn't be delivered.
"""

from __future__ import annotations

import json
import logging

from django.utils import timezone

from posthog.models.integration import SlackIntegration

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.slack_inbox_notifications import _get_team_slack_integration, _team_notification_channel
from products.signals.backend.temporal.dreaming.briefing import Briefing

logger = logging.getLogger(__name__)

# Title prefix that marks a report as a dreaming briefing — used to find and replace the
# prior night's briefing so only one live briefing exists per team.
DREAMING_BRIEFING_TITLE = "🌙 Nightly briefing"


def _render_briefing_markdown(briefing: Briefing) -> str:
    """Render the briefing as inbox/Slack-friendly markdown."""
    lines = [briefing.intro, ""]
    for idx, item in enumerate(briefing.items, start=1):
        lines.append(f"{idx}. **{item.headline}** — {item.detail}")
    return "\n".join(lines)


def deliver_briefing_to_inbox(team_id: int, briefing: Briefing) -> str:
    """Persist the briefing as a single live `SignalReport` for the team.

    Replaces the prior night's briefing (soft-delete) so the inbox shows exactly one current
    briefing per team. Returns the report id.
    """
    structured = json.dumps(briefing.to_dict())
    markdown = _render_briefing_markdown(briefing)

    # Soft-delete any prior live briefings so only tonight's remains.
    SignalReport.objects.filter(
        team_id=team_id,
        title__startswith=DREAMING_BRIEFING_TITLE,
        status=SignalReport.Status.READY,
    ).update(status=SignalReport.Status.DELETED, updated_at=timezone.now())

    report = SignalReport.objects.create(
        team_id=team_id,
        status=SignalReport.Status.READY,
        title=DREAMING_BRIEFING_TITLE,
        summary=markdown,
        signal_count=0,
        total_weight=0.0,
    )
    # Stash the structured form as an artefact so a UI can render the three items richly.
    SignalReportArtefact.objects.create(
        team_id=team_id,
        report=report,
        type=SignalReportArtefact.ArtefactType.DREAMING_BRIEFING,
        content=structured,
    )
    logger.info("dreaming briefing: delivered to inbox", extra={"team_id": team_id, "report_id": str(report.id)})
    return str(report.id)


def _team_briefing_channel(team_id: int) -> str | None:
    """The team's default inbox-notification channel, reused for briefings."""
    return _team_notification_channel(team_id)


def _build_briefing_blocks(briefing: Briefing) -> tuple[list[dict], str]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": DREAMING_BRIEFING_TITLE, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": briefing.intro}},
    ]
    for idx, item in enumerate(briefing.items, start=1):
        # Slack mrkdwn uses *bold*, not **bold**.
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{idx}. {item.headline}*\n{item.detail}"},
            }
        )
    fallback = f"{DREAMING_BRIEFING_TITLE}: {briefing.intro}"
    return blocks, fallback


def deliver_briefing_to_slack(team_id: int, briefing: Briefing) -> bool:
    """Post the briefing to the team's Slack channel. Best-effort; returns True if posted."""
    integration = _get_team_slack_integration(team_id)
    if integration is None:
        return False
    channel = _team_briefing_channel(team_id)
    if not channel:
        return False

    channel_id = channel.split("|", 1)[0].strip()
    blocks, fallback = _build_briefing_blocks(briefing)
    try:
        slack = SlackIntegration(integration)
        slack.client.chat_postMessage(channel=channel_id, blocks=blocks, text=fallback)
    except Exception:
        logger.exception("dreaming briefing: failed to deliver to Slack", extra={"team_id": team_id})
        return False
    return True


def deliver_briefing(team_id: int, briefing: Briefing) -> tuple[str, bool]:
    """Deliver the briefing to both the inbox and Slack. Returns (report_id, slack_posted)."""
    report_id = deliver_briefing_to_inbox(team_id, briefing)
    slack_posted = deliver_briefing_to_slack(team_id, briefing)
    return report_id, slack_posted
