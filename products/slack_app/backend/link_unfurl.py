import re
from typing import Optional
from urllib.parse import urlparse

import structlog
from celery import shared_task
from slack_sdk.errors import SlackApiError

from posthog.exceptions_capture import capture_exception
from posthog.models import Insight
from posthog.models.exported_asset import ExportedAsset
from posthog.models.integration import Integration, SlackIntegration
from posthog.tasks import exporter

logger = structlog.get_logger(__name__)


def extract_insight_id_from_url(url: str) -> Optional[str]:
    """
    Extract insight short_id from PostHog insight URLs.

    Examples:
    - https://us.posthog.com/project/2/insights/SvcMVcke/edit -> SvcMVcke
    - https://us.posthog.com/insights/SvcMVcke -> SvcMVcke
    - https://us.posthog.com/project/2/insights/123 -> None (numeric IDs not supported for now)
    """
    parsed = urlparse(url)
    path = parsed.path

    # Match patterns like /insights/SvcMVcke or /project/2/insights/SvcMVcke
    # Short IDs are typically 8 alphanumeric characters
    match = re.search(r"/insights/([A-Za-z0-9_-]{8,})", path)
    if match:
        return match.group(1)

    return None


@shared_task(ignore_result=True)
def export_and_unfurl_insight(
    integration_id: int,
    insight_id: str,
    url: str,
    unfurl_id: str,
    channel: str,
    source: str,
    message_ts: str,
) -> None:
    """
    Export an insight as an image and unfurl it in Slack.
    This runs asynchronously since image export can take time.
    """
    try:
        integration = Integration.objects.get(pk=integration_id)
        slack = SlackIntegration(integration)

        # Get the insight by short_id
        try:
            insight = Insight.objects.filter(team=integration.team, short_id=insight_id).first()
            if not insight:
                logger.warning(
                    "slack_unfurl_insight_not_found",
                    insight_id=insight_id,
                    team_id=integration.team_id,
                )
                return

            if not insight.query:
                logger.warning(
                    "slack_unfurl_insight_no_query",
                    insight_id=insight_id,
                    insight_pk=insight.id,
                )
                return

            # Create ExportedAsset with query in export_context
            asset = ExportedAsset.objects.create(
                team=integration.team,
                export_format="image/png",
                export_context={
                    "query": insight.query,
                    "name": insight.name or insight.derived_name,
                    "description": insight.description or "",
                    "show_legend": insight.show_legend,
                },
            )

            # Export the image synchronously (this can take a while)
            logger.info(
                "slack_unfurl_exporting_insight",
                asset_id=asset.id,
                insight_id=insight_id,
                insight_pk=insight.id,
            )
            exporter.export_asset_direct(asset)

            # Wait for export to complete and get the public URL
            asset.refresh_from_db()
            if not asset.has_content:
                logger.error(
                    "slack_unfurl_export_failed",
                    asset_id=asset.id,
                    insight_id=insight_id,
                    exception=asset.exception,
                )
                return

            image_url = asset.get_public_content_url()

            # Unfurl the link in Slack - use section block with image as accessory (matches working pattern)
            unfurls = {
                url: {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": insight.name or insight.derived_name or "Insight",
                            },
                            "accessory": {
                                "type": "image",
                                "image_url": image_url,
                                "alt_text": insight.name or insight.derived_name or "Insight",
                            },
                        }
                    ]
                }
            }

            # Use chat_unfurl API - try with channel/ts first, fallback to without if needed
            try:
                if channel and message_ts:
                    slack.client.chat_unfurl(
                        unfurls=unfurls,
                        unfurl_id=unfurl_id,
                        source=source,
                        channel=channel,
                        ts=message_ts,
                    )
                else:
                    slack.client.chat_unfurl(
                        unfurls=unfurls,
                        unfurl_id=unfurl_id,
                        source=source,
                    )

                logger.info(
                    "slack_unfurl_message_sent",
                    image_url=image_url,
                    insight_id=insight_id,
                    url=url,
                )
            except SlackApiError as e:
                # If it fails with channel/ts, try without (some sources don't require them)
                if channel and message_ts and "channel" in str(e).lower():
                    slack.client.chat_unfurl(
                        unfurls=unfurls,
                        unfurl_id=unfurl_id,
                        source=source,
                    )
                    logger.info(
                        "slack_unfurl_message_sent",
                        image_url=image_url,
                        insight_id=insight_id,
                        url=url,
                    )
                else:
                    raise

            logger.info(
                "slack_unfurl_success",
                asset_id=asset.id,
                insight_id=insight_id,
                url=url,
                unfurl_id=unfurl_id,
            )

        except Insight.DoesNotExist:
            logger.warning(
                "slack_unfurl_insight_not_found",
                insight_id=insight_id,
                team_id=integration.team_id,
            )
        except SlackApiError as e:
            logger.exception(
                "slack_unfurl_api_error",
                error=str(e),
                response=e.response,
                insight_id=insight_id,
                unfurl_id=unfurl_id,
            )
        except Exception as e:
            logger.exception(
                "slack_unfurl_error",
                error=str(e),
                insight_id=insight_id,
                unfurl_id=unfurl_id,
            )
            capture_exception(e)

    except Integration.DoesNotExist:
        logger.exception("slack_unfurl_integration_not_found", integration_id=integration_id)


def handle_link_shared(event: dict, slack_team_id: str) -> None:
    """
    Handle link_shared events from Slack.
    When a PostHog insight URL is shared, export it as an image and unfurl it.
    """
    links = event.get("links", [])
    unfurl_id = event.get("unfurl_id")
    channel = event.get("channel")
    source = event.get("source", "conversations")
    message_ts = event.get("message_ts")

    if not links or not unfurl_id:
        logger.warning(
            "slack_link_shared_missing_data",
            slack_team_id=slack_team_id,
            has_links=bool(links),
            has_unfurl_id=bool(unfurl_id),
        )
        return

    # Find Slack integration for this workspace
    integration = Integration.objects.filter(kind="slack", integration_id=slack_team_id).first()
    if not integration:
        logger.warning("slack_link_shared_no_integration", slack_team_id=slack_team_id)
        return

    # Process each link
    for link in links:
        url = link.get("url", "")
        domain = link.get("domain", "")

        # Only process PostHog URLs
        if "posthog.com" not in domain and "posthog.com" not in url:
            continue

        insight_id = extract_insight_id_from_url(url)
        if not insight_id:
            logger.debug("slack_link_shared_not_insight_url", url=url)
            continue

        logger.info(
            "slack_link_shared_insight_found",
            url=url,
            insight_id=insight_id,
            slack_team_id=slack_team_id,
            unfurl_id=unfurl_id,
        )

        # Queue the export and unfurl task
        export_and_unfurl_insight.delay(
            integration_id=integration.id,
            insight_id=insight_id,
            url=url,
            unfurl_id=unfurl_id,
            channel=channel or "",
            source=source,
            message_ts=message_ts or "",
        )
