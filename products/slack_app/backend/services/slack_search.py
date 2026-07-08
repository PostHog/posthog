"""Best-effort wrappers around Slack's Real-time Search API (``assistant.search.context``).

Bot-token calls need two things that may be absent on any given workspace: the
``search:read.public`` OAuth scope (granted only once the workspace approves an updated app
manifest) and a fresh ``action_token``, which Slack attaches only to inbound message /
app_mention events. Both are treated as strictly optional — every helper here degrades to
"no results", so callers (persona detection, tool detection) never hard-depend on search.
"""

from __future__ import annotations

import time

from django.core.cache import cache

import structlog

from posthog.models.integration import SlackIntegration

logger = structlog.get_logger(__name__)

SEARCH_SCOPES = frozenset({"search:read.public"})
# Slack doesn't document action-token lifetime; treat it as short-lived.
ACTION_TOKEN_TTL_SECONDS = 600


def _action_token_cache_key(workspace_id: str, slack_user_id: str) -> str:
    return f"slack_search_action_token:{workspace_id}:{slack_user_id}"


def cache_action_token(workspace_id: str, slack_user_id: str, action_token: str) -> None:
    cache.set(_action_token_cache_key(workspace_id, slack_user_id), action_token, timeout=ACTION_TOKEN_TTL_SECONDS)


def cache_action_token_from_event(workspace_id: str, event: dict) -> None:
    """Stash the search action token Slack attaches to message/app_mention events, keyed by author.

    The field is only present when the workspace has granted the search scopes; absence is the
    normal case and a silent no-op.
    """
    token = event.get("action_token")
    slack_user_id = event.get("user")
    if isinstance(token, str) and token and isinstance(slack_user_id, str) and slack_user_id:
        cache_action_token(workspace_id, slack_user_id, token)


def get_cached_action_token(workspace_id: str, slack_user_id: str) -> str | None:
    value = cache.get(_action_token_cache_key(workspace_id, slack_user_id))
    return value if isinstance(value, str) and value else None


def search_available(slack: SlackIntegration, action_token: str | None) -> bool:
    """True only with both a fresh action token and the search scope. Callers fetch the token
    once via ``get_cached_action_token`` and pass it in; a missing token or scope-check failure
    counts as unavailable."""
    if action_token is None:
        return False
    try:
        return not slack.missing_scopes(SEARCH_SCOPES)
    except Exception:
        logger.warning("slack_search_scope_check_failed", exc_info=True)
        return False


def search_messages(
    slack: SlackIntegration,
    *,
    action_token: str,
    query: str,
    after_days: int = 90,
    limit: int = 20,
) -> list[dict]:
    """Public-channel message search. Returns raw result message dicts, or ``[]`` on ANY failure
    (missing scope, expired token, rate limit, malformed response) — search is always best-effort."""
    try:
        response = slack.client.api_call(
            "assistant.search.context",
            params={
                "query": query,
                "action_token": action_token,
                "channel_types": "public_channel",
                "content_types": "messages",
                "after": int(time.time()) - after_days * 86400,
                "limit": limit,
            },
        )
        results = response.get("results") or {}
        messages = results.get("messages")
        return messages if isinstance(messages, list) else []
    except Exception:
        logger.warning("slack_search_messages_failed", query=query, exc_info=True)
        return []
