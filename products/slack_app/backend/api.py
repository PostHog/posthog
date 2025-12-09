import json
import asyncio
from uuid import uuid4

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError
from posthog.temporal.common.client import sync_connect
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


def handle_app_mention(event: dict, slack_team_id: str) -> None:
    """Handle app_mention events - when the bot is @mentioned."""
    from posthog.temporal.ai.slack_conversation import (
        SlackConversationRunnerWorkflow,
        SlackConversationRunnerWorkflowInputs,
    )

    channel = event.get("channel")
    if not channel:
        return

    thread_ts = event.get("thread_ts") or event.get("ts")
    if not thread_ts:
        return

    logger.info(
        "slack_app_mention_received",
        channel=channel,
        user=event.get("user"),
        text=event.get("text"),
        thread_ts=thread_ts,
        slack_team_id=slack_team_id,
    )

    # Find a Slack integration for this workspace
    integration = Integration.objects.filter(kind="slack", integration_id=slack_team_id).first()
    if not integration:
        logger.warning("slack_app_no_integration_found", slack_team_id=slack_team_id)
        return

    # Temporary: Only allow team_id=2 in US region during development
    if not settings.DEBUG and not (get_instance_region() == "US" and integration.team_id == 2):
        logger.info("slack_app_mention_skipped", team_id=integration.team_id, region=get_instance_region())
        return

    try:
        slack = SlackIntegration(integration)

        # Fetch all messages in the thread BEFORE posting our response
        thread_messages = slack.client.conversations_replies(channel=channel, ts=thread_ts)
        raw_messages = thread_messages.get("messages", [])

        # Resolve user IDs to display names
        user_cache: dict[str, str] = {}
        messages = []
        for msg in raw_messages:
            user_id = msg.get("user")
            if user_id and user_id not in user_cache:
                try:
                    user_info = slack.client.users_info(user=user_id)
                    profile = user_info.get("user", {}).get("profile", {})
                    # Prefer display_name, fall back to real_name, then user_id
                    user_cache[user_id] = profile.get("display_name") or profile.get("real_name") or user_id
                except Exception:
                    user_cache[user_id] = user_id
            messages.append({"user": user_cache.get(user_id, user_id), "text": msg.get("text")})

        # Generate conversation ID upfront so we can link to it
        conversation_id = str(uuid4())
        conversation_url = f"{settings.SITE_URL}/project/{integration.team_id}/ai?chat={conversation_id}"

        # Post initial "working on it" message in the thread with link to conversation
        initial_response = slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Hey, I'm starting to work on your question...",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "Hey, I'm starting to work on your question..."},
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in PostHog", "emoji": True},
                            "url": conversation_url,
                        }
                    ],
                },
            ],
        )
        initial_message_ts = initial_response.get("ts")
        if not initial_message_ts:
            logger.error("slack_app_initial_message_failed", channel=channel)
            return

        # Start the Temporal workflow
        workflow_inputs = SlackConversationRunnerWorkflowInputs(
            team_id=integration.team_id,
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            initial_message_ts=initial_message_ts,
            messages=messages,
            conversation_id=conversation_id,
        )

        workflow_id = f"slack-conversation-{integration.team_id}-{channel}-{thread_ts}-{uuid4().hex[:8]}"

        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                SlackConversationRunnerWorkflow.run,
                workflow_inputs,
                id=workflow_id,
                task_queue=settings.MAX_AI_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )

        logger.info(
            "slack_conversation_workflow_started",
            workflow_id=workflow_id,
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )

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
        elif event.get("type") == "link_shared":
            from products.slack_app.backend.link_unfurl import handle_link_shared

            handle_link_shared(event, slack_team_id)

        # Return 202 Accepted for event callbacks - processing continues asynchronously
        return HttpResponse(status=202)

    # Return 200 for other event types
    return HttpResponse(status=200)
