import re
import json
import random
import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import requests
import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models.integration import (
    GitHubIntegration,
    Integration,
    SlackIntegration,
    SlackIntegrationError,
    validate_slack_request,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.temporal.ai.slack_conversation import (
    THINKING_MESSAGES,
    SlackConversationRunnerWorkflow,
    SlackConversationRunnerWorkflowInputs,
)
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions

from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

HANDLED_EVENT_TYPES = ["app_mention"]


@dataclass
class SlackUserContext:
    user: User
    slack_email: str


def resolve_slack_user(
    slack: SlackIntegration, integration: Integration, slack_user_id: str, channel: str, thread_ts: str
) -> SlackUserContext | None:
    """Resolve a Slack user to a PostHog user. Posts an ephemeral error message and returns None on failure."""
    try:
        slack_user_info = slack.client.users_info(user=slack_user_id)
        slack_email = slack_user_info.get("user", {}).get("profile", {}).get("email")  # type: ignore[call-overload]
        if not slack_email:
            logger.warning("slack_app_no_user_email", slack_user_id=slack_user_id)
            slack.client.chat_postEphemeral(
                channel=channel,
                user=slack_user_id,
                thread_ts=thread_ts,
                text="Sorry, I couldn't find your email address in Slack. Please make sure your email is visible in your Slack profile.",
            )
            return None

        membership = (
            OrganizationMembership.objects.filter(
                organization_id=integration.team.organization_id, user__email=slack_email
            )
            .select_related("user")
            .first()
        )
        if not membership or not membership.user:
            organization_name = integration.team.organization.name
            slack.client.chat_postEphemeral(
                channel=channel,
                user=slack_user_id,
                thread_ts=thread_ts,
                text=(
                    f"Sorry, I couldn't find {slack_email} in the {organization_name} organization. "
                    f"Please make sure you're a member of that PostHog organization."
                ),
            )
            return None

        posthog_user = membership.user

        user_permissions = UserPermissions(user=posthog_user, team=integration.team)
        if user_permissions.current_team.effective_membership_level is None:
            logger.warning(
                "slack_app_no_team_access",
                user_id=posthog_user.id,
                team_id=integration.team_id,
                organization_id=integration.team.organization_id,
            )
            slack.client.chat_postEphemeral(
                channel=channel,
                user=slack_user_id,
                thread_ts=thread_ts,
                text=(
                    "Sorry, you don't have access to the PostHog project connected to this Slack workspace. "
                    "Please ask an admin of your PostHog organization to grant you access."
                ),
            )
            return None

        return SlackUserContext(user=posthog_user, slack_email=slack_email)
    except Exception as e:
        logger.exception("slack_app_user_lookup_failed", error=str(e))
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            thread_ts=thread_ts,
            text="Sorry, I encountered an error looking up your user account. Please try again later.",
        )
        return None


# To support Slack in both Cloud regions, one region acts as the primary, or "master".
# The primary receives all the events from Slack, and decides what to do about each event:
# 1. If the workspace is connected to any project in the primary region (via Integration), primary handles the event itself;
# 2. If the workspace is NOT connected to any project in the primary region, primary proxies the event to the secondary.
# The secondary region does the same Integration lookup, but if it doesn't find a match either, it stops processing.
# We use EU as the primary region, as it's more important to EU customers that their requests don't leave the EU,
# than to US users that their requests don't leave the US.
SLACK_PRIMARY_REGION_DOMAIN = "eu.posthog.com"
SLACK_SECONDARY_REGION_DOMAIN = "us.posthog.com"

if settings.DEBUG:
    # In local dev, we implicitly test the regional routing by ALWAYS proxying once. When the request first arrives via
    # SITE_URL (e.g. slackhog.ngrok.dev) we treat that as the primary region with no relevant integration, and proxy
    # to localhost:8000, where the actual event handler runs. This way we ensure routing works, and works well.
    SLACK_PRIMARY_REGION_DOMAIN = urlparse(settings.SITE_URL).netloc
    SLACK_SECONDARY_REGION_DOMAIN = "localhost:8000"


def route_slack_event_to_relevant_region(request: HttpRequest, event: dict, slack_team_id: str) -> None:
    """Handle app_mention events - when the bot is @mentioned."""
    # Find a Slack integration for this workspace
    integration = (
        Integration.objects.filter(kind="slack", integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .first()
    )
    if integration and not (settings.DEBUG and request.get_host() == SLACK_PRIMARY_REGION_DOMAIN):
        # We're in the right region
        if event.get("type") == "app_mention":
            handle_app_mention(event, integration)
    elif request.get_host() == SLACK_PRIMARY_REGION_DOMAIN:
        # We aren't in the right region OR the Slack workspace is not connected to any PostHog project in ANY region
        # OR we're in dev and the request hasn't been proxied once yet
        proxy_slack_event_to_secondary_region(request)
    else:
        # The Slack workspace definitively is not connected to any PostHog project in ANY region
        logger.warning("slack_app_no_integration_found", slack_team_id=slack_team_id)
        return


def proxy_slack_event_to_secondary_region(request: HttpRequest) -> None:
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=SLACK_SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    try:
        response = requests.request(
            method=request.method or "POST",
            url=target_url,
            headers=headers,
            params=dict(request.GET.lists()) if request.GET else None,
            data=request.body or None,
            timeout=3,
        )
        logger.warning("slack_app_proxy_to_secondary_region", target_url=target_url, status_code=response.status_code)
    except requests.RequestException as exc:
        logger.exception("slack_app_proxy_to_secondary_region_failed", error=str(exc), target_url=target_url)


def handle_app_mention(event: dict, integration: Integration) -> None:
    channel = event.get("channel")
    slack_team_id = integration.integration_id
    if not channel or not slack_team_id:
        return

    thread_ts = event.get("thread_ts") or event.get("ts")
    if not thread_ts:
        return

    slack_user_id = event.get("user")
    if not slack_user_id:
        return

    logger.info(
        "slack_app_mention_received",
        channel=channel,
        user=slack_user_id,
        text=event.get("text"),
        thread_ts=thread_ts,
        slack_team_id=slack_team_id,
    )

    slack_thread_key = _build_slack_thread_key(slack_team_id, channel, thread_ts)

    # Check if a conversation already exists for this Slack thread
    existing_conversation = Conversation.objects.filter(
        team_id=integration.team_id, slack_thread_key=slack_thread_key
    ).first()

    try:
        slack = SlackIntegration(integration)

        # Check if conversation is already in progress
        if existing_conversation and existing_conversation.status in [
            Conversation.Status.IN_PROGRESS,
            Conversation.Status.CANCELING,
        ]:
            slack.client.chat_postEphemeral(
                channel=channel,
                user=slack_user_id,
                thread_ts=thread_ts,
                text="Hold your hedgehogs! Looks like this PostHog AI is already in flight in this Slack thread – wait for the answer first.",
            )
            return

        user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
        if not user_context:
            return
        posthog_user = user_context.user

        # Get our bot's IDs so we can filter out our own messages and check reactions
        auth_response = slack.client.auth_test()
        our_bot_id = auth_response.get("bot_id")
        our_user_id = auth_response.get("user_id")  # Bot's user ID (used for reactions)

        # Fetch all messages in the thread BEFORE posting our response
        thread_messages = slack.client.conversations_replies(channel=channel, ts=thread_ts)
        raw_messages: list[dict] = thread_messages.get("messages", [])

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
                    empty: dict[str, Any] = {}
                    profile = user_info.get("user", empty).get("profile", empty)
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

        thinking_message = f"I'm {random.choice(THINKING_MESSAGES).lower()}..."

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
            user_id=posthog_user.id,
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

        logger.warning(
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
def slack_event_handler(request: HttpRequest) -> HttpResponse:
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
        logger.warning("slack_event_retry", retry_num=retry_num)
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

        if event.get("type") in HANDLED_EVENT_TYPES:
            route_slack_event_to_relevant_region(request, event, slack_team_id)

        # Return 202 Accepted for event callbacks - processing continues asynchronously
        return HttpResponse(status=202)

    # Return 200 for other event types
    return HttpResponse(status=200)


def _build_slack_thread_key(slack_workspace_id: str, channel: str, thread_ts: str) -> str:
    """Build the unique key for a Slack thread."""
    return f"{slack_workspace_id}:{channel}:{thread_ts}"


def _strip_bot_mentions(text: str) -> str:
    """Remove all <@BOT_ID> mentions from text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _collect_thread_messages(
    slack: SlackIntegration, channel: str, thread_ts: str, our_bot_id: str | None
) -> list[dict[str, str]]:
    """Fetch thread messages, strip bot mentions, and resolve user display names."""
    thread_response = slack.client.conversations_replies(channel=channel, ts=thread_ts)
    raw_messages: list[dict] = thread_response.get("messages", [])

    user_cache: dict[str, str] = {}

    def resolve_user(uid: str) -> str:
        if uid not in user_cache:
            try:
                user_info = slack.client.users_info(user=uid)
                profile = user_info.get("user", {}).get("profile", {})  # type: ignore[call-overload]
                user_cache[uid] = profile.get("display_name") or profile.get("real_name") or "Unknown"
            except Exception:
                user_cache[uid] = "Unknown"
        return user_cache[uid]

    def replace_user_mentions(text: str) -> str:
        def replace_mention(match: re.Match) -> str:
            return f"@{resolve_user(match.group(1))}"

        return re.sub(r"<@([A-Z0-9]+)>", replace_mention, text)

    messages = []
    for msg in raw_messages:
        if our_bot_id and msg.get("bot_id") == our_bot_id:
            continue
        user_id = msg.get("user")
        username = resolve_user(user_id) if user_id else "Unknown"
        text = replace_user_mentions(msg.get("text", ""))
        messages.append({"user": username, "text": text})

    return messages


def guess_repository(
    thread_messages: list[dict[str, str]], integration: Integration, user: "User | None" = None
) -> list[str]:
    """Use the LLM to guess which repository the user is referring to from the thread context."""
    github_integration_record = Integration.objects.filter(team=integration.team, kind="github").first()
    if not github_integration_record:
        return []

    github = GitHubIntegration(github_integration_record)
    org = github.organization()
    repo_names = github.list_repositories()

    if not repo_names:
        return []

    full_repo_names = [f"{org}/{name}" for name in repo_names]

    from openai import OpenAI

    from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_user

    if not user:
        from posthog.llm.gateway_client import get_llm_client

        client = get_llm_client("twig")
    else:
        oauth_token = create_oauth_access_token_for_user(user, integration.team_id)
        base_url = f"{settings.LLM_GATEWAY_URL.rstrip('/')}/twig/v1"
        client = OpenAI(base_url=base_url, api_key=oauth_token)

    conversation_text = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)

    response = client.chat.completions.create(
        model="claude-sonnet-4-5-20250929",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helper that identifies which GitHub repository a conversation is about. "
                    "Given a Slack conversation and a list of available repositories, return the repository names "
                    "that match. Return ONLY the repository names, one per line, in 'org/repo' format. "
                    "If you cannot confidently identify a single repository, return all plausible matches. "
                    "If none match, return nothing."
                ),
            },
            {
                "role": "user",
                "content": f"Available repositories:\n{chr(10).join(full_repo_names)}\n\nConversation:\n{conversation_text}",
            },
        ],
        temperature=0,
    )

    result_text = (response.choices[0].message.content or "").strip()
    if not result_text:
        return []

    matched = []
    for line in result_text.splitlines():
        repo = line.strip()
        if repo in full_repo_names:
            matched.append(repo)

    return matched


def route_twig_event_to_relevant_region(
    request: HttpRequest, event: dict, slack_team_id: str, integration_kind: str = "slack-twig"
) -> None:
    logger.info(
        "twig_route_start",
        slack_team_id=slack_team_id,
        integration_kind=integration_kind,
        host=request.get_host(),
        is_debug=settings.DEBUG,
        primary_region_domain=SLACK_PRIMARY_REGION_DOMAIN,
    )

    integration = (
        Integration.objects.filter(kind=integration_kind, integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .first()
    )

    logger.info(
        "twig_route_integration_lookup",
        found=integration is not None,
        integration_id=integration.id if integration else None,
        team_id=integration.team_id if integration else None,
    )

    if integration and not (settings.DEBUG and request.get_host() == SLACK_PRIMARY_REGION_DOMAIN):
        logger.info("twig_route_handling_locally", integration_id=integration.id)
        if event.get("type") == "app_mention":
            handle_twig_app_mention(event, integration)
    elif request.get_host() == SLACK_PRIMARY_REGION_DOMAIN:
        logger.info("twig_route_proxying_to_secondary")
        proxy_slack_event_to_secondary_region(request)
    else:
        logger.warning("twig_no_integration_found", slack_team_id=slack_team_id)


def handle_twig_app_mention(event: dict, integration: Integration) -> None:
    channel = event.get("channel")
    slack_team_id = integration.integration_id
    if not channel or not slack_team_id:
        logger.warning("twig_mention_missing_channel_or_team", channel=channel, slack_team_id=slack_team_id)
        return

    thread_ts = event.get("thread_ts") or event.get("ts")
    if not thread_ts:
        logger.warning("twig_mention_missing_thread_ts")
        return

    slack_user_id = event.get("user")
    if not slack_user_id:
        logger.warning("twig_mention_missing_user")
        return

    logger.info(
        "twig_app_mention_received",
        channel=channel,
        user=slack_user_id,
        text=event.get("text"),
        thread_ts=thread_ts,
        slack_team_id=slack_team_id,
    )

    try:
        slack = SlackIntegration(integration)

        logger.info("twig_mention_resolving_user", slack_user_id=slack_user_id)
        user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
        if not user_context:
            logger.warning("twig_mention_user_not_resolved", slack_user_id=slack_user_id)
            return
        logger.info("twig_mention_user_resolved", user_id=user_context.user.id)

        auth_response = slack.client.auth_test()
        our_bot_id = auth_response.get("bot_id")
        logger.info("twig_mention_bot_id", bot_id=our_bot_id)

        thread_messages = _collect_thread_messages(slack, channel, thread_ts, our_bot_id)
        logger.info("twig_mention_thread_messages", count=len(thread_messages) if thread_messages else 0)
        if not thread_messages:
            logger.warning("twig_mention_no_thread_messages")
            return

        repos = guess_repository(thread_messages, integration, user=user_context.user)
        logger.info("twig_mention_repos_guessed", repos=repos, count=len(repos))

        if len(repos) != 1:
            if len(repos) == 0:
                msg = "I couldn't determine which repository you're referring to. Please mention the repo name (e.g. `org/repo`) and @mention me again."
            else:
                msg = (
                    "I found multiple possible repositories. Please clarify which one and @mention me again:\n"
                    + "\n".join(f"• `{r}`" for r in repos)
                )

            slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=msg)
            return

        repository = repos[0]

        user_message_ts = event.get("ts")
        if user_message_ts:
            slack.client.reactions_add(channel=channel, timestamp=user_message_ts, name="seedling")

        user_text = _strip_bot_mentions(event.get("text", ""))
        title = user_text[:255] if user_text else "Task from Slack"
        description = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)

        from products.slack_app.backend.slack_thread import SlackThreadContext
        from products.tasks.backend.models import Task

        slack_thread_context = SlackThreadContext(
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
        )

        logger.info(
            "twig_mention_creating_task",
            title=title,
            repository=repository,
            user_id=user_context.user.id,
        )

        Task.create_and_run(
            team=integration.team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.SLACK,
            user_id=user_context.user.id,
            repository=repository,
            slack_thread_context=slack_thread_context,
        )

        logger.info(
            "twig_task_created",
            team_id=integration.team_id,
            repository=repository,
            channel=channel,
            thread_ts=thread_ts,
        )

    except Exception as e:
        logger.exception("twig_app_mention_failed", error=str(e))


@csrf_exempt
def twig_event_handler(request: HttpRequest) -> HttpResponse:
    logger.info("twig_event_handler_called", method=request.method, host=request.get_host())

    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        twig_config = SlackIntegration.twig_slack_config()
        logger.info("twig_event_config_loaded", has_signing_secret=bool(twig_config.get("SLACK_TWIG_SIGNING_SECRET")))
        validate_slack_request(request, twig_config["SLACK_TWIG_SIGNING_SECRET"])
        logger.info("twig_event_signature_valid")
    except SlackIntegrationError as e:
        logger.warning(
            "twig_event_invalid_request",
            error=str(e),
            has_signing_secret=bool(SlackIntegration.twig_slack_config().get("SLACK_TWIG_SIGNING_SECRET")),
        )
        return HttpResponse("Invalid request", status=403)

    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.warning("twig_event_retry", retry_num=retry_num)
        return HttpResponse(status=200)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning("twig_event_invalid_json")
        return HttpResponse("Invalid JSON", status=400)

    event_type = data.get("type")
    logger.info("twig_event_received", event_type=event_type)

    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        return JsonResponse({"challenge": challenge})

    if event_type == "event_callback":
        event = data.get("event", {})
        slack_team_id = data.get("team_id", "")
        logger.info(
            "twig_event_callback",
            inner_event_type=event.get("type"),
            slack_team_id=slack_team_id,
            channel=event.get("channel"),
            user=event.get("user"),
        )

        if event.get("type") == "app_mention":
            route_twig_event_to_relevant_region(request, event, slack_team_id)
        else:
            logger.info("twig_event_ignored", inner_event_type=event.get("type"))

        return HttpResponse(status=202)

    logger.info("twig_event_unhandled_type", event_type=event_type)
    return HttpResponse(status=200)
