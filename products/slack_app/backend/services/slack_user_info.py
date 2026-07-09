"""Slack user/profile lookup with DB caching.

`users.info` and `users.lookupByEmail` are the only sources of truth for
display names, email-to-user-id mappings, and the `is_bot` flag — and both
are rate-limited. Every lookup goes through `SlackUserProfileCache` in
Postgres so repeated requests don't burn the Slack API quota.

The bot's own user id (from `auth_test()`) is folded into the shared
per-integration auth-state cache in `slack_auth`, so a successful
``auth.test`` doubles as proof the bot token works — no separate cache
shape for the bot user id alone.

These helpers used to live in `api.py` alongside the HTTP-facing code,
which forced every service-layer caller (`slack_messages.py`,
`integration_resolver.py`) into a deferred import to dodge the circular
dependency. Living in `services/` lets all of them import normally and
keeps `api.py` focused on routes.
"""

from datetime import timedelta
from typing import Any

from django.db.utils import DatabaseError
from django.utils import timezone

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services.slack_auth import (
    classify_slack_api_error,
    get_cached_auth_state,
    write_auth_state_broken,
    write_auth_state_ok,
)

logger = structlog.get_logger(__name__)

SLACK_USER_PROFILE_TTL = timedelta(hours=1)


def _format_slack_user_info_payload(
    *,
    email: str | None,
    display_name: str,
    real_name: str,
    is_admin: bool,
    is_owner: bool,
    is_bot: bool,
) -> dict[str, Any]:
    return {
        "user": {
            "is_admin": is_admin,
            "is_owner": is_owner,
            "is_bot": is_bot,
            "profile": {
                "email": email,
                "display_name": display_name,
                "real_name": real_name,
            },
        }
    }


def normalize_slack_response(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload

    data = getattr(payload, "data", None)
    if isinstance(data, dict):
        return data

    return {}


def _get_slack_user_info_from_db(integration: Integration, slack_user_id: str) -> dict[str, Any] | None:
    try:
        profile = SlackUserProfileCache.objects.filter(
            integration_id=integration.id, slack_user_id=slack_user_id
        ).first()
    except DatabaseError:
        logger.warning("slack_app_slack_user_cache_db_unavailable", integration_id=integration.id)
        return None
    if not profile or not profile.refreshed_at or timezone.now() - profile.refreshed_at >= SLACK_USER_PROFILE_TTL:
        return None

    return _format_slack_user_info_payload(
        email=profile.email,
        display_name=profile.display_name,
        real_name=profile.real_name,
        is_admin=profile.is_admin,
        is_owner=profile.is_owner,
        is_bot=profile.is_bot,
    )


def persist_slack_user_info(integration: Integration, slack_user_id: str, user_info: dict[str, Any]) -> None:
    user = user_info.get("user", {})
    profile = user.get("profile", {})
    try:
        SlackUserProfileCache.objects.update_or_create(
            integration_id=integration.id,
            slack_user_id=slack_user_id,
            defaults={
                "email": profile.get("email") or None,
                "display_name": profile.get("display_name") or "",
                "real_name": profile.get("real_name") or "",
                "is_admin": bool(user.get("is_admin")),
                "is_owner": bool(user.get("is_owner")),
                "is_bot": bool(user.get("is_bot")),
                "refreshed_at": timezone.now(),
            },
        )
    except DatabaseError:
        logger.warning("slack_app_slack_user_cache_db_unavailable", integration_id=integration.id)


def get_slack_user_info(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> dict[str, Any]:
    cached_db = _get_slack_user_info_from_db(integration, slack_user_id)
    if isinstance(cached_db, dict):
        return cached_db

    user_info = normalize_slack_response(slack.client.users_info(user=slack_user_id))
    if user_info:
        persist_slack_user_info(integration, slack_user_id, user_info)
        return user_info
    return {}


def is_slack_workspace_admin(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> bool:
    """Whether the Slack user is a workspace admin or owner."""
    user_info = get_slack_user_info(slack, integration, slack_user_id)
    slack_user = user_info.get("user", {}) if isinstance(user_info, dict) else {}
    return bool(slack_user.get("is_admin") or slack_user.get("is_owner"))


def _get_slack_user_id_by_email_from_db(integration: Integration, normalized_email: str) -> str | None:
    try:
        profile = SlackUserProfileCache.objects.filter(
            integration_id=integration.id,
            email__iexact=normalized_email,
        ).first()
    except DatabaseError:
        logger.warning("slack_app_slack_user_cache_db_unavailable", integration_id=integration.id)
        return None
    if not profile or not profile.refreshed_at or timezone.now() - profile.refreshed_at >= SLACK_USER_PROFILE_TTL:
        return None
    return profile.slack_user_id


def lookup_slack_user_id_by_email(
    slack: SlackIntegration,
    integration: Integration,
    email: str,
) -> str | None:
    """Resolve a Slack user ID from a PostHog user email.

    Uses ``SlackUserProfileCache`` (populated by ``resolve_slack_user`` and prior lookups),
    then ``users.lookupByEmail``.
    """
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    slack_user_id = _get_slack_user_id_by_email_from_db(integration, normalized_email)
    if slack_user_id:
        return slack_user_id

    try:
        user_info = normalize_slack_response(slack.client.users_lookupByEmail(email=email))
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code != "users_not_found":
            logger.warning(
                "slack_user_id_by_email_lookup_failed",
                integration_id=integration.id,
                email=email,
                error=error_code,
            )
        return None

    if not user_info.get("ok"):
        return None

    user = user_info.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        return None

    slack_user_id = str(user["id"])
    persist_slack_user_info(integration, slack_user_id, user_info)
    _purge_stale_email_rows(integration, normalized_email, slack_user_id)
    return slack_user_id


def _purge_stale_email_rows(integration: Integration, normalized_email: str, keep_slack_user_id: str) -> None:
    """Drop rows that share an email with the authoritative Slack user ID we just resolved.

    Without this, an orphan row (same email, older Slack user ID) can outrank the fresh one
    in ``_get_slack_user_id_by_email_from_db`` and trigger a fresh ``users.lookupByEmail`` call
    on every request.
    """
    try:
        SlackUserProfileCache.objects.filter(
            integration_id=integration.id,
            email__iexact=normalized_email,
        ).exclude(slack_user_id=keep_slack_user_id).delete()
    except DatabaseError:
        logger.warning("slack_app_slack_user_cache_db_unavailable", integration_id=integration.id)


def get_cached_bot_user_id(slack: SlackIntegration, integration: Integration) -> str | None:
    """Return the bot's Slack user id for ``integration``, populating the
    shared auth-state cache as a side effect.

    Terminal paths:

    - **Cache hit, healthy with bot_user_id** — return it. No Slack call.
    - **Cache hit, broken** — known dead token; return ``None`` without
      attempting ``auth.test``. Caller treats this the same as an API failure.
    - **Cache miss or healthy-without-bot-id** — run ``auth.test``. On success,
      refresh the cache as ``ok=true`` carrying the bot user id. On an
      auth-class ``SlackApiError``, mark the cache ``ok=false`` so subsequent
      mentions skip this install for the TTL. Transient/network errors leave
      the cache alone — a Slack 5xx shouldn't brick the workspace for 6 hours.
    """
    cached = get_cached_auth_state(integration.id)
    if cached is not None:
        if cached.ok and cached.bot_user_id is not None:
            return cached.bot_user_id
        if not cached.ok:
            return None
        # ``ok=True`` without ``bot_user_id`` is rare (auth.test returned ok
        # without a user_id field). Fall through to ``auth.test`` and refill.

    try:
        response = slack.client.auth_test()
    except SlackApiError as exc:
        error_code, token_broken = classify_slack_api_error(exc)
        if token_broken and error_code is not None:
            write_auth_state_broken(integration.id, error_code)
        logger.warning(
            "slack_app_bot_user_id_lookup_failed",
            integration_id=integration.id,
            error_code=error_code,
            exc_info=True,
        )
        return None
    except Exception:
        logger.warning(
            "slack_app_bot_user_id_lookup_failed",
            integration_id=integration.id,
            error_code=None,
            exc_info=True,
        )
        return None

    bot_user_id = response.get("user_id")
    if not isinstance(bot_user_id, str) or not bot_user_id:
        return None
    write_auth_state_ok(integration.id, bot_user_id)
    return bot_user_id
