import re
from typing import Optional
from urllib.parse import urlparse

import structlog
import posthoganalytics
from celery import shared_task
from slack_sdk.errors import SlackApiError

from posthog.exceptions_capture import capture_exception
from posthog.models import Insight
from posthog.models.dashboard import Dashboard
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


def extract_dashboard_id_from_url(url: str) -> Optional[int]:
    """
    Extract dashboard ID from PostHog dashboard URLs.

    Examples:
    - https://us.posthog.com/project/2/dashboard/123 -> 123
    - https://us.posthog.com/dashboard/456 -> 456
    """
    parsed = urlparse(url)
    path = parsed.path

    # Match patterns like /dashboard/123 or /project/2/dashboard/123
    match = re.search(r"/dashboard/(\d+)", path)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

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


@shared_task(ignore_result=True)
def export_and_unfurl_dashboard(
    integration_id: int,
    dashboard_id: int,
    url: str,
    unfurl_id: str,
    channel: str,
    source: str,
    message_ts: str,
) -> None:
    """
    Export a dashboard as an image and unfurl it in Slack.
    This runs asynchronously since image export can take time.
    """
    try:
        integration = Integration.objects.get(pk=integration_id)
        slack = SlackIntegration(integration)

        # Get the dashboard by ID
        try:
            dashboard = Dashboard.objects.filter(team=integration.team, id=dashboard_id).first()
            if not dashboard:
                logger.warning(
                    "slack_unfurl_dashboard_not_found",
                    dashboard_id=dashboard_id,
                    team_id=integration.team_id,
                )
                return

            # Create ExportedAsset with dashboard
            asset = ExportedAsset.objects.create(
                team=integration.team,
                dashboard=dashboard,
                export_format="image/png",
            )

            # Export the image synchronously (this can take a while)
            logger.info(
                "slack_unfurl_exporting_dashboard",
                asset_id=asset.id,
                dashboard_id=dashboard_id,
            )
            exporter.export_asset_direct(asset)

            # Wait for export to complete and get the public URL
            asset.refresh_from_db()
            if not asset.has_content:
                logger.error(
                    "slack_unfurl_export_failed",
                    asset_id=asset.id,
                    dashboard_id=dashboard_id,
                    exception=asset.exception,
                )
                return

            image_url = asset.get_public_content_url()

            # Unfurl the link in Slack - use section block with image as accessory
            unfurls = {
                url: {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": dashboard.name or "Dashboard",
                            },
                            "accessory": {
                                "type": "image",
                                "image_url": image_url,
                                "alt_text": dashboard.name or "Dashboard",
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
                    dashboard_id=dashboard_id,
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
                        dashboard_id=dashboard_id,
                        url=url,
                    )
                else:
                    raise

            logger.info(
                "slack_unfurl_success",
                asset_id=asset.id,
                dashboard_id=dashboard_id,
                url=url,
                unfurl_id=unfurl_id,
            )

        except Dashboard.DoesNotExist:
            logger.warning(
                "slack_unfurl_dashboard_not_found",
                dashboard_id=dashboard_id,
                team_id=integration.team_id,
            )
        except SlackApiError as e:
            logger.exception(
                "slack_unfurl_api_error",
                error=str(e),
                response=e.response,
                dashboard_id=dashboard_id,
                unfurl_id=unfurl_id,
            )
        except Exception as e:
            logger.exception(
                "slack_unfurl_error",
                error=str(e),
                dashboard_id=dashboard_id,
                unfurl_id=unfurl_id,
            )
            capture_exception(e)

    except Integration.DoesNotExist:
        logger.exception("slack_unfurl_integration_not_found", integration_id=integration_id)


def handle_link_shared(event: dict, slack_team_id: str) -> None:
    """
    Handle link_shared events from Slack.
    When a PostHog insight or dashboard URL is shared, export it as an image and unfurl it.
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

    # Feature flag: check if Slack unfurling is enabled for this team
    # Uses feature flag 'slack-unfurl' if enabled, otherwise falls back to team_id=2
    try:
        enabled = posthoganalytics.feature_enabled(
            "slack-unfurl",
            str(integration.team_id),
            groups={"organization": str(integration.team.organization_id), "project": str(integration.team_id)},
            group_properties={
                "organization": {"id": str(integration.team.organization_id)},
                "project": {"id": str(integration.team_id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if not enabled:
            # Fallback to team_id=2 if feature flag is not enabled
            if integration.team_id != 2:
                logger.debug(
                    "slack_unfurl_team_not_allowed",
                    team_id=integration.team_id,
                    slack_team_id=slack_team_id,
                )
                return
    except Exception as e:
        logger.debug("slack_unfurl_feature_flag_check_failed", error=str(e), team_id=integration.team_id)
        # Fallback to team_id=2 if feature flag check fails
        if integration.team_id != 2:
            logger.debug(
                "slack_unfurl_team_not_allowed",
                team_id=integration.team_id,
                slack_team_id=slack_team_id,
            )
            return

    # Process each link
    for link in links:
        url = link.get("url", "")
        domain = link.get("domain", "")

        # Only process PostHog URLs
        if "posthog.com" not in domain and "posthog.com" not in url:
            continue

        # Try to extract insight ID first
        insight_id = extract_insight_id_from_url(url)
        if insight_id:
            logger.info(
                "slack_link_shared_insight_found",
                url=url,
                insight_id=insight_id,
                slack_team_id=slack_team_id,
                unfurl_id=unfurl_id,
            )

            # Queue the export and unfurl task for insight
            export_and_unfurl_insight.delay(
                integration_id=integration.id,
                insight_id=insight_id,
                url=url,
                unfurl_id=unfurl_id,
                channel=channel or "",
                source=source,
                message_ts=message_ts or "",
            )
            continue

        # Try to extract dashboard ID
        dashboard_id = extract_dashboard_id_from_url(url)
        if dashboard_id:
            logger.info(
                "slack_link_shared_dashboard_found",
                url=url,
                dashboard_id=dashboard_id,
                slack_team_id=slack_team_id,
                unfurl_id=unfurl_id,
            )

            # Queue the export and unfurl task for dashboard
            export_and_unfurl_dashboard.delay(
                integration_id=integration.id,
                dashboard_id=dashboard_id,
                url=url,
                unfurl_id=unfurl_id,
                channel=channel or "",
                source=source,
                message_ts=message_ts or "",
            )
            continue

        logger.debug("slack_link_shared_not_supported_url", url=url)
