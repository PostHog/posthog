import re
import json
import random
import asyncio

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.integration import Integration, SlackIntegration, SlackIntegrationError
from posthog.temporal.common.client import sync_connect
from posthog.utils import get_instance_region

logger = structlog.get_logger(__name__)


def _build_slack_thread_key(slack_workspace_id: str, channel: str, thread_ts: str) -> str:
    """Build the unique key for a Slack thread."""
    return f"{slack_workspace_id}:{channel}:{thread_ts}"


def handle_app_mention(event: dict, slack_team_id: str) -> None:
    """Handle app_mention events - when the bot is @mentioned."""
    from posthog.temporal.ai.slack_conversation import (
        THINKING_MESSAGES,
        SlackConversationRunnerWorkflow,
        SlackConversationRunnerWorkflowInputs,
    )

    from ee.models.assistant import Conversation

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

    slack_thread_key = _build_slack_thread_key(slack_team_id, channel, thread_ts)

    # Check if a conversation already exists for this Slack thread
    existing_conversation = Conversation.objects.filter(
        team_id=integration.team_id, slack_thread_key=slack_thread_key
    ).first()

    try:
        slack = SlackIntegration(integration)

        # Get our bot's IDs so we can filter out our own messages and check reactions
        auth_response = slack.client.auth_test()
        our_bot_id = auth_response.get("bot_id")
        our_user_id = auth_response.get("user_id")  # Bot's user ID (used for reactions)

        # Fetch all messages in the thread BEFORE posting our response
        thread_messages = slack.client.conversations_replies(channel=channel, ts=thread_ts)
        raw_messages = thread_messages.get("messages", [])

        # Filter messages: for continuing conversations, only use messages since the last processed app mention
        # A mention is considered "processed" if our bot reacted to it (confirming reception)
        current_event_ts = event.get("ts")
        if existing_conversation:
            # Find the timestamp of the last processed app mention (before the current one)
            previous_mention_ts = None
            for msg in reversed(raw_messages):
                msg_ts = msg.get("ts")
                # Skip the current triggering message
                if msg_ts == current_event_ts:
                    continue
                # Check if this is an app mention (has subtype or contains mention pattern)
                is_app_mention = msg.get("subtype") == "app_mention" or (
                    msg.get("text") and "<@" in msg.get("text", "") and ">" in msg.get("text", "")
                )
                if not is_app_mention:
                    continue
                # Check if our bot reacted to this message (confirming we processed it)
                reactions = msg.get("reactions", [])
                our_bot_reacted = any(our_user_id in reaction.get("users", []) for reaction in reactions)
                if our_bot_reacted:
                    previous_mention_ts = msg_ts
                    break

            if previous_mention_ts:
                # Filter to only messages AFTER the previous processed mention
                raw_messages = [msg for msg in raw_messages if float(msg.get("ts", 0)) > float(previous_mention_ts)]

        # Resolve user IDs to display names, filtering out our own bot's messages
        user_cache: dict[str, str] = {}

        def resolve_user(uid: str) -> str:
            """Resolve a Slack user ID to display name, with caching."""
            if uid not in user_cache:
                try:
                    user_info = slack.client.users_info(user=uid)
                    profile = user_info.get("user", {}).get("profile", {})
                    user_cache[uid] = profile.get("display_name") or profile.get("real_name") or "Unknown"
                except Exception:
                    user_cache[uid] = "Unknown"
            return user_cache[uid]

        def replace_user_mentions(text: str) -> str:
            """Replace <@USER_ID> mentions with resolved @display names."""

            def replace_mention(match: re.Match) -> str:
                uid = match.group(1)
                return f"@{resolve_user(uid)}"

            return re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)

        messages = []
        for msg in raw_messages:
            # Skip messages from our own bot (but allow messages from other bots/apps)
            if our_bot_id and msg.get("bot_id") == our_bot_id:
                continue
            user_id = msg.get("user")
            username = resolve_user(user_id) if user_id else "Unknown"
            text = replace_user_mentions(msg.get("text", ""))
            messages.append({"user": username, "text": text})

        # Use existing conversation ID if available
        conversation_id = str(existing_conversation.id) if existing_conversation else None

        # Get the timestamp of the message that mentioned us (for emoji reactions)
        user_message_ts = event.get("ts")

        # Add a loading emoji reaction to the user's message
        if user_message_ts:
            slack.client.reactions_add(channel=channel, timestamp=user_message_ts, name="hourglass_flowing_sand")

        thinking_message = f"{random.choice(THINKING_MESSAGES)}..."

        # Build blocks for the initial message - only include "View chat in PostHog" if we have an existing conversation
        initial_blocks: list[dict] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": thinking_message},
            },
        ]
        if conversation_id:
            conversation_url = f"{settings.SITE_URL}/project/{integration.team_id}/ai?chat={conversation_id}"
            initial_blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View chat in PostHog", "emoji": True},
                            "url": conversation_url,
                        }
                    ],
                }
            )

        # Post initial "working on it" message in the thread
        initial_response = slack.client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=thinking_message,
            blocks=initial_blocks,
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
            user_message_ts=user_message_ts,
            messages=messages,
            slack_thread_key=slack_thread_key,
            conversation_id=conversation_id,
        )

        # Deterministic workflow ID ensures only one workflow runs per Slack thread at a time
        workflow_id = f"slack-conversation-{slack_thread_key}"

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
            is_continuation=existing_conversation is not None,
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
