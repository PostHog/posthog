from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from django.conf import settings

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.models import SignalReport, SignalScoutEmission, SignalScoutRun
from products.signals.backend.slack_formatting import (
    escape_slack_mrkdwn,
    markdown_to_slack_mrkdwn,
    slack_channel_id_from_target,
    strip_chart_references,
    truncate_slack_section,
)

logger = structlog.get_logger(__name__)

_PERMANENT_SLACK_ERROR_CODES = frozenset(
    {
        "account_inactive",
        "channel_not_found",
        "ekm_access_denied",
        "invalid_auth",
        "is_archived",
        "missing_scope",
        "not_authed",
        "not_in_channel",
        "org_login_required",
        "restricted_action",
        "token_revoked",
    }
)

ScoutSlackOutputType = Literal["finding", "report"]

# Posted as an in-thread reply under every scout Slack message, inviting @PostHog follow-ups.
_SCOUT_SLACK_REPLY_TEXT = "💬 If you have questions, reply in this thread and mention *`@PostHog`*!"


@dataclass(frozen=True)
class ScoutSlackDestination:
    integration_id: int
    channel: str


class ScoutSlackPermanentDeliveryError(RuntimeError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def get_scout_slack_destination(output_destinations: object) -> ScoutSlackDestination | None:
    """Return an active Slack destination from persisted config, tolerating malformed legacy data."""
    if not isinstance(output_destinations, dict):
        return None
    slack = output_destinations.get("slack")
    if not isinstance(slack, dict):
        return None
    integration_id = slack.get("integration_id")
    channel = slack.get("channel")
    if not isinstance(integration_id, int) or isinstance(integration_id, bool) or integration_id < 1:
        return None
    if not isinstance(channel, str) or not channel.strip():
        return None
    return ScoutSlackDestination(integration_id=integration_id, channel=channel.strip())


def slack_api_error_code(exc: SlackApiError) -> str | None:
    error_code = exc.response.get("error") if exc.response else None
    return error_code if isinstance(error_code, str) else None


def _post_scout_slack_reply(
    client: object,
    *,
    channel_id: str,
    thread_ts: object,
    scout_team_id: int,
    integration_team_id: int,
) -> None:
    """Invite @PostHog follow-ups when the Slack connection uses the scout's environment.

    Best-effort and non-blocking: the scout message itself has already been delivered, so a failed
    or missing follow-up never fails the delivery (and so never re-posts the parent on retry).
    """
    if integration_team_id != scout_team_id:
        logger.info(
            "scout_slack_followup_reply_skipped_environment_mismatch",
            scout_team_id=scout_team_id,
            integration_team_id=integration_team_id,
            channel=channel_id,
        )
        return
    if not isinstance(thread_ts, str) or not thread_ts:
        return
    try:
        client.chat_postMessage(  # type: ignore[attr-defined]
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=[{"type": "context", "elements": [{"type": "mrkdwn", "text": _SCOUT_SLACK_REPLY_TEXT}]}],
            text=_SCOUT_SLACK_REPLY_TEXT,
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception:
        # Swallow everything (not just SlackApiError): a transport-level failure here must never
        # fail the task and retry the already-delivered parent message.
        logger.warning("scout_slack_followup_reply_failed", channel=channel_id, exc_info=True)


def _prettify_scout_name(skill_name: str) -> str:
    cleaned = skill_name.removeprefix("signals-scout-").replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Scout"


def _slack_integration_for_project(*, integration_id: int, project_id: int) -> Integration:
    integration = Integration.objects.filter(
        id=integration_id,
        team__project_id=project_id,
        kind=Integration.IntegrationKind.SLACK,
    ).first()
    if integration is None:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack integration no longer exists on this project",
            error_code="integration_not_found",
        )
    return integration


def _slack_channel_id(channel: str) -> str:
    channel_id = slack_channel_id_from_target(channel)
    if not channel_id:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack channel is empty",
            error_code="channel_missing",
        )
    return channel_id


def build_scout_slack_message(emission: SignalScoutEmission) -> tuple[list[dict], str]:
    """Render a direct scout finding with the same safe Markdown conversion as inbox signals."""
    scout_name = _prettify_scout_name(emission.scout_run.skill_name)
    blocks: list[dict] = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}*"}],
        }
    ]

    rendered_description = truncate_slack_section(markdown_to_slack_mrkdwn(emission.description.strip()))
    if rendered_description:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered_description}})

    details: list[str] = []
    if emission.severity:
        details.append(escape_slack_mrkdwn(emission.severity))
    details.append(f"{round(emission.confidence * 100)}% confidence")
    if emission.tags:
        safe_tags = [escape_slack_mrkdwn(str(tag)).replace("`", "'") for tag in emission.tags[:5]]
        details.append(" ".join(f"`{tag}`" for tag in safe_tags))
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(details)}]})

    skill_segment = quote(emission.scout_run.skill_name, safe="")
    finding_segment = quote(emission.finding_id, safe="")
    finding_url = (
        f"{settings.SITE_URL.rstrip('/')}/project/{emission.team_id}/inbox/scouts/{skill_segment}/{finding_segment}"
    )
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View finding in PostHog"},
                    "url": finding_url,
                }
            ],
        }
    )

    first_line = emission.description.strip().splitlines()[0] if emission.description.strip() else "New finding"
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)}: {escape_slack_mrkdwn(first_line[:200])}"
    return blocks, fallback


def post_scout_emission_to_slack(
    emission: SignalScoutEmission,
    *,
    integration_id: int,
    channel: str,
) -> None:
    integration = _slack_integration_for_project(
        integration_id=integration_id,
        project_id=emission.team.project_id,
    )
    channel_id = _slack_channel_id(channel)

    blocks, fallback = build_scout_slack_message(emission)
    client = SlackIntegration(integration).client
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=fallback,
            client_msg_id=str(emission.id),
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as exc:
        error_code = slack_api_error_code(exc)
        if error_code in _PERMANENT_SLACK_ERROR_CODES:
            raise ScoutSlackPermanentDeliveryError(
                f"Slack rejected the scout finding with {error_code}",
                error_code=error_code,
            ) from exc
        raise

    _post_scout_slack_reply(
        client,
        channel_id=channel_id,
        thread_ts=response.get("ts"),
        scout_team_id=emission.team_id,
        integration_team_id=integration.team_id,
    )


def build_scout_report_slack_message(report: SignalReport, run: SignalScoutRun) -> tuple[list[dict], str]:
    scout_name = _prettify_scout_name(run.skill_name)
    title = " ".join((report.title or "").split()) or "New scout report"
    header = title if len(title) <= 150 else title[:147].rstrip() + "..."
    blocks: list[dict] = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Scout · {escape_slack_mrkdwn(scout_name)}*"}],
        },
        {"type": "header", "text": {"type": "plain_text", "text": header}},
    ]

    summary_text = strip_chart_references((report.summary or "").strip())
    rendered_summary = truncate_slack_section(markdown_to_slack_mrkdwn(summary_text))
    if rendered_summary:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": rendered_summary}})

    report_url = f"{settings.SITE_URL.rstrip('/')}/project/{report.team_id}/inbox/reports/{report.id}"
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View report in PostHog"},
                    "url": report_url,
                }
            ],
        }
    )
    fallback = f"Scout · {escape_slack_mrkdwn(scout_name)}: {escape_slack_mrkdwn(title[:200])}"
    return blocks, fallback


def post_scout_report_to_slack(
    report: SignalReport,
    run: SignalScoutRun,
    *,
    delivery_id: str,
    integration_id: int,
    channel: str,
) -> None:
    if report.team_id != run.team_id:
        raise ScoutSlackPermanentDeliveryError(
            "The scout run does not own the configured report",
            error_code="output_team_mismatch",
        )

    integration = _slack_integration_for_project(
        integration_id=integration_id,
        project_id=report.team.project_id,
    )
    channel_id = _slack_channel_id(channel)
    blocks, fallback = build_scout_report_slack_message(report, run)
    client = SlackIntegration(integration).client
    try:
        response = client.chat_postMessage(
            channel=channel_id,
            blocks=blocks,
            text=fallback,
            client_msg_id=delivery_id,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as exc:
        error_code = slack_api_error_code(exc)
        if error_code in _PERMANENT_SLACK_ERROR_CODES:
            raise ScoutSlackPermanentDeliveryError(
                f"Slack rejected the scout report with {error_code}",
                error_code=error_code,
            ) from exc
        raise

    _post_scout_slack_reply(
        client,
        channel_id=channel_id,
        thread_ts=response.get("ts"),
        scout_team_id=run.team_id,
        integration_team_id=integration.team_id,
    )
