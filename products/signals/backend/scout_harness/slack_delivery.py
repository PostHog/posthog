from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.signals.backend.models import SignalScoutEmission
from products.signals.backend.slack_formatting import (
    escape_slack_mrkdwn,
    markdown_to_slack_mrkdwn,
    slack_channel_id_from_target,
    truncate_slack_section,
)

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


def _prettify_scout_name(skill_name: str) -> str:
    cleaned = skill_name.removeprefix("signals-scout-").replace("-", " ").replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Scout"


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
    integration = Integration.objects.filter(
        id=integration_id,
        team_id=emission.team_id,
        kind=Integration.IntegrationKind.SLACK,
    ).first()
    if integration is None:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack integration no longer exists on this project",
            error_code="integration_not_found",
        )

    channel_id = slack_channel_id_from_target(channel)
    if not channel_id:
        raise ScoutSlackPermanentDeliveryError(
            "The configured Slack channel is empty",
            error_code="channel_missing",
        )

    blocks, fallback = build_scout_slack_message(emission)
    try:
        SlackIntegration(integration).client.chat_postMessage(
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
