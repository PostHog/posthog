import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog

from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError

logger = structlog.get_logger(__name__)


def handle_app_mention(event: dict, slack_team_id: str) -> None:
    """Handle app_mention events - when the bot is @mentioned."""
    channel = event.get("channel")
    if not channel:
        return

    logger.info(
        "slack_app_mention_received",
        channel=channel,
        user=event.get("user"),
        text=event.get("text"),
        slack_team_id=slack_team_id,
    )

    # Find a Slack integration for this workspace
    integration = Integration.objects.filter(kind="slack", integration_id=slack_team_id).first()
    if not integration:
        logger.warning("slack_app_no_integration_found", slack_team_id=slack_team_id)
        return

    try:
        slack = SlackIntegration(integration)
        slack.client.chat_postMessage(channel=channel, text="Hello world")
    except Exception as e:
        logger.exception("slack_app_reply_failed", error=str(e))


@csrf_exempt
def slack_event(request: HttpRequest) -> HttpResponse:
    """
    Handle incoming Slack events.

    This endpoint handles:
    - URL verification challenges from Slack
    - Event callbacks (app_mention, etc.)
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        SlackIntegration.validate_request(request)
    except SlackIntegrationError as e:
        slack_config = SlackIntegration.slack_config()
        logger.warning(
            "slack_event_invalid_request",
            error=str(e),
            has_signing_secret=bool(slack_config.get("SLACK_APP_SIGNING_SECRET")),
            has_signature=bool(request.headers.get("X-Slack-Signature")),
            has_timestamp=bool(request.headers.get("X-Slack-Request-Timestamp")),
        )
        return HttpResponse("Invalid request", status=403)

    # Check for retry to avoid duplicate processing
    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("slack_event_retry", retry_num=retry_num)
        return HttpResponse(status=200)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = data.get("type")

    # Handle URL verification challenge (Slack sends this when setting up the endpoint)
    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        return JsonResponse({"challenge": challenge})

    # Handle event callbacks
    if event_type == "event_callback":
        event = data.get("event", {})
        slack_team_id = data.get("team_id", "")

        if event.get("type") == "app_mention":
            handle_app_mention(event, slack_team_id)

    # Always respond with 200 quickly - Slack requires response within 3 seconds
    return HttpResponse(status=200)
