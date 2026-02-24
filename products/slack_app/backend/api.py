import re
import json
import time
import uuid
import random
import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core import signing
from django.core.cache import cache
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
from posthog.security.outbound_proxy import external_requests
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

ROUTE_HANDLED_LOCALLY = "handled_locally"
ROUTE_PROXIED = "proxied"
ROUTE_PROXY_FAILED = "proxy_failed"
ROUTE_NO_INTEGRATION = "no_integration"

PICKER_TOKEN_SALT = "twig_repo_picker"
PICKER_TOKEN_MAX_AGE_SECONDS = 900


@dataclass
class SlackUserContext:
    user: User
    slack_email: str


@dataclass
class RepoDecision:
    mode: Literal["auto", "picker"]
    repository: str | None
    reason: str
    llm_called: bool


@dataclass
class DefaultRepoCommand:
    action: Literal["set", "show", "clear"]
    repository: str | None = None


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
    integrations = list(
        Integration.objects.filter(kind="slack", integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .order_by("id")[:2]
    )
    if len(integrations) > 1:
        logger.warning("slack_multiple_integrations", slack_team_id=slack_team_id)
    integration = integrations[0] if integrations else None
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


def _proxy_to_secondary(request: HttpRequest) -> requests.Response | None:
    """Proxy a request to the secondary region, returning the upstream response or None on failure."""
    parsed_url = urlparse(request.build_absolute_uri())
    target_url = urlunparse(parsed_url._replace(netloc=SLACK_SECONDARY_REGION_DOMAIN))
    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}

    try:
        response = external_requests.request(
            method=request.method or "POST",
            url=target_url,
            headers=headers,
            params=dict(request.GET.lists()) if request.GET else None,
            data=request.body or None,
            timeout=3,
        )
        if 200 <= response.status_code < 300:
            logger.info("slack_app_proxy_to_secondary_region", target_url=target_url, status_code=response.status_code)
            return response

        logger.warning(
            "slack_app_proxy_to_secondary_region_non_success",
            target_url=target_url,
            status_code=response.status_code,
        )
        return None
    except requests.RequestException as exc:
        logger.exception("slack_app_proxy_to_secondary_region_failed", error=str(exc), target_url=target_url)
        return None


def proxy_slack_event_to_secondary_region(request: HttpRequest) -> bool:
    return _proxy_to_secondary(request) is not None


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


def _parse_default_repo_command(text: str) -> DefaultRepoCommand | None:
    cleaned = _strip_bot_mentions(text).strip()
    if not cleaned:
        return None

    clear_match = re.fullmatch(r"default\s+repo\s+clear", cleaned, flags=re.IGNORECASE)
    if clear_match:
        return DefaultRepoCommand(action="clear")

    show_match = re.fullmatch(r"default\s+repo\s+show", cleaned, flags=re.IGNORECASE)
    if show_match:
        return DefaultRepoCommand(action="show")

    set_match = re.fullmatch(r"default\s+repo\s+set(?:\s+([\w.-]+/[\w.-]+))?", cleaned, flags=re.IGNORECASE)
    if set_match:
        return DefaultRepoCommand(action="set", repository=set_match.group(1))

    return None


def _get_user_default_repo(team_id: int, user_id: int) -> str | None:
    from products.slack_app.backend.models import SlackUserRepoPreference

    preference = SlackUserRepoPreference.objects.filter(team_id=team_id, user_id=user_id).first()
    return preference.repository if preference else None


def _set_user_default_repo(team_id: int, user_id: int, repository: str) -> None:
    from products.slack_app.backend.models import SlackUserRepoPreference

    SlackUserRepoPreference.objects.update_or_create(
        team_id=team_id,
        user_id=user_id,
        defaults={"repository": repository},
    )


def _clear_user_default_repo(team_id: int, user_id: int) -> bool:
    from products.slack_app.backend.models import SlackUserRepoPreference

    deleted_count, _ = SlackUserRepoPreference.objects.filter(team_id=team_id, user_id=user_id).delete()
    return bool(deleted_count)


def _post_repo_picker_message(
    *,
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    event_text: str,
    user_message_ts: str | None,
    guidance: str,
    action_id: str,
) -> None:
    context_data = {
        "integration_id": integration.id,
        "channel": channel,
        "thread_ts": thread_ts,
        "user_message_ts": user_message_ts,
        "mentioning_slack_user_id": slack_user_id,
        "event_text": event_text,
        "created_at": int(time.time()),
    }
    context_token = uuid.uuid4().hex
    cache.set(_picker_context_cache_key(context_token), context_data, timeout=PICKER_TOKEN_MAX_AGE_SECONDS)

    slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=guidance,
        blocks=[
            {
                "type": "section",
                "block_id": f"twig_repo_picker_v2:{integration.id}:{slack_user_id}:{context_token}",
                "text": {"type": "mrkdwn", "text": guidance},
                "accessory": {
                    "type": "external_select",
                    "action_id": action_id,
                    "placeholder": {"type": "plain_text", "text": "Search GitHub repositories..."},
                    "min_query_length": 0,
                },
            },
        ],
        metadata={"event_type": "twig_repo_picker", "event_payload": {"context_token": context_token}},
    )


def _extract_explicit_repo(text: str, all_repos: list[str]) -> str | None:
    """Extract an explicit org/repo token from message text, if it matches connected repos."""
    if not text or not all_repos:
        return None

    normalized_repos = {repo.lower(): repo for repo in all_repos}
    cleaned_text = _strip_bot_mentions(text)

    for token in cleaned_text.split():
        candidate = token.strip("`'\"()[]{}<>,.;:!?")

        # Slack can format links as <url|label>; for repo tokens we want the label.
        if "|" in candidate:
            candidate = candidate.split("|", 1)[1].strip("`'\"()[]{}<>,.;:!?")

        if not candidate or "://" in candidate or candidate.startswith("http"):
            continue
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", candidate):
            continue

        match = normalized_repos.get(candidate.lower())
        if match:
            return match

    return None


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


def _get_full_repo_names(integration: Integration) -> list[str]:
    """Return canonical org/repo names for the team's GitHub integration, or [] if unavailable."""
    github_integration_record = Integration.objects.filter(team=integration.team, kind="github").first()
    if not github_integration_record:
        return []

    github = GitHubIntegration(github_integration_record)
    org = github.organization()
    repo_names = github.list_repositories()

    if not repo_names:
        return []

    return [f"{org}/{name}" for name in repo_names]


def guess_repository(
    thread_messages: list[dict[str, str]],
    integration: Integration,
    user: "User | None" = None,
    all_repos: list[str] | None = None,
) -> list[str]:
    """Use the LLM to guess which repository the user is referring to from the thread context."""
    full_repo_names = all_repos if all_repos is not None else _get_full_repo_names(integration)
    if not full_repo_names:
        return []

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
                    "Given a Slack conversation and a list of available repositories, return repository names "
                    "in 'org/repo' format, one per line. "
                    "Return exactly one repository if and only if you are highly confident it is the correct one. "
                    "If there is any ambiguity, uncertainty, or multiple plausible repositories, return nothing. "
                    "Never guess based on organization defaults."
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


def select_repository(
    event_text: str,
    thread_messages: list[dict[str, str]],
    integration: Integration,
    user: User,
    all_repos: list[str],
) -> RepoDecision:
    if not all_repos:
        return RepoDecision(mode="picker", repository=None, reason="no_repos", llm_called=False)

    if len(all_repos) == 1:
        return RepoDecision(mode="auto", repository=all_repos[0], reason="single_repo", llm_called=False)

    explicit_repo = _extract_explicit_repo(event_text, all_repos)
    if explicit_repo:
        return RepoDecision(mode="auto", repository=explicit_repo, reason="explicit_mention", llm_called=False)

    user_default_repo = _get_user_default_repo(integration.team_id, user.id)
    if user_default_repo and user_default_repo in all_repos:
        return RepoDecision(mode="auto", repository=user_default_repo, reason="user_default_repo", llm_called=False)

    if user_default_repo and user_default_repo not in all_repos:
        _clear_user_default_repo(integration.team_id, user.id)

    return RepoDecision(mode="picker", repository=None, reason="no_explicit_multi_repo", llm_called=False)


def route_twig_event_to_relevant_region(
    request: HttpRequest, event: dict, slack_team_id: str, integration_kind: str = "slack-twig"
) -> str:
    integrations = list(
        Integration.objects.filter(kind=integration_kind, integration_id=slack_team_id)
        .select_related("team", "team__organization")
        .order_by("id")[:2]
    )
    if len(integrations) > 1:
        logger.warning("twig_multiple_integrations", slack_team_id=slack_team_id)
    integration = integrations[0] if integrations else None

    if integration and not (settings.DEBUG and request.get_host() == SLACK_PRIMARY_REGION_DOMAIN):
        if event.get("type") == "app_mention":
            from products.slack_app.backend.tasks import process_twig_mention

            process_twig_mention.delay(event, integration.id, slack_team_id)
        return ROUTE_HANDLED_LOCALLY
    elif request.get_host() == SLACK_PRIMARY_REGION_DOMAIN:
        success = proxy_slack_event_to_secondary_region(request)
        return ROUTE_PROXIED if success else ROUTE_PROXY_FAILED
    else:
        logger.warning("twig_no_integration_found", slack_team_id=slack_team_id)
        return ROUTE_NO_INTEGRATION


def _create_task_for_repo(
    *,
    repository: str,
    integration: Integration,
    slack: SlackIntegration,
    channel: str,
    thread_ts: str,
    user_message_ts: str | None,
    event_text: str,
    thread_messages: list[dict[str, str]],
    user_id: int,
    slack_user_id: str | None = None,
) -> None:
    """Create a Task for the given repo, adding a seedling reaction and handling errors."""
    if user_message_ts:
        slack.client.reactions_add(channel=channel, timestamp=user_message_ts, name="seedling")

    user_text = _strip_bot_mentions(event_text)
    title = user_text[:255] if user_text else "Task from Slack"
    description = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)

    from products.slack_app.backend.slack_thread import SlackThreadContext
    from products.tasks.backend.models import Task

    slack_thread_context = SlackThreadContext(
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=user_message_ts,
        mentioning_slack_user_id=slack_user_id,
    )

    slack_thread_url = None
    try:
        permalink_resp = slack.client.chat_getPermalink(channel=channel, message_ts=thread_ts)
        if permalink_resp.get("ok"):
            slack_thread_url = permalink_resp["permalink"]
    except Exception:
        logger.warning("twig_slack_permalink_failed", channel=channel, thread_ts=thread_ts)

    try:
        Task.create_and_run(
            team=integration.team,
            title=title,
            description=description,
            origin_product=Task.OriginProduct.SLACK,
            user_id=user_id,
            repository=repository,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
        )
    except Exception as e:
        logger.exception(
            "twig_task_creation_failed",
            error=str(e),
            team_id=integration.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        try:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Sorry, I ran into an internal error creating the task. Please try again in a minute.",
            )
        except Exception:
            logger.warning("twig_error_notification_failed", channel=channel, thread_ts=thread_ts)
        return

    logger.info(
        "twig_task_created",
        team_id=integration.team_id,
        repository=repository,
        channel=channel,
        thread_ts=thread_ts,
    )


def _picker_context_cache_key(context_token: str) -> str:
    token_hash = hashlib.sha256(context_token.encode("utf-8")).hexdigest()
    return f"twig_repo_picker_ctx:{token_hash}"


def _decode_picker_context(context_token: str) -> dict[str, Any] | None:
    if not context_token:
        return None

    cached = cache.get(_picker_context_cache_key(context_token))
    if isinstance(cached, dict):
        return cached

    # Backward-compat for older tests/keys using raw token in cache key.
    if len(context_token) < 120:
        cached = cache.get(f"twig_repo_picker_ctx:{context_token}")
    if isinstance(cached, dict):
        return cached

    try:
        decoded = signing.loads(context_token, salt=PICKER_TOKEN_SALT, max_age=PICKER_TOKEN_MAX_AGE_SECONDS)
        if isinstance(decoded, dict):
            return decoded
    except signing.SignatureExpired:
        return None
    except signing.BadSignature:
        pass

    return None


def handle_twig_app_mention(event: dict, integration: Integration) -> None:
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

    event_ts = event.get("ts", "")
    dedup_key = f"twig_mention:{integration.integration_id}:{channel}:{event_ts}"
    if not cache.add(dedup_key, True, timeout=300):
        logger.info("twig_mention_dedup", dedup_key=dedup_key)
        return

    logger.info(
        "twig_event_received",
        channel=channel,
        user=slack_user_id,
        thread_ts=thread_ts,
        team_id=integration.team_id,
    )

    try:
        slack = SlackIntegration(integration)

        user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
        if not user_context:
            return

        default_repo_command = _parse_default_repo_command(event.get("text", ""))
        if default_repo_command:
            all_repos = _get_full_repo_names(integration)

            if default_repo_command.action == "show":
                default_repo = _get_user_default_repo(integration.team_id, user_context.user.id)
                if default_repo:
                    slack.client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"Your default repository is `{default_repo}`.",
                    )
                else:
                    slack.client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text="You don't have a default repository set. Use `@Twig default repo set org/repo`.",
                    )
                return

            if default_repo_command.action == "clear":
                cleared = _clear_user_default_repo(integration.team_id, user_context.user.id)
                text = "Cleared your default repository." if cleared else "You don't have a default repository set."
                slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
                return

            command_repo = default_repo_command.repository or ""
            if default_repo_command.action == "set" and not command_repo:
                if not all_repos:
                    slack.client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text="I couldn't find any connected GitHub repositories for this project.",
                    )
                    return

                _post_repo_picker_message(
                    slack=slack,
                    integration=integration,
                    channel=channel,
                    thread_ts=thread_ts,
                    slack_user_id=slack_user_id,
                    event_text=event.get("text", ""),
                    user_message_ts=event.get("ts"),
                    guidance=(
                        "Pick a default repository for future generic requests. "
                        "You can still override by explicitly writing `org/repo` in a task request."
                    ),
                    action_id="twig_default_repo_select",
                )
                return

            if not all_repos:
                slack.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="I couldn't find any connected GitHub repositories for this project.",
                )
                return

            explicit_repo = _extract_explicit_repo(command_repo, all_repos)
            if not explicit_repo:
                slack.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="That repository is not connected to this project. Use `@Twig default repo show` to inspect current setting.",
                )
                return

            _set_user_default_repo(integration.team_id, user_context.user.id, explicit_repo)
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"Set your default repository to `{explicit_repo}`.",
            )
            return

        auth_response = slack.client.auth_test()
        our_bot_id = auth_response.get("bot_id")

        thread_messages = _collect_thread_messages(slack, channel, thread_ts, our_bot_id)
        if not thread_messages:
            return

        all_repos = _get_full_repo_names(integration)
        decision = select_repository(
            event_text=event.get("text", ""),
            thread_messages=thread_messages,
            integration=integration,
            user=user_context.user,
            all_repos=all_repos,
        )
        logger.info(
            "twig_repo_decision",
            mode=decision.mode,
            repository=decision.repository,
            reason=decision.reason,
            llm_called=decision.llm_called,
            repo_count=len(all_repos),
            team_id=integration.team_id,
            channel=channel,
        )

        if decision.mode == "picker":
            if decision.reason == "no_repos":
                slack.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="I couldn't find any connected GitHub repositories. Please make sure a GitHub integration is set up in your PostHog project.",
                )
                return

            guidance = (
                "Please select the repository for this task. "
                "Or @mention me again and include the exact repository as `org/repo`. "
                "You can also set a default with `@Twig default repo set` or `@Twig default repo set org/repo`."
            )
            _post_repo_picker_message(
                slack=slack,
                integration=integration,
                channel=channel,
                thread_ts=thread_ts,
                slack_user_id=slack_user_id,
                event_text=event.get("text", ""),
                user_message_ts=event.get("ts"),
                guidance=guidance,
                action_id="twig_repo_select",
            )
            return

        repository = decision.repository
        if not repository:
            return

        _create_task_for_repo(
            repository=repository,
            integration=integration,
            slack=slack,
            channel=channel,
            thread_ts=thread_ts,
            user_message_ts=event.get("ts"),
            event_text=event.get("text", ""),
            thread_messages=thread_messages,
            user_id=user_context.user.id,
            slack_user_id=slack_user_id,
        )

    except Exception as e:
        logger.exception("twig_app_mention_failed", error=str(e))


@csrf_exempt
def twig_event_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        twig_config = SlackIntegration.twig_slack_config()
        validate_slack_request(request, twig_config["SLACK_TWIG_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("twig_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("twig_event_retry", retry_num=retry_num)
        return HttpResponse(status=200)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    event_type = data.get("type")

    if event_type == "url_verification":
        challenge = data.get("challenge", "")
        return JsonResponse({"challenge": challenge})

    if event_type == "event_callback":
        event = data.get("event", {})
        slack_team_id = data.get("team_id", "")

        if event.get("type") == "app_mention":
            result = route_twig_event_to_relevant_region(request, event, slack_team_id)
            if result == ROUTE_PROXY_FAILED:
                return HttpResponse(status=502)

        return HttpResponse(status=202)

    # twig_event_handler: unrecognized event type
    return HttpResponse(status=200)


def _extract_context_token(payload: dict) -> str:
    """Extract the context token from a block_id (block_suggestion) or message metadata (block_actions)."""

    def token_from_block_id(raw_block_id: str) -> str:
        if not raw_block_id:
            return ""
        if raw_block_id.startswith("twig_repo_picker_v2:"):
            parts = raw_block_id.split(":", 3)
            return parts[3] if len(parts) == 4 else ""
        if ":" in raw_block_id:
            return raw_block_id.split(":", 1)[1]
        return ""

    # block_suggestion: block_id is at top level
    block_id = payload.get("block_id", "")
    token = token_from_block_id(block_id)
    if token:
        return token

    # block_actions: block_id is inside each action
    for action in payload.get("actions", []):
        action_block_id = action.get("block_id", "")
        token = token_from_block_id(action_block_id)
        if token:
            return token

    # fallback: message metadata
    return payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("context_token", "")


def _extract_picker_hints(payload: dict) -> tuple[int | None, str | None]:
    """Extract integration_id and mentioning user id from block_id for fallback handling."""
    block_id = payload.get("block_id", "")
    if not block_id:
        actions = payload.get("actions", [])
        if actions:
            block_id = actions[0].get("block_id", "")

    if not block_id.startswith("twig_repo_picker_v2:"):
        return None, None

    parts = block_id.split(":", 3)
    if len(parts) != 4:
        return None, None

    try:
        integration_id = int(parts[1])
    except ValueError:
        return None, None

    mentioning_slack_user_id = parts[2]
    return integration_id, mentioning_slack_user_id


def _extract_terminate_hints(payload: dict) -> tuple[int | None, str | None]:
    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "twig_terminate_task"), None)
    if not action:
        return None, None

    value_raw = action.get("value", "")
    if not value_raw:
        return None, None

    try:
        value = json.loads(value_raw)
    except json.JSONDecodeError:
        return None, None

    integration_id = value.get("integration_id")
    mentioning_user_id = value.get("mentioning_slack_user_id")
    if not isinstance(integration_id, int):
        return None, None
    if mentioning_user_id is not None and not isinstance(mentioning_user_id, str):
        mentioning_user_id = None
    return integration_id, mentioning_user_id


def _handle_repo_picker_options(payload: dict) -> JsonResponse:
    """Return filtered repo options for the external_select picker."""
    action = payload.get("action_id") or (payload.get("actions", [{}])[0].get("action_id", ""))
    if action not in {"twig_repo_select", "twig_default_repo_select"}:
        return JsonResponse({"options": []})

    context_token = _extract_context_token(payload)
    slack_team_id = payload.get("team", {}).get("id")
    if not slack_team_id:
        logger.info("twig_repo_picker_options_missing_slack_team")
        return JsonResponse({"options": []})
    if not context_token:
        logger.info("twig_repo_picker_options_missing_token")
        return JsonResponse({"options": []})

    ctx = _decode_picker_context(context_token)
    hinted_integration_id, hinted_user_id = _extract_picker_hints(payload)
    if not ctx and not hinted_integration_id:
        team_id = payload.get("team", {}).get("id")
        if team_id:
            fallback_integration = (
                Integration.objects.filter(kind="slack-twig", integration_id=team_id).order_by("id").first()
            )
            if fallback_integration:
                hinted_integration_id = fallback_integration.id
                logger.info(
                    "twig_repo_picker_options_fallback_team",
                    context_token=context_token,
                    team_id=team_id,
                    integration_id=hinted_integration_id,
                )

    if not ctx and not hinted_integration_id:
        logger.info("twig_repo_picker_options_no_context", context_token=context_token)
        return JsonResponse({"options": []})

    requesting_user = payload.get("user", {}).get("id", "")
    expected_user = ctx["mentioning_slack_user_id"] if ctx else hinted_user_id
    if expected_user and requesting_user != expected_user:
        logger.info(
            "twig_repo_picker_options_user_mismatch",
            context_token=context_token,
            requesting_user=requesting_user,
            expected_user=expected_user,
        )
        return JsonResponse({"options": []})

    if not expected_user:
        logger.info("twig_repo_picker_options_missing_expected_user", context_token=context_token)

    try:
        integration_id = ctx["integration_id"] if ctx else hinted_integration_id
        integration = Integration.objects.get(id=integration_id, kind="slack-twig", integration_id=slack_team_id)
    except Integration.DoesNotExist:
        logger.info("twig_repo_picker_options_no_integration", context_token=context_token)
        return JsonResponse({"options": []})

    all_repos = _get_full_repo_names(integration)
    if not all_repos:
        logger.info("twig_repo_picker_options_no_repos", context_token=context_token, integration_id=integration.id)
        return JsonResponse({"options": []})

    query = (payload.get("value") or "").lower()
    filtered = [r for r in all_repos if query in r.lower()] if query else all_repos

    options = [{"text": {"type": "plain_text", "text": r}, "value": r} for r in filtered[:25]]
    return JsonResponse({"options": options})


def _handle_repo_picker_submit(payload: dict) -> HttpResponse:
    """Dispatch the repo selection to a Celery task and return 200 immediately."""
    from products.slack_app.backend.tasks import process_twig_repo_selection

    process_twig_repo_selection.delay(payload)
    return HttpResponse(status=200)


def _handle_terminate_task_submit(payload: dict) -> HttpResponse:
    """Dispatch task termination to Celery and return 200 immediately."""
    from products.slack_app.backend.tasks import process_twig_task_termination

    process_twig_task_termination.delay(payload)
    return HttpResponse(status=200)


@csrf_exempt
def twig_interactivity_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        twig_config = SlackIntegration.twig_slack_config()
        validate_slack_request(request, twig_config["SLACK_TWIG_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("twig_interactivity_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    payload_type = payload.get("type")
    context_token = _extract_context_token(payload)
    logger.info(
        "twig_interactivity_received",
        payload_type=payload_type,
        context_token=context_token,
        host=request.get_host(),
    )

    # Check if we own this context locally
    context = _decode_picker_context(context_token) if context_token else None
    hinted_integration_id, hinted_user_id = _extract_picker_hints(payload)
    terminate_integration_id, terminate_user_id = _extract_terminate_hints(payload)
    requesting_user = payload.get("user", {}).get("id", "")
    slack_team_id = payload.get("team", {}).get("id")

    local = False
    if slack_team_id and context:
        local = Integration.objects.filter(
            id=context.get("integration_id"), kind="slack-twig", integration_id=slack_team_id
        ).exists()
    elif slack_team_id and hinted_integration_id and hinted_user_id and requesting_user == hinted_user_id:
        local = Integration.objects.filter(
            id=hinted_integration_id, kind="slack-twig", integration_id=slack_team_id
        ).exists()
    elif slack_team_id and terminate_integration_id and (not terminate_user_id or requesting_user == terminate_user_id):
        local = Integration.objects.filter(
            id=terminate_integration_id, kind="slack-twig", integration_id=slack_team_id
        ).exists()

    logger.info(
        "twig_interactivity_resolution",
        context_token_present=bool(context_token),
        has_context=bool(context),
        hinted_integration_id=hinted_integration_id,
        terminate_integration_id=terminate_integration_id,
        requesting_user=requesting_user,
        hinted_user=hinted_user_id,
        terminate_user=terminate_user_id,
        local=local,
        host=request.get_host(),
    )

    if not local and request.get_host() == SLACK_PRIMARY_REGION_DOMAIN:
        # Proxy to secondary and relay its response back to Slack
        upstream = _proxy_to_secondary(request)
        if upstream is not None:
            return HttpResponse(
                upstream.content,
                status=upstream.status_code,
                content_type=upstream.headers.get("Content-Type", "application/json"),
            )
        # Proxy failed — return safe defaults
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=502)

    if not local:
        logger.warning("twig_interactivity_no_context", context_token=context_token)
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=200)

    # Handled locally
    if payload_type == "block_suggestion":
        return _handle_repo_picker_options(payload)

    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            if action.get("action_id") in {"twig_repo_select", "twig_default_repo_select"}:
                return _handle_repo_picker_submit(payload)
            if action.get("action_id") == "twig_terminate_task":
                return _handle_terminate_task_submit(payload)

    return HttpResponse(status=200)
