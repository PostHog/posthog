import re
import json
import time
import uuid
import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import requests
import structlog
import posthoganalytics
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.llm.gateway_client import get_llm_client
from posthog.models.integration import (
    GitHubIntegration,
    Integration,
    SlackIntegration,
    SlackIntegrationError,
    validate_slack_request,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.temporal.ai.posthog_code_slack_interactivity import (
    PostHogCodeSlackInteractivityInputs,
    PostHogCodeSlackTerminateTaskWorkflow,
)
from posthog.temporal.ai.posthog_code_slack_mention import (
    PostHogCodeSlackMentionWorkflow,
    PostHogCodeSlackMentionWorkflowInputs,
)
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions
from posthog.utils import get_instance_region

from products.slack_app.backend.slack_link_unfurl import handle_posthog_link_unfurl

logger = structlog.get_logger(__name__)

HANDLED_EVENT_TYPES = ["app_mention", "link_shared"]

POSTHOG_CODE_SLACK_AVAILABILITY_FLAG = "posthog-code-slack-availability"

ROUTE_HANDLED_LOCALLY = "handled_locally"
ROUTE_PROXIED = "proxied"
ROUTE_PROXY_FAILED = "proxy_failed"
ROUTE_NO_INTEGRATION = "no_integration"

PICKER_TOKEN_SALT = "posthog_code_repo_picker"
PICKER_TOKEN_MAX_AGE_SECONDS = 900
SLACK_USER_INFO_CACHE_TTL_SECONDS = 600

_MAX_GITHUB_REPOS = 500
REPO_LIST_CACHE_TTL_SECONDS = 300
PENDING_REPO_PICKER_TTL_SECONDS = PICKER_TOKEN_MAX_AGE_SECONDS


def _repo_list_cache_key(team_id: int) -> str:
    return f"posthog_code:repo_list:v1:{team_id}"


def _invalidate_repo_list_cache(team_id: int) -> None:
    cache.delete(_repo_list_cache_key(team_id))


def _pending_repo_picker_cache_key(integration_id: int, channel: str, thread_ts: str, slack_user_id: str) -> str:
    raw_key = f"{integration_id}:{channel}:{thread_ts}:{slack_user_id}"
    return f"posthog_code:pending_repo_picker:v1:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}"


def _set_pending_repo_picker(
    *,
    integration_id: int,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    workflow_id: str,
    context_token: str,
    message_ts: str | None,
) -> None:
    cache.set(
        _pending_repo_picker_cache_key(integration_id, channel, thread_ts, slack_user_id),
        {
            "workflow_id": workflow_id,
            "context_token": context_token,
            "message_ts": message_ts,
        },
        timeout=PENDING_REPO_PICKER_TTL_SECONDS,
    )


def _get_pending_repo_picker(
    *, integration_id: int, channel: str, thread_ts: str, slack_user_id: str
) -> dict[str, Any] | None:
    cached = cache.get(_pending_repo_picker_cache_key(integration_id, channel, thread_ts, slack_user_id))
    return cached if isinstance(cached, dict) else None


def _clear_pending_repo_picker(*, integration_id: int, channel: str, thread_ts: str, slack_user_id: str) -> None:
    cache.delete(_pending_repo_picker_cache_key(integration_id, channel, thread_ts, slack_user_id))


@dataclass
class SlackUserContext:
    user: User
    slack_email: str


@dataclass
class RepoDecision:
    mode: Literal["auto", "picker"]
    repository: str | None
    reason: str
    llm_found_match: bool


@dataclass
class RulesCommand:
    action: Literal["list", "add", "remove", "help", "default_set", "default_show", "default_clear"]
    rule_text: str | None = None
    repository: str | None = None
    rule_numbers: list[int] | None = None


def _slack_user_info_cache_key(integration_id: int, slack_user_id: str) -> str:
    return f"posthog_code_slack_user_info:{integration_id}:{slack_user_id}"


def _format_slack_user_info_payload(*, email: str | None, display_name: str, real_name: str) -> dict[str, Any]:
    return {
        "user": {
            "profile": {
                "email": email,
                "display_name": display_name,
                "real_name": real_name,
            }
        }
    }


def _normalize_slack_response(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return data

    return {}


def _get_slack_user_info_from_db(integration: Integration, slack_user_id: str) -> dict[str, Any] | None:
    from products.slack_app.backend.models import SlackUserProfileCache

    try:
        profile = SlackUserProfileCache.objects.filter(
            integration_id=integration.id, slack_user_id=slack_user_id
        ).first()
    except DatabaseError:
        logger.warning("posthog_code_slack_user_cache_db_unavailable", integration_id=integration.id)
        return None
    if not profile:
        return None

    return _format_slack_user_info_payload(
        email=profile.email,
        display_name=profile.display_name,
        real_name=profile.real_name,
    )


def _persist_slack_user_info(integration: Integration, slack_user_id: str, user_info: dict[str, Any]) -> None:
    from products.slack_app.backend.models import SlackUserProfileCache

    profile = user_info.get("user", {}).get("profile", {})
    try:
        SlackUserProfileCache.objects.update_or_create(
            integration_id=integration.id,
            slack_user_id=slack_user_id,
            defaults={
                "email": profile.get("email") or None,
                "display_name": profile.get("display_name") or "",
                "real_name": profile.get("real_name") or "",
            },
        )
    except DatabaseError:
        logger.warning("posthog_code_slack_user_cache_db_unavailable", integration_id=integration.id)


def _get_slack_user_info(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> dict[str, Any]:
    cache_key = _slack_user_info_cache_key(integration.id, slack_user_id)
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    cached_db = _get_slack_user_info_from_db(integration, slack_user_id)
    if isinstance(cached_db, dict):
        cache.set(cache_key, cached_db, timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return cached_db

    user_info = _normalize_slack_response(slack.client.users_info(user=slack_user_id))
    if user_info:
        _persist_slack_user_info(integration, slack_user_id, user_info)
        cache.set(cache_key, user_info, timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return user_info
    return {}


def _post_slack_user_feedback(
    slack: SlackIntegration,
    channel: str,
    slack_user_id: str,
    thread_ts: str,
    text: str,
    *,
    prefer_thread_message: bool = False,
) -> None:
    if prefer_thread_message:
        try:
            slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
            return
        except Exception:
            logger.warning("slack_user_feedback_thread_post_failed", channel=channel, slack_user_id=slack_user_id)

    try:
        slack.client.chat_postEphemeral(channel=channel, user=slack_user_id, thread_ts=thread_ts, text=text)
    except Exception:
        try:
            slack.client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)
        except Exception:
            logger.warning("slack_user_feedback_failed", channel=channel, slack_user_id=slack_user_id)


def resolve_slack_user(
    slack: SlackIntegration,
    integration: Integration,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    *,
    post_feedback: bool = True,
) -> SlackUserContext | None:
    """Resolve a Slack user to a PostHog user. Posts an ephemeral error message and returns None on failure (unless post_feedback is False)."""
    try:
        slack_user_info = _get_slack_user_info(slack, integration, slack_user_id)
        slack_email = slack_user_info.get("user", {}).get("profile", {}).get("email")
        if not slack_email:
            fresh_user_info = _normalize_slack_response(slack.client.users_info(user=slack_user_id))
            if fresh_user_info:
                _persist_slack_user_info(integration, slack_user_id, fresh_user_info)
                cache.set(
                    _slack_user_info_cache_key(integration.id, slack_user_id),
                    fresh_user_info,
                    timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS,
                )
                slack_email = fresh_user_info.get("user", {}).get("profile", {}).get("email")

        if not slack_email:
            logger.exception("slack_app_no_user_email", slack_user_id=slack_user_id)
            if post_feedback:
                _post_slack_user_feedback(
                    slack,
                    channel,
                    slack_user_id,
                    thread_ts,
                    (
                        "Sorry, I couldn't find your email address in Slack. "
                        "Please make sure your email is visible in your Slack profile, "
                        "and contact the PostHog team if the issue persists."
                    ),
                    prefer_thread_message=True,
                )
            return None

        if get_instance_region() == "DEV":
            # Dev region override for testing on any workspace (for Slack review team)
            slack_email = "twixes3d+slacktest@gmail.com"

        # Trust model: Slack signature validation proves the payload is authentic.
        # The email comes from Slack's `users.info` API via `users:read.email` scope, not from
        # user-supplied input. Slack verifies emails at workspace sign-up, and admins control
        # membership
        membership = (
            OrganizationMembership.objects.filter(
                organization_id=integration.team.organization_id, user__email=slack_email
            )
            .select_related("user")
            .first()
        )
        if not membership or not membership.user:
            organization_name = integration.team.organization.name
            if post_feedback:
                _post_slack_user_feedback(
                    slack,
                    channel,
                    slack_user_id,
                    thread_ts,
                    (
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
            if post_feedback:
                _post_slack_user_feedback(
                    slack,
                    channel,
                    slack_user_id,
                    thread_ts,
                    (
                        "Sorry, you don't have access to the PostHog project connected to this Slack workspace. "
                        "Please ask an admin of your PostHog organization to grant you access."
                    ),
                )
            return None

        return SlackUserContext(user=posthog_user, slack_email=slack_email)
    except Exception as e:
        logger.exception("slack_app_user_lookup_failed", error=str(e))
        if post_feedback:
            _post_slack_user_feedback(
                slack,
                channel,
                slack_user_id,
                thread_ts,
                "Sorry, I encountered an error looking up your user account. Please try again later.",
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


def _proxy_to_secondary(request: HttpRequest) -> requests.Response | None:
    """Proxy a request to the secondary region, returning the upstream response or None on failure."""
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


def _build_slack_thread_key(slack_workspace_id: str, channel: str, thread_ts: str) -> str:
    """Build the unique key for a Slack thread."""
    return f"{slack_workspace_id}:{channel}:{thread_ts}"


def _strip_bot_mentions(text: str) -> str:
    """Remove all <@BOT_ID> mentions from text."""
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _parse_rules_command(text: str) -> RulesCommand | None:
    cleaned = _strip_bot_mentions(text).strip()
    if not cleaned:
        return None

    list_match = re.fullmatch(r"rules\s+list", cleaned, flags=re.IGNORECASE)
    if list_match:
        return RulesCommand(action="list")

    add_with_repo_match = re.fullmatch(
        r'rules\s+add\s+"([^"]+)"\s+([\w.-]+/[\w.-]+)',
        cleaned,
        flags=re.IGNORECASE,
    )
    if add_with_repo_match:
        return RulesCommand(
            action="add", rule_text=add_with_repo_match.group(1), repository=add_with_repo_match.group(2)
        )

    add_no_repo_match = re.fullmatch(
        r'rules\s+add\s+"([^"]+)"',
        cleaned,
        flags=re.IGNORECASE,
    )
    if add_no_repo_match:
        return RulesCommand(action="add", rule_text=add_no_repo_match.group(1))

    remove_match = re.fullmatch(r"rules\s+remove\s+([\d,\s]+)", cleaned, flags=re.IGNORECASE)
    if remove_match:
        numbers = [int(n.strip()) for n in remove_match.group(1).split(",") if n.strip().isdigit()]
        if numbers:
            return RulesCommand(action="remove", rule_numbers=numbers)

    default_set_match = re.fullmatch(
        r"default\s+repo\s+set\s+([\w.-]+/[\w.-]+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if default_set_match:
        return RulesCommand(action="default_set", repository=default_set_match.group(1))

    if re.fullmatch(r"default\s+repo\s+show", cleaned, flags=re.IGNORECASE):
        return RulesCommand(action="default_show")

    if re.fullmatch(r"default\s+repo\s+clear", cleaned, flags=re.IGNORECASE):
        return RulesCommand(action="default_clear")

    if re.fullmatch(r"help", cleaned, flags=re.IGNORECASE):
        return RulesCommand(action="help")

    return None


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
    workflow_id: str | None = None,
    allow_no_repo: bool = False,
) -> None:
    context_data = {
        "integration_id": integration.id,
        "channel": channel,
        "thread_ts": thread_ts,
        "user_message_ts": user_message_ts,
        "mentioning_slack_user_id": slack_user_id,
        "event_text": event_text,
        "created_at": int(time.time()),
        "workflow_id": workflow_id,
    }
    context_token = uuid.uuid4().hex
    cache.set(_picker_context_cache_key(context_token), context_data, timeout=PICKER_TOKEN_MAX_AGE_SECONDS)

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "block_id": f"posthog_code_repo_picker_v2:{integration.id}:{slack_user_id}:{context_token}",
            "text": {"type": "mrkdwn", "text": guidance},
            "accessory": {
                "type": "external_select",
                "action_id": action_id,
                "placeholder": {"type": "plain_text", "text": "Search GitHub repositories..."},
                "min_query_length": 0,
            },
        }
    ]

    if allow_no_repo:
        blocks.append(
            {
                "type": "actions",
                "block_id": f"posthog_code_repo_picker_v2:{integration.id}:{slack_user_id}:{context_token}:actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "posthog_code_repo_none",
                        "text": {"type": "plain_text", "text": "No repo needed"},
                        "style": "primary",
                        "value": "no_repo_needed",
                    }
                ],
            }
        )

    response = slack.client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=guidance,
        blocks=blocks,
        metadata={
            "event_type": "posthog_code_repo_picker",
            "event_payload": {"context_token": context_token, "workflow_id": workflow_id},
        },
    )

    if workflow_id:
        response_data = _normalize_slack_response(response)
        message_ts = response_data.get("ts") if isinstance(response_data.get("ts"), str) else None
        _set_pending_repo_picker(
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
            workflow_id=workflow_id,
            context_token=context_token,
            message_ts=message_ts,
        )

    # Pre-warm the repo list cache so the external_select options request
    # is served from cache rather than hitting the GitHub API inline.
    # Non-fatal: the dropdown will still work, it will just fetch on demand.
    try:
        _get_full_repo_names(integration)
    except Exception:
        logger.warning("repo_list_prewarm_failed", team_id=integration.team_id, exc_info=True)


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
    slack: SlackIntegration, integration: Integration, channel: str, thread_ts: str, our_bot_id: str | None
) -> list[dict[str, str]]:
    """Fetch thread messages, strip bot mentions, and resolve user display names."""
    thread_response = slack.client.conversations_replies(channel=channel, ts=thread_ts)
    raw_messages: list[dict] = thread_response.get("messages", [])

    user_cache: dict[str, str] = {}

    def resolve_user(uid: str) -> str:
        if uid not in user_cache:
            try:
                user_info = _get_slack_user_info(slack, integration, uid)
                profile = user_info.get("user", {}).get("profile", {})
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
    """Return canonical org/repo names across all GitHub integrations for the team, or [] if unavailable."""
    cache_key = _repo_list_cache_key(integration.team_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    github_records = Integration.objects.filter(team=integration.team, kind="github")
    if not github_records.exists():
        cache.set(cache_key, [], timeout=REPO_LIST_CACHE_TTL_SECONDS)
        return []

    all_repos: set[str] = set()

    for record in github_records:
        github = GitHubIntegration(record)
        repo_entries = github.list_all_cached_repositories(max_repos=_MAX_GITHUB_REPOS)
        for repo in repo_entries:
            all_repos.add(repo["full_name"])
            if len(all_repos) >= _MAX_GITHUB_REPOS:
                logger.warning(
                    "github_repo_list_capped",
                    team_id=integration.team_id,
                    cap=_MAX_GITHUB_REPOS,
                )
                result = sorted(all_repos)
                cache.set(cache_key, result, timeout=REPO_LIST_CACHE_TTL_SECONDS)
                return result

    result = sorted(all_repos)
    if result:
        cache.set(cache_key, result, timeout=REPO_LIST_CACHE_TTL_SECONDS)
    return result


def select_repository(
    event_text: str,
    thread_messages: list[dict[str, str]],
    integration: Integration,
    all_repos: list[str],
    user_id: int | None = None,
    channel: str = "",
) -> RepoDecision:
    if not all_repos:
        return RepoDecision(mode="picker", repository=None, reason="no_repos", llm_found_match=False)

    if len(all_repos) == 1:
        return RepoDecision(mode="auto", repository=all_repos[0], reason="single_repo", llm_found_match=False)

    explicit_repo = _extract_explicit_repo(event_text, all_repos)
    if explicit_repo:
        return RepoDecision(mode="auto", repository=explicit_repo, reason="explicit_mention", llm_found_match=False)

    if user_id and channel:
        from posthog.models.user_repo_preference import UserRepoPreference

        default = UserRepoPreference.get_default(
            team_id=integration.team_id,
            user_id=user_id,
            scope_type="slack_channel",
            scope_id=channel,
        )
        if default and default in all_repos:
            return RepoDecision(mode="auto", repository=default, reason="user_default", llm_found_match=False)

    matched = _match_repo_rule(event_text, thread_messages, integration.team_id, all_repos)
    if matched:
        return RepoDecision(mode="auto", repository=matched, reason="rule_match", llm_found_match=True)

    return RepoDecision(mode="picker", repository=None, reason="no_rule_match", llm_found_match=False)


def _replace_repo_picker_message_with_selection(
    *,
    integration_id: int,
    slack_team_id: str,
    channel: str,
    message_ts: str,
    selected_repo: str,
) -> None:
    try:
        # nosemgrep: idor-lookup-without-team — Slack webhook: no team context; scoped by PK + kind + Slack team ID
        integration = Integration.objects.get(
            id=integration_id, kind="slack-posthog-code", integration_id=slack_team_id
        )
        slack = SlackIntegration(integration)
        text = f"Repository selected: `{selected_repo}`"
        slack.client.chat_update(
            channel=channel,
            ts=message_ts,
            text=text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Repository selected:* `{selected_repo}`"},
                }
            ],
        )
    except Exception:
        logger.warning(
            "posthog_code_repo_submit_picker_update_failed",
            integration_id=integration_id,
            channel=channel,
            message_ts=message_ts,
        )


def _replace_repo_picker_message_with_no_repo(
    *,
    integration_id: int,
    slack_team_id: str,
    channel: str,
    message_ts: str,
) -> None:
    try:
        # nosemgrep: idor-lookup-without-team — Slack webhook: no team context; scoped by PK + kind + Slack team ID
        integration = Integration.objects.get(
            id=integration_id, kind="slack-posthog-code", integration_id=slack_team_id
        )
        slack = SlackIntegration(integration)
        text = "Continuing without a repository."
        slack.client.chat_update(
            channel=channel,
            ts=message_ts,
            text=text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Continuing without a repository.*"},
                }
            ],
        )
    except Exception:
        logger.warning(
            "posthog_code_repo_none_picker_update_failed",
            integration_id=integration_id,
            channel=channel,
            message_ts=message_ts,
        )


def _resolve_pending_repo_picker_from_followup(event: dict[str, Any], integration: Integration) -> bool:
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    slack_user_id = event.get("user")
    if not channel or not thread_ts or not slack_user_id:
        return False

    pending_picker = _get_pending_repo_picker(
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
    )
    if not pending_picker:
        return False

    workflow_id = pending_picker.get("workflow_id")
    if not isinstance(workflow_id, str) or not workflow_id:
        _clear_pending_repo_picker(
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )
        return False

    try:
        all_repos = _get_full_repo_names(integration)
    except Exception:
        logger.exception("posthog_code_pending_picker_repo_fetch_failed", integration_id=integration.id)
        return False

    selected_repo = _extract_explicit_repo(event.get("text", ""), all_repos)
    if not selected_repo:
        return False

    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        asyncio.run(handle.signal(PostHogCodeSlackMentionWorkflow.repo_selected, selected_repo))
    except Exception as e:
        logger.warning(
            "posthog_code_pending_picker_signal_failed",
            workflow_id=workflow_id,
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            error=str(e),
        )
        _clear_pending_repo_picker(
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            slack_user_id=slack_user_id,
        )
        return False

    _clear_pending_repo_picker(
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        slack_user_id=slack_user_id,
    )

    message_ts = pending_picker.get("message_ts")
    if isinstance(message_ts, str) and message_ts:
        _replace_repo_picker_message_with_selection(
            integration_id=integration.id,
            slack_team_id=integration.integration_id,
            channel=channel,
            message_ts=message_ts,
            selected_repo=selected_repo,
        )

    logger.info(
        "posthog_code_pending_picker_resolved_from_followup",
        workflow_id=workflow_id,
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        repository=selected_repo,
    )
    return True


def _match_repo_rule(
    event_text: str,
    thread_messages: list[dict[str, str]],
    team_id: int,
    all_repos: list[str],
) -> str | None:
    from posthog.models.repo_routing_rule import RepoRoutingRule

    rules = list(RepoRoutingRule.objects.filter(team_id=team_id).order_by("priority", "id"))
    if not rules:
        logger.info("posthog_code_rule_match_no_rules", team_id=team_id)
        return None

    _MAX_RULES_FOR_LLM = 20

    connected_set = {r.lower() for r in all_repos}
    eligible_rules = [r for r in rules if r.repository.lower() in connected_set][:_MAX_RULES_FOR_LLM]
    if not eligible_rules:
        logger.info(
            "posthog_code_rule_match_no_eligible_rules",
            team_id=team_id,
            rule_repos=[r.repository for r in rules],
            connected_repos=all_repos,
        )
        return None

    conversation = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)
    rules_block = "\n".join(f"{i}: {r.rule_text} -> {r.repository}" for i, r in enumerate(eligible_rules))

    prompt = (
        "You are a routing classifier. Given a Slack conversation and a numbered list of rules, "
        'return the JSON object {"rule_index": <int>} for the best-matching rule, '
        'or {"rule_index": null} if none match.\n\n'
        f"Rules:\n{rules_block}\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest message: {event_text}\n\n"
        "Respond with ONLY the JSON object, no other text."
    )

    try:
        client = get_llm_client("slack-posthog-code")
        response = client.chat.completions.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown code fences if the LLM wrapped the response
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        logger.info("posthog_code_rule_match_llm_response", content=content, team_id=team_id)
        parsed = json.loads(content)
        idx = parsed.get("rule_index")
        if idx is None:
            logger.info("posthog_code_rule_match_llm_returned_null", team_id=team_id)
            return None
        if not isinstance(idx, int) or idx < 0 or idx >= len(eligible_rules):
            logger.warning("posthog_code_rule_match_invalid_index", index=idx, rule_count=len(eligible_rules))
            return None

        matched_repo = eligible_rules[idx].repository
        canonical = next((r for r in all_repos if r.lower() == matched_repo.lower()), None)
        if not canonical:
            logger.warning("posthog_code_rule_match_repo_not_connected", repo=matched_repo)
            return None
        logger.info("posthog_code_rule_match_success", repo=canonical, rule_index=idx, team_id=team_id)
        return canonical
    except Exception:
        logger.exception("posthog_code_rule_match_failed", team_id=team_id)
        return None


def classify_task_needs_repo(
    event_text: str,
    thread_messages: list[dict[str, str]],
) -> bool:
    """Classify whether a Slack conversation requires code repository access.

    Returns True if the task likely needs a repo (writing code, fixing bugs, PRs),
    False if it does not (analytics, data queries, PostHog config).
    Defaults to True on error (conservative — falls back to picker).
    """
    conversation = "\n".join(f"{msg['user']}: {msg['text']}" for msg in thread_messages)
    normalized = f"{conversation}\nLatest message: {event_text}".lower()

    product_debug_terms = (
        "automation",
        "destination",
        "slack destination",
        "posthog ai feedback",
        "feature flag",
        "experiment",
        "survey",
        "dashboard",
        "insight",
        "session replay",
        "recording",
        "trace",
        "mcp",
        "webhook",
    )
    explicit_code_patterns = (
        r"\brepository\b",
        r"\brepo\b",
        r"\bpull request\b",
        r"\bopen a pr\b",
        r"\bcreate a pr\b",
        r"\bcommit\b",
        r"\bbranch\b",
        r"\bmodify code\b",
        r"\bchange code\b",
        r"\bwrite code\b",
        r"\bimplement\b",
        r"\.py\b",
        r"\.ts\b",
        r"\.tsx\b",
        r"\.js\b",
        r"\bserializer\b",
        r"\bviewset\b",
        r"\bmigration\b",
    )

    if any(term in normalized for term in product_debug_terms) and not any(
        re.search(pattern, normalized) for pattern in explicit_code_patterns
    ):
        logger.info("classify_task_needs_repo_heuristic_non_repo", event_text=event_text)
        return False

    prompt = (
        "You are a task classifier. Given a Slack conversation, determine whether the task "
        "requires access to a code repository (e.g. writing code, fixing bugs, creating PRs, "
        "reviewing code, modifying files) or NOT (e.g. answering questions about analytics, "
        "querying data, PostHog configuration, general knowledge questions, planning, or "
        "investigating product behavior in a PostHog workspace using MCP/tools).\n\n"
        "Return needs_repo=false for tasks that are primarily about debugging or investigating "
        "automations, destinations, feature flags, experiments, surveys, dashboards, insights, "
        "recordings, traces, or Slack integrations inside PostHog, unless the user explicitly "
        "asks to change code, open a PR, edit files, or work in a specific repository.\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest message: {event_text}\n\n"
        'Respond with ONLY a JSON object: {{"needs_repo": true}} or {{"needs_repo": false}}'
    )
    try:
        client = get_llm_client("slack-posthog-code")
        response = client.chat.completions.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        parsed = json.loads(content)
        return bool(parsed.get("needs_repo", True))
    except Exception:
        logger.exception("classify_task_needs_repo_failed")
        return True


def _posthog_code_flag_subject(integration: Integration) -> User | None:
    """Resolve a person to evaluate the coding-agent rollout flag against.

    Prefer the installer (created_by), since that's the user who opted the org
    into the feature and usually matches the dogfood cohort. Integration.created_by
    is SET_NULL on user deletion, which would otherwise silently disable the coding
    agent for the whole workspace — fall back to any organization admin/owner so the
    feature keeps working after installer cleanup.
    """
    if integration.created_by:
        return integration.created_by
    fallback = (
        OrganizationMembership.objects.filter(
            organization_id=integration.team.organization_id,
            level__gte=OrganizationMembership.Level.ADMIN,
        )
        .select_related("user")
        .order_by("joined_at")
        .first()
    )
    return fallback.user if fallback else None


def _posthog_code_enabled_for_integration(integration: Integration) -> bool:
    """Runtime gate for the coding agent on app_mention events.

    Why: the approved Slack app is installed by many orgs for notifications; the
    coding agent should only fire for orgs in the posthog-code-slack-availability
    rollout. Evaluated against the installing user (or an org admin fallback) so
    we reuse the same cohort the rest of the codebase uses to gate the feature.

    Latency: `posthoganalytics.feature_enabled` evaluates locally from polled flag
    definitions (see `posthog/apps.py`: `personal_api_key` + `poll_interval=90`),
    so this is effectively a dict lookup — safe within Slack's 3s webhook budget.
    """
    subject = _posthog_code_flag_subject(integration)
    if not subject:
        logger.warning(
            "posthog_code_slack_flag_no_subject",
            integration_id=integration.id,
            organization_id=str(integration.team.organization_id),
        )
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                POSTHOG_CODE_SLACK_AVAILABILITY_FLAG,
                str(subject.distinct_id),
                groups={"organization": str(integration.team.organization_id)},
                person_properties={"region": get_instance_region() or "unknown"},
            )
        )
    except Exception:
        logger.exception("posthog_code_slack_flag_check_failed", integration_id=integration.id)
        return False


def route_posthog_code_event_to_relevant_region(
    request: HttpRequest,
    event: dict,
    slack_team_id: str,
    event_id: str | None = None,
) -> str:
    # One webhook endpoint serves both the notifications integration (kind="slack") and the
    # coding-agent integration (kind="slack-posthog-code"). What counts as a "local match" has
    # to depend on event type: app_mention needs the coding-agent integration specifically,
    # while link_shared (unfurl) works with either kind. Without this, a region that has only a
    # notifications install for a workspace would silently swallow mentions instead of
    # proxying to the region that holds the coding-agent install.
    integrations = list(
        Integration.objects.filter(
            kind__in=["slack", "slack-posthog-code"],
            integration_id=slack_team_id,
        )
        .select_related("team", "team__organization", "created_by")
        .order_by("id")
    )
    coding_agent_integration = next((i for i in integrations if i.kind == "slack-posthog-code"), None)
    any_integration = integrations[0] if integrations else None

    event_type = event.get("type")
    if event_type == "app_mention":
        local_match = coding_agent_integration
    else:
        local_match = any_integration

    if local_match and not (settings.DEBUG and request.get_host() == SLACK_PRIMARY_REGION_DOMAIN):
        if event_type == "app_mention":
            if not _posthog_code_enabled_for_integration(local_match):
                logger.info(
                    "posthog_code_event_flag_off",
                    slack_team_id=slack_team_id,
                    organization_id=str(local_match.team.organization_id),
                )
                return ROUTE_HANDLED_LOCALLY
            if _resolve_pending_repo_picker_from_followup(event, local_match):
                return ROUTE_HANDLED_LOCALLY
            workflow_inputs = PostHogCodeSlackMentionWorkflowInputs(
                event=event,
                integration_id=local_match.id,
                slack_team_id=slack_team_id,
            )
            event_id_or_fallback = event_id if event_id else f"{event.get('channel', '')}:{event.get('ts', '')}"
            workflow_id = f"posthog-code-mention-{slack_team_id}:{event_id_or_fallback}"
            client = sync_connect()
            asyncio.run(
                client.start_workflow(
                    PostHogCodeSlackMentionWorkflow.run,
                    workflow_inputs,
                    id=workflow_id,
                    task_queue=settings.MAX_AI_TASK_QUEUE,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                )
            )
        elif event_type == "link_shared":
            handle_posthog_link_unfurl(event, local_match)
        return ROUTE_HANDLED_LOCALLY
    elif request.get_host() == SLACK_PRIMARY_REGION_DOMAIN:
        success = proxy_slack_event_to_secondary_region(request)
        return ROUTE_PROXIED if success else ROUTE_PROXY_FAILED
    else:
        logger.warning("posthog_code_no_integration_found", slack_team_id=slack_team_id)
        return ROUTE_NO_INTEGRATION


def _picker_context_cache_key(context_token: str) -> str:
    token_hash = hashlib.sha256(context_token.encode("utf-8")).hexdigest()
    return f"posthog_code_repo_picker_ctx:{token_hash}"


def _decode_picker_context(context_token: str) -> dict[str, Any] | None:
    if not context_token:
        return None

    cached = cache.get(_picker_context_cache_key(context_token))
    if isinstance(cached, dict):
        return cached

    # Backward-compat for older tests/keys using raw token in cache key.
    if len(context_token) < 120:
        cached = cache.get(f"posthog_code_repo_picker_ctx:{context_token}")
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


@csrf_exempt
def posthog_code_event_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        posthog_code_config = SlackIntegration.posthog_code_slack_config()
        validate_slack_request(request, posthog_code_config["SLACK_POSTHOG_CODE_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("posthog_code_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("posthog_code_event_retry", retry_num=retry_num)
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
        event_id = data.get("event_id")

        if event.get("type") in HANDLED_EVENT_TYPES:
            result = route_posthog_code_event_to_relevant_region(request, event, slack_team_id, event_id=event_id)
            if result == ROUTE_PROXY_FAILED:
                return HttpResponse(status=502)

        return HttpResponse(status=202)

    # posthog_code_event_handler: unrecognized event type
    return HttpResponse(status=200)


def _extract_context_token(payload: dict) -> str:
    """Extract the context token from a block_id (block_suggestion) or message metadata (block_actions)."""

    def token_from_block_id(raw_block_id: str) -> str:
        if not raw_block_id:
            return ""
        if raw_block_id.startswith("posthog_code_repo_picker_v2:"):
            parts = raw_block_id.split(":")
            return parts[3] if len(parts) >= 4 else ""
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

    if not block_id.startswith("posthog_code_repo_picker_v2:"):
        return None, None

    parts = block_id.split(":")
    if len(parts) < 4:
        return None, None

    try:
        integration_id = int(parts[1])
    except ValueError:
        return None, None

    mentioning_slack_user_id = parts[2]
    return integration_id, mentioning_slack_user_id


def _extract_terminate_hints(payload: dict) -> tuple[int | None, str | None]:
    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "posthog_code_terminate_task"), None)
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
    if action != "posthog_code_repo_select":
        return JsonResponse({"options": []})

    context_token = _extract_context_token(payload)
    slack_team_id = payload.get("team", {}).get("id")
    if not slack_team_id:
        logger.info("posthog_code_repo_picker_options_missing_slack_team")
        return JsonResponse({"options": []})
    if not context_token:
        logger.info("posthog_code_repo_picker_options_missing_token")
        return JsonResponse({"options": []})

    ctx = _decode_picker_context(context_token)
    hinted_integration_id, hinted_user_id = _extract_picker_hints(payload)
    if not ctx and not hinted_integration_id:
        team_id = payload.get("team", {}).get("id")
        if team_id:
            fallback_integration = (
                Integration.objects.filter(kind="slack-posthog-code", integration_id=team_id).order_by("id").first()
            )
            if fallback_integration:
                hinted_integration_id = fallback_integration.id
                logger.info(
                    "posthog_code_repo_picker_options_fallback_team",
                    context_token=context_token,
                    team_id=team_id,
                    integration_id=hinted_integration_id,
                )

    if not ctx and not hinted_integration_id:
        logger.info("posthog_code_repo_picker_options_no_context", context_token=context_token)
        return JsonResponse({"options": []})

    requesting_user = payload.get("user", {}).get("id", "")
    expected_user = ctx["mentioning_slack_user_id"] if ctx else hinted_user_id
    if expected_user and requesting_user != expected_user:
        logger.info(
            "posthog_code_repo_picker_options_user_mismatch",
            context_token=context_token,
            requesting_user=requesting_user,
            expected_user=expected_user,
        )
        return JsonResponse({"options": []})

    if not expected_user:
        logger.info("posthog_code_repo_picker_options_missing_expected_user", context_token=context_token)

    try:
        integration_id: int | None = ctx["integration_id"] if ctx else hinted_integration_id
        if not integration_id:
            raise Integration.DoesNotExist
        # nosemgrep: idor-lookup-without-team — Slack webhook: no team context; scoped by PK + kind + Slack team ID
        integration = Integration.objects.get(
            id=integration_id, kind="slack-posthog-code", integration_id=slack_team_id
        )
    except Integration.DoesNotExist:
        logger.info("posthog_code_repo_picker_options_no_integration", context_token=context_token)
        return JsonResponse({"options": []})

    try:
        all_repos = _get_full_repo_names(integration)
    except Exception:
        logger.exception("twig_repo_picker_options_repo_fetch_error", integration_id=integration.id)
        return JsonResponse({"options": []})

    if not all_repos:
        logger.info(
            "posthog_code_repo_picker_options_no_repos", context_token=context_token, integration_id=integration.id
        )
        return JsonResponse({"options": []})

    query = (payload.get("value") or "").lower()
    filtered = [r for r in all_repos if query in r.lower()] if query else all_repos

    options = [{"text": {"type": "plain_text", "text": r}, "value": r} for r in filtered[:25]]
    return JsonResponse({"options": options})


def _handle_repo_picker_submit(payload: dict) -> HttpResponse:
    """Signal Temporal mention workflow for repo submit."""
    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "posthog_code_repo_select"), None)
    selected_repo = action.get("selected_option", {}).get("value") if action else None

    context_token = _extract_context_token(payload)
    context = _decode_picker_context(context_token) if context_token else None
    pending_picker_user_id = context.get("mentioning_slack_user_id") if context else None
    workflow_id = None
    if context and isinstance(context.get("workflow_id"), str):
        workflow_id = context.get("workflow_id")
    if not workflow_id:
        workflow_id = payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("workflow_id")

    def post_selection_expired() -> None:
        slack_team_id = payload.get("team", {}).get("id")
        integration_id = context.get("integration_id") if context else None
        channel = context.get("channel") if context else payload.get("channel", {}).get("id")
        thread_ts = context.get("thread_ts") if context else payload.get("message", {}).get("ts")

        if not slack_team_id or not integration_id or not channel or not thread_ts:
            logger.warning(
                "posthog_code_repo_submit_expired_feedback_missing_context",
                slack_team_id=slack_team_id,
                integration_id=integration_id,
                channel=channel,
                thread_ts=thread_ts,
            )
            return

        if isinstance(pending_picker_user_id, str) and pending_picker_user_id:
            _clear_pending_repo_picker(
                integration_id=integration_id,
                channel=channel,
                thread_ts=thread_ts,
                slack_user_id=pending_picker_user_id,
            )

        # If another workflow already created a task for this thread (e.g. the
        # user sent a follow-up message instead of using the picker), skip the
        # expired message.
        from products.slack_app.backend.models import SlackThreadTaskMapping

        if SlackThreadTaskMapping.objects.filter(
            integration_id=integration_id,
            channel=channel,
            thread_ts=thread_ts,
        ).exists():
            return

        try:
            # nosemgrep: idor-lookup-without-team — Slack webhook: no team context; scoped by PK + kind + Slack team ID
            integration = Integration.objects.get(
                id=integration_id, kind="slack-posthog-code", integration_id=slack_team_id
            )
            SlackIntegration(integration).client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Repository selection expired. Please mention PostHog again to retry.",
            )
        except Exception:
            logger.warning(
                "posthog_code_repo_submit_expired_feedback_failed",
                integration_id=integration_id,
                channel=channel,
                thread_ts=thread_ts,
            )

    if not selected_repo:
        return HttpResponse(status=200)

    if not workflow_id:
        logger.info("posthog_code_repo_submit_missing_workflow_id")
        post_selection_expired()
        return HttpResponse(status=200)

    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        asyncio.run(handle.signal(PostHogCodeSlackMentionWorkflow.repo_selected, selected_repo))
        if context and pending_picker_user_id:
            _clear_pending_repo_picker(
                integration_id=context["integration_id"],
                channel=context["channel"],
                thread_ts=context["thread_ts"],
                slack_user_id=pending_picker_user_id,
            )
        _replace_repo_picker_with_selection(payload, context, selected_repo)
        return HttpResponse(status=200)
    except Exception as e:
        logger.warning("posthog_code_repo_submit_signal_failed", workflow_id=workflow_id, error=str(e))
        post_selection_expired()
        return HttpResponse(status=200)


def _replace_repo_picker_with_selection(payload: dict, context: dict | None, selected_repo: str) -> None:
    integration_id = context.get("integration_id") if context else None
    slack_team_id = payload.get("team", {}).get("id")
    channel = context.get("channel") if context else payload.get("channel", {}).get("id")
    message_ts = payload.get("message", {}).get("ts")

    if not integration_id or not slack_team_id or not channel or not message_ts:
        logger.info(
            "posthog_code_repo_submit_missing_picker_update_context",
            integration_id=integration_id,
            slack_team_id=slack_team_id,
            channel=channel,
            message_ts=message_ts,
        )
        return

    _replace_repo_picker_message_with_selection(
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        channel=channel,
        message_ts=message_ts,
        selected_repo=selected_repo,
    )


def _handle_no_repo_needed_submit(payload: dict) -> HttpResponse:
    context_token = _extract_context_token(payload)
    context = _decode_picker_context(context_token) if context_token else None
    pending_picker_user_id = context.get("mentioning_slack_user_id") if context else None
    workflow_id = None
    if context and isinstance(context.get("workflow_id"), str):
        workflow_id = context.get("workflow_id")
    if not workflow_id:
        workflow_id = payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("workflow_id")

    if not workflow_id or not context:
        logger.info("posthog_code_repo_none_missing_workflow_id")
        return HttpResponse(status=200)

    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        asyncio.run(handle.signal(PostHogCodeSlackMentionWorkflow.no_repo_needed))
        if pending_picker_user_id:
            _clear_pending_repo_picker(
                integration_id=context["integration_id"],
                channel=context["channel"],
                thread_ts=context["thread_ts"],
                slack_user_id=pending_picker_user_id,
            )
        message_ts = payload.get("message", {}).get("ts")
        slack_team_id = payload.get("team", {}).get("id")
        if message_ts and slack_team_id:
            _replace_repo_picker_message_with_no_repo(
                integration_id=context["integration_id"],
                slack_team_id=slack_team_id,
                channel=context["channel"],
                message_ts=message_ts,
            )
        return HttpResponse(status=200)
    except Exception as e:
        logger.warning("posthog_code_repo_none_signal_failed", workflow_id=workflow_id, error=str(e))
        return HttpResponse(status=200)


def _handle_terminate_task_submit(payload: dict) -> HttpResponse:
    """Start Temporal workflow for task termination and return 200 immediately."""
    action = next((a for a in payload.get("actions", []) if a.get("action_id") == "posthog_code_terminate_task"), None)
    action_ts = action.get("action_ts") if action else ""
    team_id = payload.get("team", {}).get("id", "")
    user_id = payload.get("user", {}).get("id", "")
    workflow_id = (
        f"posthog-code-terminate-task:{team_id}:{user_id}:{action_ts or payload.get('message', {}).get('ts', '')}"
    )
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                PostHogCodeSlackTerminateTaskWorkflow.run,
                PostHogCodeSlackInteractivityInputs(payload=payload),
                id=workflow_id,
                task_queue=settings.MAX_AI_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception as e:
        logger.warning("posthog_code_terminate_submit_start_failed", workflow_id=workflow_id, error=str(e))
    return HttpResponse(status=200)


@csrf_exempt
def posthog_code_interactivity_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        posthog_code_config = SlackIntegration.posthog_code_slack_config()
        validate_slack_request(request, posthog_code_config["SLACK_POSTHOG_CODE_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("posthog_code_interactivity_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    payload_type = payload.get("type")
    context_token = _extract_context_token(payload)
    logger.info(
        "posthog_code_interactivity_received",
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
    ctx_integration_id = context.get("integration_id") if context else None
    # Slack webhook endpoint: no team context available; queries are scoped by PK + kind + workspace ID
    if slack_team_id and ctx_integration_id:
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=ctx_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind="slack-posthog-code",
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and hinted_integration_id and hinted_user_id and requesting_user == hinted_user_id:
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=hinted_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind="slack-posthog-code",
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and terminate_integration_id and (not terminate_user_id or requesting_user == terminate_user_id):
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=terminate_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind="slack-posthog-code",
            integration_id=slack_team_id,
        ).exists()

    logger.info(
        "posthog_code_interactivity_resolution",
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
        logger.warning("posthog_code_interactivity_no_context", context_token=context_token)
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=200)

    # Handled locally
    if payload_type == "block_suggestion":
        return _handle_repo_picker_options(payload)

    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            if action.get("action_id") == "posthog_code_repo_select":
                return _handle_repo_picker_submit(payload)
            if action.get("action_id") == "posthog_code_repo_none":
                return _handle_no_repo_needed_submit(payload)
            if action.get("action_id") == "posthog_code_terminate_task":
                return _handle_terminate_task_submit(payload)

    return HttpResponse(status=200)
