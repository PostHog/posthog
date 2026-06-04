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
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.event_usage import groups
from posthog.llm.gateway_client import get_llm_client
from posthog.models.integration import (
    SLACK_INTEGRATION_KINDS,
    Integration,
    SlackIntegration,
    SlackIntegrationError,
    sign_slack_request,
    validate_slack_request,
)
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.temporal.ai.posthog_code_slack_interactivity import (
    PostHogCodeSlackInteractivityInputs,
    PostHogCodeSlackTerminateTaskWorkflow,
)
from posthog.temporal.ai.posthog_code_slack_mention import (
    PostHogCodeSlackMentionWorkflow,
    PostHogCodeSlackMentionWorkflowInputs,
    derive_mention_workflow_id,
)
from posthog.temporal.ai.posthog_code_slack_mention_command import (
    PostHogCodeSlackMentionCommandWorkflow,
    PostHogCodeSlackMentionCommandWorkflowInputs,
)
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.services.integration_resolver import format_project_candidate_list, load_integrations
from products.slack_app.backend.slack_link_unfurl import handle_posthog_link_unfurl

logger = structlog.get_logger(__name__)

HANDLED_EVENT_TYPES = ["app_mention", "link_shared"]

# The notifications Slack app (`slack`) install carries every scope the coding-agent flow
# needs, so both surfaces share one kind.
SLACK_INTEGRATION_KIND = "slack"

# Scopes the coding-agent flow exercises end-to-end. Slack stores the granted scope set
# per install, so tenants who connected the Slack integration before the full scope set
# was requested in prod (2026-05-04, #57177) must reconnect before mentions can work.
POSTHOG_CODE_REQUIRED_SLACK_SCOPES: frozenset[str] = frozenset(
    {
        "app_mentions:read",
        "users:read",
        "users:read.email",
        "chat:write",
        "channels:history",
        "groups:history",
        "reactions:write",
    }
)

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


def _user_repo_list_cache_key(user_id: int) -> str:
    return f"posthog_code:user_repo_list:v1:{user_id}"


def _invalidate_user_repo_list_cache(user_id: int) -> None:
    cache.delete(_user_repo_list_cache_key(user_id))


def _pending_repo_picker_cache_key(integration_id: int, channel: str, thread_ts: str, slack_user_id: str) -> str:
    raw_key = f"{integration_id}:{channel}:{thread_ts}:{slack_user_id}"
    return f"posthog_code:pending_repo_picker:v1:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}"


def _set_pending_repo_picker(
    *,
    integration_id: int,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
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
            "mentioning_user_id": user_id,
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
class RulesCommand:
    """Parsed `@PostHog <command>` mention text.

    Most actions (``list``, ``add``, ``remove``, ``help``, ``default_*``) are
    dispatched post-routing inside the Temporal workflow's first activity. The
    ``project_*`` actions are dispatched pre-routing — they decide which
    integration the workflow runs against — so the routing layer in `api.py`
    handles them before ``start_workflow`` and the workflow activity ignores
    them defensively.
    """

    action: Literal[
        "list",
        "add",
        "remove",
        "help",
        "deprecated_default_repo",
        "project_show",
        "project_set",
        "project_set_workspace",
    ]
    rule_text: str | None = None
    repository: str | None = None
    rule_numbers: list[int] | None = None
    project_team_id: int | None = None


def _slack_user_info_cache_key(integration_id: int, slack_user_id: str) -> str:
    return f"posthog_code_slack_user_info:{integration_id}:{slack_user_id}"


def _slack_user_id_by_email_cache_key(integration_id: int, normalized_email: str) -> str:
    return f"posthog_code_slack_user_id_by_email:{integration_id}:{normalized_email}"


def _format_slack_user_info_payload(
    *, email: str | None, display_name: str, real_name: str, is_admin: bool, is_owner: bool
) -> dict[str, Any]:
    return {
        "user": {
            "is_admin": is_admin,
            "is_owner": is_owner,
            "profile": {
                "email": email,
                "display_name": display_name,
                "real_name": real_name,
            },
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
        is_admin=profile.is_admin,
        is_owner=profile.is_owner,
    )


def _persist_slack_user_info(integration: Integration, slack_user_id: str, user_info: dict[str, Any]) -> None:
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


def is_slack_workspace_admin(slack: SlackIntegration, integration: Integration, slack_user_id: str) -> bool:
    """Whether the Slack user is a workspace admin or owner."""
    user_info = _get_slack_user_info(slack, integration, slack_user_id)
    slack_user = user_info.get("user", {}) if isinstance(user_info, dict) else {}
    return bool(slack_user.get("is_admin") or slack_user.get("is_owner"))


def _get_slack_user_id_by_email_from_db(integration: Integration, normalized_email: str) -> str | None:
    try:
        profile = SlackUserProfileCache.objects.filter(
            integration_id=integration.id,
            email__iexact=normalized_email,
        ).first()
    except DatabaseError:
        logger.warning("posthog_code_slack_user_cache_db_unavailable", integration_id=integration.id)
        return None
    return profile.slack_user_id if profile else None


def lookup_slack_user_id_by_email(
    slack: SlackIntegration,
    integration: Integration,
    email: str,
) -> str | None:
    """Resolve a Slack user ID from a PostHog user email.

    Uses ``SlackUserProfileCache`` (populated by ``resolve_slack_user`` and prior lookups),
    then ``users.lookupByEmail``. Results are cached per integration + email.
    """
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    cache_key = _slack_user_id_by_email_cache_key(integration.id, normalized_email)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    slack_user_id = _get_slack_user_id_by_email_from_db(integration, normalized_email)
    if slack_user_id:
        cache.set(cache_key, slack_user_id, timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return slack_user_id

    try:
        user_info = _normalize_slack_response(slack.client.users_lookupByEmail(email=email))
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code != "users_not_found":
            logger.warning(
                "slack_user_id_by_email_lookup_failed",
                integration_id=integration.id,
                email=email,
                error=error_code,
            )
        cache.set(cache_key, "", timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return None

    if not user_info.get("ok"):
        cache.set(cache_key, "", timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return None

    user = user_info.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        cache.set(cache_key, "", timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
        return None

    slack_user_id = str(user["id"])
    _persist_slack_user_info(integration, slack_user_id, user_info)
    cache.set(
        _slack_user_info_cache_key(integration.id, slack_user_id),
        user_info,
        timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS,
    )
    cache.set(cache_key, slack_user_id, timeout=SLACK_USER_INFO_CACHE_TTL_SECONDS)
    return slack_user_id


QUOTA_EXHAUSTED_MESSAGE = (
    "Your team has used its monthly PostHog AI credits. "
    "Top up at https://us.posthog.com/organization/billing to continue."
)


def post_quota_exhausted_denial(
    *,
    integration: Integration,
    slack: SlackIntegration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    context: str,
) -> None:
    """Post the AI-credits denial message into a Slack thread.

    Called by the workflow's quota gate after it determines the team is over
    quota. Lives in this module so the Slack-posting helpers and the message
    text stay co-located; the quota check itself lives in the temporal layer
    (which is the only side allowed to import ``ee.billing``).
    """
    logger.info(
        "posthog_code_slack_blocked_by_quota",
        context=context,
        team_id=integration.team_id,
        channel=channel,
        thread_ts=thread_ts,
    )
    _post_slack_user_feedback(
        slack,
        channel,
        slack_user_id,
        thread_ts,
        QUOTA_EXHAUSTED_MESSAGE,
        prefer_thread_message=True,
    )


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

        if settings.DEBUG:
            # When running locally - match the local user
            slack_email = "test@posthog.com"

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
                    prefer_thread_message=True,
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


# Slack delivers a single webhook URL per app, but the workspace's PostHog Integration may live
# in either Cloud region. Whichever region Slack hits, we route the event to the region that
# owns the workspace. US is the primary; when both regions hold a row for the same workspace
# (only possible during cutover or migration), US wins. This means:
#
#  - hit US, local match           -> handle locally
#  - hit US, no local match        -> proxy to EU (loop header set)
#  - hit EU, US says "I have it"   -> proxy to US (loop header set)
#  - hit EU, US says "no"          -> handle locally if found, else drop
#  - hit EU, probe errs / unknown  -> assume US claims and proxy (optimistic); US drops if it
#                                     also has nothing, which is the same outcome as before
#  - hit either with loop header   -> never proxy again; handle locally or drop
#
# This keeps the slack manifest endpoint swappable between us.posthog.com and eu.posthog.com
# without any other coordination.
REGION_PROXY_HEADER = "X-PostHog-Region-Proxied"
REGION_PROXY_TIMEOUT_SECONDS = 3
# Tight budget: the workspace_claims endpoint is just a DB .exists(), and EU calls it inline
# before deciding whether to proxy. Slack's webhook ack deadline is 3s total, so we want this
# call to fail fast (and fall back to optimistic proxy) rather than eat into the proxy budget.
WORKSPACE_CLAIMS_TIMEOUT_SECONDS = (1, 1)
# Cache definitive (True/False) claim answers per workspace so a single probe flake does not
# re-flap routing for every subsequent event. Short TTL keeps us responsive when an integration
# moves between regions; None answers are never cached.
WORKSPACE_CLAIMS_CACHE_TTL_SECONDS = 60


def _us_region_domain() -> str:
    # Resolved at call time so override_settings(DEBUG=...) flips the topology cleanly in tests.
    # In dev we run a single instance pretending to be both regions: the incoming SITE_URL host
    # plays the part of US, and the other region is mapped to localhost so the proxy round-trips
    # through the same process and exercises the at-most-one-hop guarantee end-to-end.
    if settings.DEBUG:
        return urlparse(settings.SITE_URL).netloc
    return "us.posthog.com"


def _eu_region_domain() -> str:
    if settings.DEBUG:
        return "localhost:8000"
    return "eu.posthog.com"


def _is_us_host(host: str) -> bool:
    return host == _us_region_domain()


def _other_region_domain(incoming_host: str) -> str:
    return _eu_region_domain() if _is_us_host(incoming_host) else _us_region_domain()


def _was_proxied(request: HttpRequest) -> bool:
    # Match the literal value the sender sets (`"1"`) rather than coercing the header value to
    # bool — semgrep flags the latter as nan-injection and we control the sender anyway.
    return request.headers.get(REGION_PROXY_HEADER) == "1"


def _proxy_event_to_region(request: HttpRequest, target_domain: str) -> requests.Response | None:
    """Forward the original Slack event to the other region, tagged so the receiver does not hop again."""
    parsed_url = urlparse(request.build_absolute_uri())
    # In dev the EU "region" is plain-HTTP localhost while the incoming URI is HTTPS (ngrok-
    # terminated TLS), so always pick the scheme by target domain rather than copying the
    # inbound one. Production talks HTTPS region-to-region.
    target_scheme = "http" if settings.DEBUG else "https"
    target_url = urlunparse(parsed_url._replace(scheme=target_scheme, netloc=target_domain))
    # Drop Host plus the host-identifying forwarded headers so the receiver computes its own
    # host from the new TCP connection rather than mirroring the sender's edge. X-Forwarded-For
    # is intentionally preserved so the original Slack client IP survives the inter-region hop.
    stripped = {"host", "x-forwarded-host", "forwarded"}
    headers = {key: value for key, value in request.headers.items() if key.lower() not in stripped}
    headers[REGION_PROXY_HEADER] = "1"

    try:
        response = requests.request(
            method=request.method or "POST",
            url=target_url,
            headers=headers,
            params=dict(request.GET.lists()) if request.GET else None,
            data=request.body or None,
            timeout=REGION_PROXY_TIMEOUT_SECONDS,
        )
        if 200 <= response.status_code < 300:
            logger.info("slack_app_region_proxy_ok", target_url=target_url, status_code=response.status_code)
            return response

        logger.warning(
            "slack_app_region_proxy_non_success",
            target_url=target_url,
            status_code=response.status_code,
        )
        return None
    except requests.RequestException as exc:
        logger.exception("slack_app_region_proxy_failed", error=str(exc), target_url=target_url)
        return None


def _proxy_event_and_return_route(request: HttpRequest, target_domain: str) -> str:
    """Forward and translate the upstream result into a routing outcome string."""
    return ROUTE_PROXIED if _proxy_event_to_region(request, target_domain) is not None else ROUTE_PROXY_FAILED


def _workspace_claims_cache_key(slack_team_id: str, kinds: list[str]) -> str:
    kinds_token = ",".join(sorted(kinds))
    return f"slack_app:ws_claims:{slack_team_id}:{kinds_token}"


def does_other_region_claim_workspace(*, slack_team_id: str, kinds: list[str], incoming_host: str) -> bool | None:
    """Ask the other region whether it claims the given workspace for any of the kinds.

    Returns True/False on a definitive answer, or None on transport failure or bad response.
    Definitive answers are cached for ``WORKSPACE_CLAIMS_CACHE_TTL_SECONDS`` so a single probe
    flake does not reroute the next event. None is never cached so the next event re-probes.
    """
    cache_key = _workspace_claims_cache_key(slack_team_id, kinds)
    cached = cache.get(cache_key)
    if isinstance(cached, bool):
        logger.info(
            "slack_app_workspace_claims_cache_hit",
            slack_team_id=slack_team_id,
            claimed=cached,
        )
        return cached

    target_domain = _other_region_domain(incoming_host)
    scheme = "http" if settings.DEBUG else "https"
    target_url = f"{scheme}://{target_domain}/slack/workspace/claims/"

    body = json.dumps({"slack_team_id": slack_team_id, "kinds": kinds}).encode("utf-8")
    signing_secret = SlackIntegration.slack_config()["SLACK_APP_SIGNING_SECRET"]
    signature, ts = sign_slack_request(body, signing_secret)

    try:
        response = requests.post(
            target_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": signature,
                "X-Slack-Request-Timestamp": ts,
                REGION_PROXY_HEADER: "1",
            },
            timeout=WORKSPACE_CLAIMS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.warning("slack_app_workspace_claims_failed", target_url=target_url, error=str(exc))
        return None

    if response.status_code != 200:
        logger.warning(
            "slack_app_workspace_claims_non_200",
            target_url=target_url,
            status_code=response.status_code,
        )
        return None

    try:
        data = response.json()
    except ValueError:
        logger.warning("slack_app_workspace_claims_bad_json", target_url=target_url)
        return None

    claimed = data.get("claimed")
    if not isinstance(claimed, bool):
        logger.warning("slack_app_workspace_claims_bad_payload", target_url=target_url)
        return None

    cache.set(cache_key, claimed, timeout=WORKSPACE_CLAIMS_CACHE_TTL_SECONDS)
    return claimed


_VALID_WORKSPACE_CLAIM_KINDS = frozenset(SLACK_INTEGRATION_KINDS)


@csrf_exempt
def slack_workspace_claims_view(request: HttpRequest) -> HttpResponse:
    """Cross-region probe: does this region hold an Integration row for the given Slack workspace?

    Both Cloud regions provision the PostHog Code Slack signing secret, so a region can HMAC-sign
    a small JSON body and the receiver can verify it with the same routine that validates real
    Slack webhooks. The signed body covers `slack_team_id` + `kinds`, so a captured signature
    cannot be replayed against a different workspace.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        slack_config = SlackIntegration.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("slack_app_workspace_claims_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    slack_team_id = data.get("slack_team_id")
    kinds = data.get("kinds")
    if not isinstance(slack_team_id, str) or not slack_team_id:
        return HttpResponse("Missing slack_team_id", status=400)
    if not isinstance(kinds, list) or not kinds:
        return HttpResponse("Missing kinds", status=400)
    filtered = [k for k in kinds if isinstance(k, str) and k in _VALID_WORKSPACE_CLAIM_KINDS]
    if not filtered:
        return HttpResponse("No valid kinds", status=400)

    claimed = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
        kind__in=filtered,
        integration_id=slack_team_id,
    ).exists()
    return JsonResponse({"claimed": claimed})


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

    # `project workspace <id>` sets the workspace-wide default and must be tested
    # before the generic `project` branch. Trailing text after the id is ignored.
    project_workspace_match = re.fullmatch(
        r"project\s+workspace\s+(\d+)(?:\s+.*)?", cleaned, flags=re.IGNORECASE | re.DOTALL
    )
    if project_workspace_match is not None:
        return RulesCommand(action="project_set_workspace", project_team_id=int(project_workspace_match.group(1)))

    # Trailing text after the id is tolerated but ignored — we only act on the id.
    project_match = re.fullmatch(r"project(?:\s+(\d+)(?:\s+.*)?)?", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if project_match is not None:
        team_id_str = project_match.group(1)
        if team_id_str is None:
            return RulesCommand(action="project_show")
        return RulesCommand(action="project_set", project_team_id=int(team_id_str))

    if re.fullmatch(r"help", cleaned, flags=re.IGNORECASE):
        return RulesCommand(action="help")

    # Intercept legacy `default repo` verbs so `default repo set org/repo` doesn't
    # fall through into the explicit-repo cascade and spawn a junk task.
    if re.fullmatch(r"default\s+repo\s+(set|show|clear)(\s+.*)?", cleaned, flags=re.IGNORECASE):
        return RulesCommand(action="deprecated_default_repo")

    return None


def _post_repo_picker_message(
    *,
    slack: SlackIntegration,
    integration: Integration,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    user_id: int,
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
        "mentioning_user_id": user_id,
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
            user_id=user_id,
            workflow_id=workflow_id,
            context_token=context_token,
            message_ts=message_ts,
        )

    # Pre-warm the repo list cache so the external_select options request
    # is served from cache rather than hitting the GitHub API inline.
    # Non-fatal: the dropdown will still work, it will just fetch on demand.
    try:
        _get_full_repo_names(integration, user_id=user_id)
    except Exception:
        logger.warning("repo_list_prewarm_failed", user_id=user_id, exc_info=True)


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


def _flatten_block_text(node: Any) -> list[str]:
    """Best-effort plain-text extraction from a Slack block-kit subtree.

    Slack alert posts (subscriptions, log alerts, hog-function destinations) often
    put the substantive content in `blocks` while the top-level `text` field is a
    short fallback (or empty). Walking the block tree lets us surface that content
    to the agent. Always wrap call sites in try/except — Slack block schemas evolve.
    """
    if node is None:
        return []
    if isinstance(node, str):
        stripped = node.strip()
        return [stripped] if stripped else []
    if isinstance(node, list):
        out: list[str] = []
        for item in node:
            out.extend(_flatten_block_text(item))
        return out
    if isinstance(node, dict):
        # `context` blocks can carry useful labels — recurse into `elements` only.
        if node.get("type") == "context":
            return _flatten_block_text(node.get("elements"))
        # Skip interactive/decorative blocks that carry no information for the agent.
        if node.get("type") in ("actions", "divider", "image"):
            return []
        out = []
        for key in ("text", "fields", "elements", "title", "pretext", "fallback"):
            if key in node:
                out.extend(_flatten_block_text(node[key]))
        return out
    return []


def _extract_message_text(msg: dict) -> str:
    # Always include `text` and `blocks`/`attachments`: PostHog's own alert templates put
    # the headline in `text` and the values/details in blocks. Dedup so a string repeated
    # across both (e.g. text == header block) shows up once.
    pieces: list[str] = []
    text = (msg.get("text") or "").strip()
    if text:
        pieces.append(text)

    blocks = msg.get("blocks") or []
    attachments = msg.get("attachments") or []
    try:
        pieces.extend(_flatten_block_text(blocks))
    except Exception:
        logger.warning("slack_thread_block_flatten_failed", exc_info=True)
    try:
        pieces.extend(_flatten_block_text(attachments))
    except Exception:
        logger.warning("slack_thread_attachment_flatten_failed", exc_info=True)

    seen: set[str] = set()
    deduped: list[str] = []
    for piece in pieces:
        if piece and piece not in seen:
            seen.add(piece)
            deduped.append(piece)
    return "\n".join(deduped)


def _resolve_bot_author_label(msg: dict) -> str:
    bot_profile = msg.get("bot_profile") or {}
    return bot_profile.get("name") or msg.get("username") or "Bot"


def _collect_thread_messages(
    slack: SlackIntegration, integration: Integration, channel: str, thread_ts: str, our_bot_id: str | None
) -> list[dict[str, str]]:
    """Fetch thread messages, strip bot mentions, and resolve user display names."""
    client = slack.client
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
    thread_response = client.conversations_replies(channel=channel, ts=thread_ts)
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
    for index, msg in enumerate(raw_messages):
        # Skip our own bot's posts to avoid loops where the agent ingests its own replies.
        # Never skip the thread root: the agent only ever posts as a reply, so msg 0 is
        # always the originating message (e.g. a PostHog alert) that's the actual context
        # for the task. Filtering it by bot_id breaks workspaces where the alerting Slack
        # app and the `@PostHog` code app share an installation identity.
        if index > 0 and our_bot_id and msg.get("bot_id") == our_bot_id:
            continue

        user_id = msg.get("user")
        if user_id:
            username = resolve_user(user_id)
        elif msg.get("bot_id"):
            username = _resolve_bot_author_label(msg)
        else:
            username = "Unknown"

        text = replace_user_mentions(_extract_message_text(msg))
        # `ts` lets downstream callers distinguish the initiator message from surrounding thread
        # context, since `app_mention` events surface only the initiator's ts.
        messages.append({"user": username, "text": text, "ts": msg.get("ts") or ""})

    return messages


def _get_full_repo_names(integration: Integration, *, user_id: int | None) -> list[str]:
    """Return canonical org/repo names from the mentioning user's GitHub install, or [] if unavailable.

    Repos are scoped to the user's personal GitHub integration so the picker matches the
    identity that will author the resulting pull request. Users without a personal install
    see an empty list; the downstream personal-GitHub gate posts the connect-GitHub prompt.
    A `None` user_id (e.g. a workflow replay predating per-user scoping) also returns [].
    """
    if user_id is None:
        return []
    cache_key = _user_repo_list_cache_key(user_id)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    user_records = UserIntegration.objects.filter(
        user_id=user_id,
        kind=UserIntegration.IntegrationKind.GITHUB,
    )
    if not user_records.exists():
        cache.set(cache_key, [], timeout=REPO_LIST_CACHE_TTL_SECONDS)
        return []

    all_repos: set[str] = set()

    for record in user_records:
        github = UserGitHubIntegration(record)
        repo_entries = github.list_all_cached_repositories(max_repos=_MAX_GITHUB_REPOS)
        for repo in repo_entries:
            all_repos.add(repo["full_name"])
            if len(all_repos) >= _MAX_GITHUB_REPOS:
                logger.warning(
                    "github_repo_list_capped",
                    user_id=user_id,
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
            id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
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
            id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
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

    mentioning_user_id = pending_picker.get("mentioning_user_id")
    if not isinstance(mentioning_user_id, int):
        # Without a known PostHog user we can't scope the picker to a personal install;
        # let the message fall through to the standard flow, which will re-resolve and re-post.
        return False

    try:
        all_repos = _get_full_repo_names(integration, user_id=mentioning_user_id)
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
        "A complaint about something the team's own app, site, or SDK does (crashes, broken pages, "
        "wrong rendering, slow loads of a site they ship) is a code change in a repo they own → "
        "needs_repo. But complaints about PostHog itself as a product (its dashboards hanging, "
        "product pages loading slowly, UI bugs in PostHog screens) are SaaS product issues, not "
        "the team's code → no_repo. Important exception: 'wrong data', 'missing events', or "
        "'numbers look off' in PostHog usually means the team's tracking code is broken (wrong "
        "event names, identification logic, SDK setup) — that's a code fix in their repo → "
        "needs_repo. When in doubt, lean needs_repo=true — the discovery agent can still report "
        "there's no good match.\n\n"
        f"Conversation:\n{conversation}\n\n"
        f"Latest message: {event_text}\n\n"
        'Respond with ONLY a JSON object: {{"needs_repo": true}} or {{"needs_repo": false}}'
    )
    try:
        client = get_llm_client("slack_app_routing")
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


def _app_mention_ignore_reason(event: dict[str, Any]) -> str | None:
    """Return a short reason if this app_mention shouldn't trigger the coding agent, else None.

    - "edit": Slack re-fires app_mention with a new event_id when a previously-posted
      mention is edited. The new event_id bypasses Temporal workflow dedup, so without
      this guard the edit spawns a duplicate task alongside the original.
    - "bot_author": the message was authored by another Slack app/bot. Foreign bots
      that quote `<@PostHog>` in their text (incident bots, alert relays, our own
      notifications integration) would trigger reply loops on every re-post.
    """
    if event.get("edited") or event.get("subtype") == "message_changed":
        return "edit"
    if (
        event.get("bot_id")
        or event.get("bot_profile")
        or event.get("app_id")
        or event.get("subtype") == "bot_message"
        or event.get("user") == "USLACKBOT"
    ):
        return "bot_author"
    return None


def _notify_missing_slack_scopes(
    slack: SlackIntegration,
    event: dict,
    missing: frozenset[str],
) -> None:
    """Tell the user the install is missing scopes and how to fix it.

    `chat:write` has been part of the base Slack scope set since the integration existed,
    so the feedback post itself is safe to attempt even when other scopes are absent.
    """
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")
    slack_user_id = event.get("user", "")
    integration = slack.integration

    logger.warning(
        "posthog_code_slack_missing_scopes",
        integration_id=integration.id,
        team_id=integration.team_id,
        missing=sorted(missing),
    )

    if not channel or not thread_ts or not slack_user_id:
        return

    settings_url = f"{settings.SITE_URL}/settings/project-integrations"
    text = (
        ":warning: PostHog can't reply because the Slack integration is missing required "
        f"permissions: `{', '.join(sorted(missing))}`.\n"
        f"A project admin needs to reconnect Slack from project settings: {settings_url}"
    )

    _post_slack_user_feedback(slack, channel, slack_user_id, thread_ts, text, prefer_thread_message=True)


def _resolve_posthog_user_from_event(
    *,
    slack_user_id: str,
    probe_integration: Integration,
    candidate_integrations: list[Integration],
) -> User | None:
    """Resolve the acting Slack user to a PostHog ``User`` who is a member of
    at least one organization connected to this Slack workspace.

    The probe is used to call Slack's ``users.info``; the candidate list scopes
    the organization-membership check. A user with no membership in any
    connected org returns ``None`` so the caller can refuse the event.
    """
    slack_client = SlackIntegration(probe_integration)
    try:
        user_info = _get_slack_user_info(slack_client, probe_integration, slack_user_id)
        slack_email = user_info.get("user", {}).get("profile", {}).get("email")
        if not slack_email:
            fresh = _normalize_slack_response(slack_client.client.users_info(user=slack_user_id))
            if fresh:
                _persist_slack_user_info(probe_integration, slack_user_id, fresh)
                slack_email = fresh.get("user", {}).get("profile", {}).get("email")
        if not slack_email:
            return None
        org_ids = {c.team.organization_id for c in candidate_integrations}
        if not org_ids:
            return None
        membership = (
            OrganizationMembership.objects.filter(organization_id__in=org_ids, user__email=slack_email)
            .select_related("user")
            .first()
        )
        return membership.user if membership else None
    except Exception:
        logger.warning(
            "posthog_code_resolve_user_failed",
            integration_id=probe_integration.id,
            slack_user_id=slack_user_id,
            exc_info=True,
        )
    return None


def _post_pick_a_project_hint(
    probe: SlackIntegration,
    candidates: list[Integration],
    event: dict[str, Any],
) -> None:
    """Tell the user that this workspace is connected to multiple PostHog
    projects, and that they should pick one via `@PostHog project <id>`.
    """
    slack_user_id = event.get("user")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not isinstance(slack_user_id, str) or not isinstance(channel, str) or not isinstance(thread_ts, str):
        return
    text = (
        "This Slack workspace is connected to multiple PostHog projects:\n"
        f"{format_project_candidate_list(candidates)}\n\n"
        "Use `@PostHog project <id>` to pick one — that also saves it as your default."
    )
    _post_slack_user_feedback(probe, channel, slack_user_id, thread_ts, text, prefer_thread_message=True)


def _start_posthog_code_workflow(
    workflow_cls: Any,
    workflow_inputs: Any,
    *,
    id_prefix: str,
    slack_team_id: str,
    event: dict,
    event_id: str | None,
    workflow_id: str | None = None,
) -> None:
    if workflow_id is None:
        fallback = event_id if event_id else f"{event.get('channel', '')}:{event.get('ts', '')}"
        workflow_id = f"{id_prefix}-{slack_team_id}:{fallback}"
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            workflow_cls.run,
            workflow_inputs,
            id=workflow_id,
            task_queue=settings.MAX_AI_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


def route_posthog_code_event_to_relevant_region(
    request: HttpRequest,
    event: dict,
    slack_team_id: str,
    event_id: str | None = None,
) -> str:
    event_type = event.get("type")
    incoming_host = request.get_host()
    proxied = _was_proxied(request)
    other_domain = _other_region_domain(incoming_host)
    # In local dev we run a single instance, so cross-region routing is meaningless: the only
    # consumer is this process. Disable both the probe and the proxy hop and always handle
    # locally.
    can_defer_to_other_region = not _is_us_host(incoming_host) and not proxied and not settings.DEBUG

    logger.info(
        "posthog_code_route_enter",
        incoming_host=incoming_host,
        is_us=_is_us_host(incoming_host),
        proxied=proxied,
        other_domain=other_domain,
        can_defer=can_defer_to_other_region,
        event_type=event_type,
        slack_team_id=slack_team_id,
        event_id=event_id,
        debug=settings.DEBUG,
        us_domain=_us_region_domain(),
        eu_domain=_eu_region_domain(),
    )

    if event_type == "app_mention":
        ignore_reason = _app_mention_ignore_reason(event)
        if ignore_reason:
            logger.info(
                "posthog_code_event_app_mention_ignored",
                reason=ignore_reason,
                slack_team_id=slack_team_id,
                channel=event.get("channel"),
                message_ts=event.get("ts"),
            )
            return ROUTE_HANDLED_LOCALLY

        result = load_integrations(
            slack_team_id=slack_team_id,
            kinds=[SLACK_INTEGRATION_KIND],
            slack_user_id=str(event.get("user") or ""),
            user=None,
            channel=event.get("channel") if isinstance(event.get("channel"), str) else None,
            thread_ts=(event.get("thread_ts") or event.get("ts"))
            if isinstance(event.get("thread_ts") or event.get("ts"), str)
            else None,
        )
        if not result.candidates:
            return _route_to_other_region_or_drop(request, slack_team_id, proxied=proxied, other_domain=other_domain)

        if _us_should_handle_instead(slack_team_id, [SLACK_INTEGRATION_KIND], can_defer_to_other_region, incoming_host):
            return _proxy_event_and_return_route(request, other_domain)

        candidates = result.candidates
        target = result.integration if result.integration in candidates else None

        if _parse_rules_command(event.get("text", "")) is not None:
            return _start_command_workflow(event, candidates, slack_team_id, event_id)

        mention_target = target or (candidates[0] if len(candidates) == 1 else None)
        if mention_target is None:
            _post_pick_a_project_hint(SlackIntegration(candidates[0]), candidates, event)
            return ROUTE_HANDLED_LOCALLY

        slack = SlackIntegration(mention_target)
        missing = slack.missing_scopes(POSTHOG_CODE_REQUIRED_SLACK_SCOPES)
        if missing:
            _notify_missing_slack_scopes(slack, event, missing)
            return ROUTE_HANDLED_LOCALLY

        return _start_mention_workflow(event, mention_target, slack_team_id, event_id)

    # link_shared (unfurl) works with either integration kind.
    link_result = load_integrations(slack_team_id=slack_team_id, kinds=list(SLACK_INTEGRATION_KINDS))
    local_match = link_result.candidates[0] if link_result.candidates else None
    if local_match:
        if _us_should_handle_instead(
            slack_team_id, list(SLACK_INTEGRATION_KINDS), can_defer_to_other_region, incoming_host
        ):
            return _proxy_event_and_return_route(request, other_domain)
        if event_type == "link_shared":
            handle_posthog_link_unfurl(event, local_match)
        return ROUTE_HANDLED_LOCALLY
    return _route_to_other_region_or_drop(request, slack_team_id, proxied=proxied, other_domain=other_domain)


def _us_should_handle_instead(slack_team_id: str, kinds: list[str], can_defer: bool, incoming_host: str) -> bool:
    """US-precedence guard. EU yields to US when both claim a workspace.

    Skipped when we're already US (we win) or when we were proxied to (the other region already
    deferred). When the probe transport itself fails (None), bias toward proxying to US: during
    a region cutover both regions hold a row for the same workspace and US is the rightful owner,
    so a single probe flake should not pin the event to EU. If US in fact has no row, it sees the
    proxied event with the loop header set and drops it — the same outcome the caller would have
    reached by handling locally.
    """
    if not can_defer:
        return False
    claimed = does_other_region_claim_workspace(slack_team_id=slack_team_id, kinds=kinds, incoming_host=incoming_host)
    decision = True if claimed is None else claimed
    logger.info(
        "posthog_code_route_us_probe_result",
        slack_team_id=slack_team_id,
        claimed=claimed,
        decision=decision,
        optimistic_proxy=claimed is None,
    )
    return decision


def _route_to_other_region_or_drop(
    request: HttpRequest, slack_team_id: str, *, proxied: bool, other_domain: str
) -> str:
    """No local match: either forward to the other region or drop if we are the second hop.

    In local dev there is no other region to forward to, so we just record the miss and stop.
    """
    if proxied or settings.DEBUG:
        logger.warning(
            "posthog_code_no_integration_found",
            slack_team_id=slack_team_id,
            incoming_host=request.get_host(),
        )
        return ROUTE_NO_INTEGRATION
    return _proxy_event_and_return_route(request, other_domain)


def _start_command_workflow(
    event: dict, integrations: list[Integration], slack_team_id: str, event_id: str | None
) -> str:
    _start_posthog_code_workflow(
        PostHogCodeSlackMentionCommandWorkflow,
        PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[i.id for i in integrations],
            slack_team_id=slack_team_id,
        ),
        id_prefix="posthog-code-mention-command",
        slack_team_id=slack_team_id,
        event=event,
        event_id=event_id,
    )
    return ROUTE_HANDLED_LOCALLY


def _count_session_thread_messages(integration: Integration, channel: str | None, thread_ts: str | None) -> int | None:
    """Best-effort count of messages in a Slack thread (the session). None if unavailable.

    Runs in the Slack webhook request path, so the client timeout is bounded: a slow or
    rate-limited Slack response must not eat into Slack's retry window before we return.
    """
    if not channel or not thread_ts:
        return None
    try:
        client = SlackIntegration(integration).client
        client.timeout = 3
        response = client.conversations_replies(channel=channel, ts=thread_ts, limit=200)
        return len(response.get("messages", []))
    except Exception:
        logger.warning(
            "posthog_code_mention_count_failed",
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            exc_info=True,
        )
        return None


def _report_slack_mention_received(event: dict, integration: Integration, slack_team_id: str) -> None:
    """Capture a product-analytics event each time the @PostHog bot is mentioned.

    A Slack thread is treated as the session: ``thread_ts`` identifies it, and a mention whose
    ``thread_ts`` is absent or equal to its own ``ts`` is the session's first message. The acting
    Slack user is resolved to a PostHog ``User`` so the event is attributed to a real person where
    one exists; otherwise it falls back to a stable Slack-derived distinct id.
    """
    try:
        channel = event.get("channel") if isinstance(event.get("channel"), str) else None
        message_ts = event.get("ts") if isinstance(event.get("ts"), str) else None
        raw_thread_ts = event.get("thread_ts") if isinstance(event.get("thread_ts"), str) else None
        thread_ts = raw_thread_ts or message_ts
        is_first_message_in_session = raw_thread_ts is None or raw_thread_ts == message_ts

        slack_user_id = event.get("user") if isinstance(event.get("user"), str) and event.get("user") else None
        posthog_user = (
            _resolve_posthog_user_from_event(
                slack_user_id=slack_user_id,
                probe_integration=integration,
                candidate_integrations=[integration],
            )
            if slack_user_id
            else None
        )
        # Prefer the resolved PostHog user's distinct id so the event attributes to a real person;
        # fall back to a stable Slack-derived id so anonymous-but-valid mentions are still captured.
        identified_distinct_id = posthog_user.distinct_id if posthog_user else None
        distinct_id = identified_distinct_id or f"slack:{slack_team_id}:{slack_user_id or 'unknown'}"

        if is_first_message_in_session:
            session_message_count: int | None = 1
        else:
            session_message_count = _count_session_thread_messages(integration, channel, thread_ts)

        properties: dict[str, Any] = {
            "is_first_message_in_session": is_first_message_in_session,
            "session_message_count": session_message_count,
            "slack_session_id": f"{slack_team_id}:{channel}:{thread_ts}" if channel and thread_ts else None,
            "slack_team_id": slack_team_id,
            "slack_channel": channel,
            "slack_thread_ts": thread_ts,
            "slack_user_id": slack_user_id,
            "posthog_user_identified": identified_distinct_id is not None,
        }
        if posthog_user is not None and identified_distinct_id is not None:
            properties["$set"] = posthog_user.get_analytics_metadata()

        posthoganalytics.capture(
            distinct_id=distinct_id,
            event="posthog code slack mention received",
            properties=properties,
            groups=groups(team=integration.team),
            send_feature_flags=True,
        )
    except Exception:
        logger.warning(
            "posthog_code_mention_analytics_failed",
            slack_team_id=slack_team_id,
            integration_id=integration.id,
            exc_info=True,
        )


def _start_mention_workflow(event: dict, integration: Integration, slack_team_id: str, event_id: str | None) -> str:
    _report_slack_mention_received(event, integration, slack_team_id)
    if _resolve_pending_repo_picker_from_followup(event, integration):
        return ROUTE_HANDLED_LOCALLY
    workflow_inputs = PostHogCodeSlackMentionWorkflowInputs(
        event=event,
        integration_id=integration.id,
        slack_team_id=slack_team_id,
        slack_event_id=event_id,
    )
    # Use derive_mention_workflow_id as the single source of truth: the workflow persists the same
    # value as slack_mention_workflow_id, so dispatch and the debug-tool Temporal link stay consistent
    _start_posthog_code_workflow(
        PostHogCodeSlackMentionWorkflow,
        workflow_inputs,
        id_prefix="posthog-code-mention",
        slack_team_id=slack_team_id,
        event=event,
        event_id=event_id,
        workflow_id=derive_mention_workflow_id(workflow_inputs),
    )
    return ROUTE_HANDLED_LOCALLY


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
        slack_config = SlackIntegration.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])
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
            logger.info(
                "posthog_code_event_dispatch_result",
                result=result,
                slack_team_id=slack_team_id,
                event_id=event_id,
            )
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
                Integration.objects.filter(kind=SLACK_INTEGRATION_KIND, integration_id=team_id).order_by("id").first()
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
            id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
        )
    except Integration.DoesNotExist:
        logger.info("posthog_code_repo_picker_options_no_integration", context_token=context_token)
        return JsonResponse({"options": []})

    mentioning_user_id = ctx.get("mentioning_user_id") if ctx else None
    if not isinstance(mentioning_user_id, int):
        # Without a known PostHog user we can't scope the options to a personal install;
        # return empty rather than falling back to the team install — the user can re-mention.
        logger.info("posthog_code_repo_picker_options_missing_user_id", context_token=context_token)
        return JsonResponse({"options": []})

    try:
        all_repos = _get_full_repo_names(integration, user_id=mentioning_user_id)
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
                id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
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
        slack_config = SlackIntegration.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])
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
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and hinted_integration_id and hinted_user_id and requesting_user == hinted_user_id:
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=hinted_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and terminate_integration_id and (not terminate_user_id or requesting_user == terminate_user_id):
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=terminate_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()

    proxied = _was_proxied(request)
    incoming_host = request.get_host()
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
        host=incoming_host,
        proxied=proxied,
    )

    if not local and not proxied and not settings.DEBUG:
        # The payload's integration_id pinpoints exactly one row, so a lookup would tell us
        # nothing new — just forward to the other region. The loop header keeps us at one hop.
        # Skipped in local dev where there is only one region to talk to.
        target = _other_region_domain(incoming_host)
        upstream = _proxy_event_to_region(request, target)
        if upstream is not None:
            logger.info(
                "posthog_code_interactivity_route",
                outcome="proxied",
                from_host=incoming_host,
                to_domain=target,
                payload_type=payload_type,
            )
            return HttpResponse(
                upstream.content,
                status=upstream.status_code,
                content_type=upstream.headers.get("Content-Type", "application/json"),
            )
        # Proxy failed — return safe defaults
        logger.warning(
            "posthog_code_interactivity_route",
            outcome="proxy_failed",
            from_host=incoming_host,
            to_domain=target,
            payload_type=payload_type,
        )
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=502)

    if not local:
        logger.warning(
            "posthog_code_interactivity_route",
            outcome="dropped",
            from_host=incoming_host,
            payload_type=payload_type,
            context_token=context_token,
        )
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=200)

    logger.info(
        "posthog_code_interactivity_route",
        outcome="handled",
        from_host=incoming_host,
        payload_type=payload_type,
    )

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
