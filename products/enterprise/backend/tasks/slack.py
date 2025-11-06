import re
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

import structlog

from posthog.models.exported_asset import ExportedAsset
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.sharing_configuration import SharingConfiguration

from products.enterprise.backend.tasks.subscriptions.subscription_utils import generate_assets

logger = structlog.get_logger(__name__)


SHARED_LINK_REGEX = r"\/(?:shared_dashboard|shared|embedded)\/(.+)"


def _block_for_asset(asset: ExportedAsset) -> dict:
    image_url = asset.get_public_content_url()
    alt_text = None
    if asset.insight:
        alt_text = asset.insight.name or asset.insight.derived_name

    if settings.DEBUG:
        image_url = "https://source.unsplash.com/random"

    return {"type": "image", "image_url": image_url, "alt_text": alt_text}


def _handle_slack_event(event_payload: Any) -> None:
    slack_team_id = event_payload.get("team_id")
    channel = event_payload.get("event").get("channel")
    message_ts = event_payload.get("event").get("message_ts")
    unfurl_id = event_payload.get("event").get("unfurl_id")
    source = event_payload.get("event").get("source")
    links_to_unfurl = event_payload.get("event").get("links")

    unfurls = {}

    for link_obj in links_to_unfurl:
        link = link_obj.get("url")
        parsed = urlparse(link)
        matches = re.search(SHARED_LINK_REGEX, parsed.path)

        if matches:
            share_token = matches[1]

            # First we try and get the sharingconfig for the given link
            try:
                sharing_config: SharingConfiguration = SharingConfiguration.objects.get(
                    access_token=share_token, enabled=True
                )
            except SharingConfiguration.DoesNotExist:
                logger.info("No SharingConfiguration found")
                continue

            team_id = sharing_config.team_id

            # Now we try and get the SlackIntegration for the specificed PostHog team and Slack Team
            try:
                integration = Integration.objects.get(kind="slack", team=team_id, config__team__id=slack_team_id)
                slack_integration = SlackIntegration(integration)

            except Integration.DoesNotExist:
                logger.info("No SlackIntegration found for this team")
                continue

            # With both the integration and the resource we are good to go!!

            insights, assets = generate_assets(sharing_config, 1)

            if assets:
                unfurls[link] = {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": insights[0].name or insights[0].derived_name,
                            },
                            "accessory": _block_for_asset(assets[0]),
                        }
                    ]
                }

    if unfurls:
        try:
            slack_integration.client.chat_unfurl(unfurls=unfurls, unfurl_id=unfurl_id, source=source, channel="", ts="")
        except Exception:
            # NOTE: This is temporary as a test to understand if the channel and ts are actually required as the docs are not clear
            slack_integration.client.chat_unfurl(
                unfurls=unfurls,
                unfurl_id=unfurl_id,
                source=source,
                channel=channel,
                ts=message_ts,
            )
            raise


def handle_slack_event(payload: Any) -> None:
    return _handle_slack_event(payload)
