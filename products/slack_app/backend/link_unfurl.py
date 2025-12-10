import re
import json
from datetime import timedelta
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import structlog
from celery import shared_task
from slack_sdk.errors import SlackApiError

from posthog.exceptions_capture import capture_exception
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Insight
from posthog.models.dashboard import Dashboard
from posthog.models.exported_asset import ExportedAsset
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.tasks import exporter

logger = structlog.get_logger(__name__)


def get_posthog_user_from_slack_user(slack: SlackIntegration, slack_user_id: str, team_id: int) -> Optional[User]:
    """
    Get the PostHog user corresponding to a Slack user ID by matching email addresses.
    Returns None if no matching user is found.
    """
    try:
        # Get Slack user info
        user_info = slack.client.users_info(user=slack_user_id)
        profile = user_info.get("user", {}).get("profile", {})
        email = profile.get("email")

        if not email:
            return None

        # Find PostHog user by email
        try:
            user = User.objects.get(email=email)
            # Verify user has access to this team
            if user.teams.filter(id=team_id).exists():
                return user
            else:
                return None
        except User.DoesNotExist:
            return None
    except SlackApiError:
        return None
    except Exception:
        return None


def create_impersonated_user_token(user: User, asset_id: int, expiry_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT token for impersonating a user (used for Slack exports).
    Includes the asset ID so we can retrieve the asset from the token.
    """
    if not expiry_delta:
        expiry_delta = timedelta(days=1)  # 1 day expiry for Slack exports

    return encode_jwt(
        {"id": user.id, "asset_id": asset_id},
        expiry_delta=expiry_delta,
        audience=PosthogJwtAudience.IMPERSONATED_USER,
    )


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


def extract_query_from_new_insight_url(url: str) -> Optional[dict]:
    """
    Extract query JSON from new insight URLs with query in hash.

    Examples:
    - https://us.posthog.com/project/2/insights/new#q=%7B%22kind%22%3A... -> query dict
    - https://us.posthog.com/insights/new#q=... -> query dict
    """
    parsed = urlparse(url)
    path = parsed.path
    fragment = parsed.fragment

    # Check if this is a "new insight" URL
    if not path.endswith("/insights/new") and "/insights/new" not in path:
        return None

    if not fragment:
        return None

    # Parse the hash fragment - it might be just the query or have q= parameter
    if fragment.startswith("q="):
        # Extract the q parameter value
        hash_params = parse_qs(fragment)
        if hash_params.get("q"):
            query_str = hash_params["q"][0]
        else:
            return None
    elif fragment.startswith("{") or fragment.startswith("["):
        # The fragment itself is the JSON query
        query_str = fragment
    else:
        # Try parsing as URL params
        try:
            hash_params = parse_qs(fragment)
            if hash_params.get("q"):
                query_str = hash_params["q"][0]
            else:
                return None
        except Exception:
            return None

    # URL decode and parse JSON
    try:
        decoded = unquote(query_str)
        query = json.loads(decoded)
        if isinstance(query, dict):
            return query
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("slack_unfurl_query_extraction_failed", url=url, error=str(e))
        return None

    return None


@shared_task(ignore_result=True)
def export_and_unfurl_query(
    integration_id: int,
    query: dict,
    url: str,
    unfurl_id: str,
    channel: str,
    source: str,
    message_ts: str,
    slack_user_id: Optional[str] = None,
    name: Optional[str] = None,
) -> None:
    """
    Export a query (from new insight URL) as an image and unfurl it in Slack.
    This runs asynchronously since image export can take time.
    """
    try:
        integration = Integration.objects.get(pk=integration_id)
        slack = SlackIntegration(integration)

        # Create ExportedAsset with query in export_context
        asset = ExportedAsset.objects.create(
            team=integration.team,
            export_format="image/png",
            export_context={
                "query": query,
                "name": name or "Insight",
            },
        )

        # Export the image synchronously (this can take a while)
        # Use max_height_pixels to limit image size for Slack (Slack has image size limits)
        logger.info(
            "slack_unfurl_exporting_query",
            asset_id=asset.id,
            url=url,
        )
        exporter.export_asset_direct(asset, max_height_pixels=2000)

        # Wait for export to complete and get the public URL
        asset.refresh_from_db()
        if not asset.has_content:
            logger.error(
                "slack_unfurl_export_failed",
                asset_id=asset.id,
                url=url,
                exception=asset.exception,
            )
            return

        # Get PostHog user from Slack user ID and create IMPERSONATED_USER token
        user = None
        token = None
        if slack_user_id:
            user = get_posthog_user_from_slack_user(slack, slack_user_id, integration.team_id)
            if user:
                token = create_impersonated_user_token(user, asset.id)

        # Use IMPERSONATED_USER token if available, otherwise fall back to EXPORTED_ASSET token
        if token:
            from posthog.utils import absolute_uri

            image_url = absolute_uri(f"/exporter/{asset.filename}?token={token}")
        else:
            image_url = asset.get_public_content_url()

        # Unfurl the link in Slack - use standalone image block for better display
        unfurls = {
            url: {
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{name or 'Insight'}*",
                        },
                    },
                    {
                        "type": "image",
                        "image_url": image_url,
                        "alt_text": name or "Insight",
                    },
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
                    channel="",
                    ts="",
                )

            logger.info(
                "slack_unfurl_message_sent",
                image_url=image_url,
                url=url,
            )
        except SlackApiError as e:
            # If it fails with channel/ts, try without (some sources don't require them)
            if channel and message_ts and "channel" in str(e).lower():
                slack.client.chat_unfurl(
                    unfurls=unfurls,
                    unfurl_id=unfurl_id,
                    source=source,
                    channel="",
                    ts="",
                )
                logger.info(
                    "slack_unfurl_message_sent",
                    image_url=image_url,
                    url=url,
                )
            else:
                raise

        logger.info(
            "slack_unfurl_success",
            asset_id=asset.id,
            url=url,
            unfurl_id=unfurl_id,
        )

    except Integration.DoesNotExist:
        logger.exception("slack_unfurl_integration_not_found", integration_id=integration_id)
    except SlackApiError as e:
        logger.exception(
            "slack_unfurl_api_error",
            error=str(e),
            response=e.response,
            url=url,
            unfurl_id=unfurl_id,
        )
    except Exception as e:
        logger.exception(
            "slack_unfurl_error",
            error=str(e),
            url=url,
            unfurl_id=unfurl_id,
        )
        capture_exception(e)


@shared_task(ignore_result=True)
def export_and_unfurl_insight(
    integration_id: int,
    insight_id: str,
    url: str,
    unfurl_id: str,
    channel: str,
    source: str,
    message_ts: str,
    slack_user_id: Optional[str] = None,
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
            # Use max_height_pixels to limit image size for Slack (Slack has image size limits)
            logger.info(
                "slack_unfurl_exporting_insight",
                asset_id=asset.id,
                insight_id=insight_id,
                insight_pk=insight.id,
            )
            exporter.export_asset_direct(asset, max_height_pixels=2000)

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

            # Get PostHog user from Slack user ID and create IMPERSONATED_USER token
            user = None
            token = None
            if slack_user_id:
                user = get_posthog_user_from_slack_user(slack, slack_user_id, integration.team_id)
                if user:
                    token = create_impersonated_user_token(user, asset.id)

            # Use IMPERSONATED_USER token if available, otherwise fall back to EXPORTED_ASSET token
            if token:
                from posthog.utils import absolute_uri

                image_url = absolute_uri(f"/exporter/{asset.filename}?token={token}")
            else:
                image_url = asset.get_public_content_url()

            # Unfurl the link in Slack - use standalone image block for better display
            unfurls = {
                url: {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{insight.name or insight.derived_name or 'Insight'}*",
                            },
                        },
                        {
                            "type": "image",
                            "image_url": image_url,
                            "alt_text": insight.name or insight.derived_name or "Insight",
                        },
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
                        channel="",
                        ts="",
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
                        channel="",
                        ts="",
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
    slack_user_id: Optional[str] = None,
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
            # Use max_height_pixels to limit image size for Slack (Slack has image size limits)
            logger.info(
                "slack_unfurl_exporting_dashboard",
                asset_id=asset.id,
                dashboard_id=dashboard_id,
            )
            exporter.export_asset_direct(asset, max_height_pixels=2000)

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

            # Get PostHog user from Slack user ID and create IMPERSONATED_USER token
            user = None
            token = None
            if slack_user_id:
                user = get_posthog_user_from_slack_user(slack, slack_user_id, integration.team_id)
                if user:
                    token = create_impersonated_user_token(user, asset.id)

            # Use IMPERSONATED_USER token if available, otherwise fall back to EXPORTED_ASSET token
            if token:
                from posthog.utils import absolute_uri

                image_url = absolute_uri(f"/exporter/{asset.filename}?token={token}")
            else:
                image_url = asset.get_public_content_url()

            # Unfurl the link in Slack - use standalone image block for better display
            unfurls = {
                url: {
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{dashboard.name or 'Dashboard'}*",
                            },
                        },
                        {
                            "type": "image",
                            "image_url": image_url,
                            "alt_text": dashboard.name or "Dashboard",
                        },
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
                        channel="",
                        ts="",
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
                        channel="",
                        ts="",
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
    slack_user_id = event.get("user")  # The Slack user who shared the link

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
    # try:
    #     enabled = posthoganalytics.feature_enabled(
    #         "slack-unfurl",
    #         str(integration.team_id),
    #         groups={"organization": str(integration.team.organization_id), "project": str(integration.team_id)},
    #         group_properties={
    #             "organization": {"id": str(integration.team.organization_id)},
    #             "project": {"id": str(integration.team_id)},
    #         },
    #         only_evaluate_locally=False,
    #         send_feature_flag_events=False,
    #     )
    #     if not enabled:
    #         # Fallback to team_id=2 if feature flag is not enabled
    #         if integration.team_id != 2:
    #             logger.debug(
    #                 "slack_unfurl_team_not_allowed",
    #                 team_id=integration.team_id,
    #                 slack_team_id=slack_team_id,
    #             )
    #             return
    # except Exception as e:
    #     logger.debug("slack_unfurl_feature_flag_check_failed", error=str(e), team_id=integration.team_id)
    #     # Fallback to team_id=2 if feature flag check fails
    #     if integration.team_id != 2:
    #         logger.debug(
    #             "slack_unfurl_team_not_allowed",
    #             team_id=integration.team_id,
    #             slack_team_id=slack_team_id,
    #         )
    #         return

    # Process each link
    for link in links:
        url = link.get("url", "")
        # domain = link.get("domain", "")

        # Only process PostHog URLs
        # if "posthog.com" not in domain and "posthog.com" not in url:
        #     continue

        # Try to extract query from new insight URL first
        query = extract_query_from_new_insight_url(url)
        if query:
            logger.info(
                "slack_link_shared_new_insight_found",
                url=url,
                slack_team_id=slack_team_id,
                unfurl_id=unfurl_id,
            )

            # Queue the export and unfurl task for query
            export_and_unfurl_query.delay(
                integration_id=integration.id,
                query=query,
                url=url,
                unfurl_id=unfurl_id,
                channel=channel or "",
                source=source,
                message_ts=message_ts or "",
                slack_user_id=slack_user_id,
            )
            continue

        # Try to extract insight ID
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
                slack_user_id=slack_user_id,
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
                slack_user_id=slack_user_id,
            )
            continue

        logger.debug("slack_link_shared_not_supported_url", url=url)
