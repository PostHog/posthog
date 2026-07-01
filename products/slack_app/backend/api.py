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
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

import requests
import structlog
import posthoganalytics
from slack_sdk.errors import SlackApiError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.event_usage import groups
from posthog.git import extract_explicit_repo
from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
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
from posthog.temporal.ai.slack_app import (
    PostHogCodeSlackMentionCommandWorkflowInputs,
    PostHogCodeSlackMentionWorkflowInputs,
    derive_mention_workflow_id,
)
from posthog.temporal.ai.slack_app.posthog_code_slack_interactivity import (
    PostHogCodeSlackInteractivityInputs,
    PostHogCodeSlackTerminateTaskWorkflow,
)
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import PostHogCodeSlackMentionWorkflow
from posthog.temporal.ai.slack_app.posthog_code_slack_mention_command import PostHogCodeSlackMentionCommandWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.user_permissions import UserPermissions
from posthog.utils import get_instance_region

from products.slack_app.backend import inbox_channel, onboarding
from products.slack_app.backend.feature_flags import (
    is_slack_app_assistant_enabled,
    is_slack_app_oauth_enabled,
    is_slack_app_untagged_thread_followups_enabled,
)
from products.slack_app.backend.models import SlackChannel, SlackThreadTaskMapping
from products.slack_app.backend.services import inbox_interactivity
from products.slack_app.backend.services.agent_permissions import (
    SLACK_PERMISSION_ACTION_APPROVE,
    SLACK_PERMISSION_ACTION_DENY,
    SLACK_PERMISSION_ACTION_SELECT,
    SLACK_PERMISSION_CONTEXT_KIND,
)
from products.slack_app.backend.services.integration_resolver import (
    UserResolutionFailure,
    format_project_candidate_list,
    load_integrations,
    resolve_user_for_workspace,
    user_resolution_failure_reply,
)
from products.slack_app.backend.services.slack_app_home import (
    ACTION_EDIT_PERSONAL,
    ACTION_EDIT_WORKSPACE,
    ACTION_RESET_PERSONAL,
    ACTION_RESET_PROJECT_PERSONAL,
    ACTION_SET_PROJECT_PERSONAL,
    ACTION_SET_PROJECT_WORKSPACE,
    ACTION_TASKS_FILTER_REPO,
    ACTION_TASKS_FILTER_STATUS,
    ACTION_TASKS_PAGE_NEXT,
    ACTION_TASKS_PAGE_PREV,
    ACTION_TASKS_REFRESH,
    ACTION_UNLINK_ACCOUNT,
    EDIT_MODAL_PERSONAL_CALLBACK_ID,
    EDIT_MODAL_WORKSPACE_CALLBACK_ID,
    MODAL_ACTION_MODEL,
    MODAL_ACTION_RUNTIME_ADAPTER,
    handle_ai_preferences_block_action as _handle_ai_preferences_block_action,
    handle_app_home_opened as _handle_app_home_opened,
    handle_app_home_view_submission as _handle_app_home_view_submission,
)
from products.slack_app.backend.services.slack_user_info import (
    get_cached_bot_user_id,
    get_slack_user_info,
    normalize_slack_response,
    persist_slack_user_info,
)
from products.slack_app.backend.services.slack_user_oauth import (
    build_invite_url,
    find_linked_posthog_user,
    post_link_invite_message,
)
from products.slack_app.backend.slack_link_unfurl import handle_posthog_link_unfurl
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.client import signal_task_permission_response

logger = structlog.get_logger(__name__)

HANDLED_EVENT_TYPES = [
    "app_mention",
    "link_shared",
    "message",
    "member_joined_channel",
    "assistant_thread_started",
    "assistant_thread_context_changed",
    "app_home_opened",
]

# The notifications Slack app (`slack`) install carries every scope the coding-agent flow
# needs, so both surfaces share one kind.
SLACK_INTEGRATION_KIND = "slack"
LOCAL_DEV_SLACK_EMAIL = "test@posthog.com"

# Onboarding-on-join dedupe TTL: just long enough to absorb Slack retries and
# a near-simultaneous cross-region race during cutover. A real re-add after
# this window should re-onboard — most likely the person forgot how it works.
CHANNEL_ONBOARDING_DEDUPE_TTL_SECONDS = 60 * 10
CHANNEL_ONBOARDING_DOCS_URL = "https://posthog.com/docs/slack-app"

ROUTE_HANDLED_LOCALLY = "handled_locally"
ROUTE_PROXIED = "proxied"
ROUTE_PROXY_FAILED = "proxy_failed"
ROUTE_NO_INTEGRATION = "no_integration"

PICKER_TOKEN_SALT = "posthog_code_repo_picker"
PICKER_TOKEN_MAX_AGE_SECONDS = 900

CHANNEL_APPROVAL_BLOCK_ID_PREFIX = "posthog_code_channel_approval"
CHANNEL_APPROVAL_ACTION_APPROVE = "posthog_code_channel_approve"
CHANNEL_APPROVAL_ACTION_DENY = "posthog_code_channel_deny"
CHANNEL_APPROVAL_CONTEXT_KIND = "channel_approval"

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
    # `None` on the linked-user path: the OAuth link binds slack_user_id to a
    # PostHog user without ever consulting Slack's email, so no value is
    # available. The email-matching path still always populates this.
    slack_email: str | None


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
        "slack_app_slack_blocked_by_quota",
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
        slack_team_id = integration.integration_id

        # Linked-user path: when the user has bound their Slack identity to a
        # PostHog account via the OAuth link flow, we resolve directly without
        # paying for users.info / email matching. Falls through to the email
        # path on miss so this stays additive — a workspace with no links
        # behaves exactly like before.
        #
        # The link lookup runs FIRST (two cheap indexed queries) and the flag
        # check only fires when a row is found, and on the email-mismatch
        # failure branch below to decide whether to offer the invite button.
        # Both checks are local-evaluation only (`only_evaluate_locally=True`),
        # so calling twice on the rare both-branches path is essentially free.
        linked_user = find_linked_posthog_user(
            slack_user_id=slack_user_id,
            slack_team_id=slack_team_id,
            candidate_org_ids={integration.team.organization_id},
        )

        if linked_user is not None and is_slack_app_oauth_enabled(integration, slack_team_id):
            user_permissions = UserPermissions(user=linked_user, team=integration.team)
            if user_permissions.current_team.effective_membership_level is None:
                logger.warning(
                    "slack_app_linked_user_no_team_access",
                    user_id=linked_user.id,
                    team_id=integration.team_id,
                    slack_user_id=slack_user_id,
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
            return SlackUserContext(user=linked_user, slack_email=None)

        slack_email = get_slack_email_for_user(integration, slack_user_id)
        if settings.DEBUG:
            # Local dev: match the seeded test fixture user regardless of what
            # Slack returns. Applied here rather than in the shared helper so
            # other callers (e.g. `resolve_posthog_user_from_event` from the
            # channel-approval path) can still drive the helper with stubbed
            # Slack responses in tests.
            slack_email = LOCAL_DEV_SLACK_EMAIL

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

        # Trust model: Slack signature validation proves the payload is authentic.
        # The email comes from Slack's `users.info` API via `users:read.email` scope, not from
        # user-supplied input. Slack verifies emails at workspace sign-up, and admins control
        # membership
        membership = (
            OrganizationMembership.objects.filter(
                organization_id=integration.team.organization_id, user__email__iexact=slack_email
            )
            .select_related("user")
            .first()
        )
        if not membership or not membership.user:
            organization_name = integration.team.organization.name
            if post_feedback:
                # Two messages by design, with distinct audiences:
                #
                #   * The text reply goes into the thread (`prefer_thread_message=True`)
                #     so other channel members can see why the bot stayed silent on
                #     this mention. Without it, the channel reads as if the mention
                #     was simply ignored.
                #   * The invite-button message is ephemeral — only the affected
                #     user sees the recovery affordance. Posting the button into
                #     the public thread would be noise for everyone else.
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
                if is_slack_app_oauth_enabled(integration, slack_team_id):
                    invite_url = build_invite_url(
                        slack_user_id=slack_user_id,
                        slack_team_id=slack_team_id,
                        posthog_team_id=integration.team_id,
                        channel=channel,
                        thread_ts=thread_ts,
                    )
                    post_link_invite_message(
                        slack_client=slack.client,
                        channel=channel,
                        slack_user_id=slack_user_id,
                        thread_ts=thread_ts,
                        slack_email=slack_email,
                        invite_url=invite_url,
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


def cross_region_routing_enabled() -> bool:
    # Cross-region routing only makes sense between PostHog Cloud US and EU — they share the
    # Slack app's signing secret and split workspace ownership between them. The hosted dev
    # environment (CLOUD_DEPLOYMENT="DEV"), local dev, E2E, and self-hosted deployments all run
    # as a single region; proxying their Slack events to us.posthog.com targets a different
    # signing secret and a workspace this region doesn't own, which surfaces as a 403 on every
    # webhook hit (see slack_app_region_proxy_non_success).
    return get_instance_region() in ("US", "EU")


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


def is_us_host(host: str) -> bool:
    return host == _us_region_domain()


def other_region_domain(incoming_host: str) -> str:
    return _eu_region_domain() if is_us_host(incoming_host) else _us_region_domain()


def was_proxied(request: HttpRequest) -> bool:
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

    target_domain = other_region_domain(incoming_host)
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


def parse_rules_command(text: str) -> RulesCommand | None:
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
        response_data = normalize_slack_response(response)
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
    """Extract an explicit org/repo token from Slack message text, if it matches connected repos."""
    return extract_explicit_repo(_strip_bot_mentions(text), all_repos)


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
            "slack_app_repo_submit_picker_update_failed",
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
            "slack_app_repo_none_picker_update_failed",
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
        logger.exception("slack_app_pending_picker_repo_fetch_failed", integration_id=integration.id)
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
            "slack_app_pending_picker_signal_failed",
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
        "slack_app_pending_picker_resolved_from_followup",
        workflow_id=workflow_id,
        integration_id=integration.id,
        channel=channel,
        thread_ts=thread_ts,
        repository=selected_repo,
    )
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


def _thread_message_ignore_reason(event: dict[str, Any]) -> str | None:
    """Return a short reason if this ``message`` event shouldn't be considered as an
    untagged thread follow-up, else None.

    Distinct from ``_app_mention_ignore_reason`` because ``message`` events have
    more subtypes worth dropping early — joins, leaves, deletions — and arrive
    in vastly higher volume (every message in every channel the bot is in), so
    the cheap gates here run before any DB or LLM work.
    """
    if not event.get("user"):
        return "no_user"
    if not event.get("text"):
        return "no_text"
    if event.get("edited") or event.get("subtype") == "message_changed":
        return "edit"
    if event.get("subtype") == "message_deleted":
        return "deleted"
    if (
        event.get("bot_id")
        or event.get("bot_profile")
        or event.get("app_id")
        or event.get("subtype") == "bot_message"
        or event.get("user") == "USLACKBOT"
    ):
        return "bot_author"
    # Any other ``subtype`` (channel_join, channel_leave, thread_broadcast,
    # etc.) is system noise from this gate's perspective. ``thread_broadcast``
    # is the only one a human types, but it's typically an announcement to the
    # parent channel, not agent-directed work.
    if event.get("subtype"):
        return f"subtype:{event.get('subtype')}"
    return None


def _resolve_untagged_followup_mapping(
    *,
    candidates: list[Integration],
    channel: str | None,
    thread_ts: str | None,
    slack_team_id: str,
) -> SlackThreadTaskMapping | None:
    """Look up a ``SlackThreadTaskMapping`` for an untagged thread reply and
    confirm the integration's org has opted in via the feature flag.

    Returns the mapping when the message should enter the shared routing
    pipeline; ``None`` when it should drop. Two distinct ``None`` cases —
    no mapping (thread we don't own) and FF off — are logged separately so
    rollout dashboards can tell them apart.
    """
    candidate_ids = [c.id for c in candidates]
    # ``task`` is fetched separately inside the classifier activity — the
    # handler hot path only needs the integration (for the FF check + the
    # ``mention_target`` override downstream).
    mapping = (
        SlackThreadTaskMapping.objects.filter(
            integration_id__in=candidate_ids,
            channel=channel,
            thread_ts=thread_ts,
        )
        .select_related("integration", "integration__team")
        .first()
    )
    if mapping is None:
        return None
    if not is_slack_app_untagged_thread_followups_enabled(mapping.integration, slack_team_id):
        logger.info(
            "slack_app_thread_message_feature_flag_off",
            slack_team_id=slack_team_id,
            channel=channel,
            thread_ts=thread_ts,
            integration_id=mapping.integration_id,
        )
        return None
    return mapping


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
        "slack_app_slack_missing_scopes",
        integration_id=integration.id,
        team_id=integration.team_id,
        missing=sorted(missing),
    )

    if not channel or not thread_ts or not slack_user_id:
        return

    settings_url = f"{settings.SITE_URL}/integrations/slack"
    text = (
        ":warning: PostHog can't reply because the Slack integration is missing required "
        f"permissions: `{', '.join(sorted(missing))}`.\n"
        f"A project admin needs to reconnect Slack from project settings: {settings_url}"
    )

    _post_slack_user_feedback(slack, channel, slack_user_id, thread_ts, text, prefer_thread_message=True)


def get_slack_email_for_user(probe_integration: Integration, slack_user_id: str) -> str | None:
    """Best-effort lookup of the Slack user's email via ``users.info``, cache-first then
    a fresh hit on miss. Returns ``None`` when Slack doesn't expose an email for the
    user (profile email hidden) or the lookup fails.

    Every termination path emits a distinct structured log so a silent ``None`` can
    still be diagnosed from logs alone — historically the failure modes collapsed
    onto a downstream ``user_not_found`` warning that hid the actual cause.

    Auth-class ``SlackApiError`` outcomes flip the shared ``slack_auth`` cache to
    ``ok=false`` so the resolver demotes this install on subsequent mentions
    rather than pinning every one to a dead token. The success path deliberately
    does NOT write ``ok=true``: the cache lives in the resolver's ``auth.test``
    layer, and a DB-cache hit (``SlackUserProfileCache``) proves nothing about
    the live token. Letting the resolver own the positive verdict keeps the
    cache truthful.
    """
    from products.slack_app.backend.services.slack_auth import SLACK_AUTH_FAILURE_CODES, write_auth_state_broken

    slack_client = SlackIntegration(probe_integration)
    try:
        user_info = get_slack_user_info(slack_client, probe_integration, slack_user_id)
        slack_email = user_info.get("user", {}).get("profile", {}).get("email")
        if slack_email:
            return slack_email

        fresh = normalize_slack_response(slack_client.client.users_info(user=slack_user_id))
        if not fresh:
            logger.warning(
                "slack_app_resolve_user_email_empty_response",
                integration_id=probe_integration.id,
                slack_user_id=slack_user_id,
            )
            return None

        persist_slack_user_info(probe_integration, slack_user_id, fresh)
        slack_email = fresh.get("user", {}).get("profile", {}).get("email")
        if not slack_email:
            logger.warning(
                "slack_app_resolve_user_email_missing_in_profile",
                integration_id=probe_integration.id,
                slack_user_id=slack_user_id,
                ok=fresh.get("ok"),
            )
            return None
        return slack_email
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        token_broken = isinstance(error_code, str) and error_code in SLACK_AUTH_FAILURE_CODES
        if token_broken and isinstance(error_code, str):
            write_auth_state_broken(probe_integration.id, error_code)
        logger.warning(
            "slack_app_resolve_user_email_failed",
            integration_id=probe_integration.id,
            slack_user_id=slack_user_id,
            error_code=error_code,
            token_broken=token_broken,
            exc_info=True,
        )
        return None
    except Exception:
        logger.warning(
            "slack_app_resolve_user_email_failed",
            integration_id=probe_integration.id,
            slack_user_id=slack_user_id,
            error_code=None,
            token_broken=False,
            exc_info=True,
        )
        return None


def resolve_posthog_user_from_event(
    *,
    slack_user_id: str,
    probe_integration: Integration,
    candidate_integrations: list[Integration],
    slack_email: str | None = None,
) -> User | None:
    """Resolve the acting Slack user to a PostHog ``User`` who is a member of
    at least one organization connected to this Slack workspace.

    The probe is used to call Slack's ``users.info``; the candidate list scopes
    the organization-membership check. A user with no membership in any
    connected org returns ``None`` so the caller can refuse the event.

    ``slack_email`` may be passed by callers that already have it (e.g.
    ``resolve_user_and_integrations``) so we don't repeat the cache lookup.
    """
    org_ids = {c.team.organization_id for c in candidate_integrations}
    if not org_ids:
        return None

    # Linked-user path: short-circuit the email match when the user has bound
    # their Slack identity to a PostHog account. The cheap indexed lookup
    # runs first; the feature-flag gate only fires when a row is found so
    # workspaces with no linked users don't pay for the flag evaluation.
    slack_team_id = probe_integration.integration_id
    linked_user = find_linked_posthog_user(
        slack_user_id=slack_user_id,
        slack_team_id=slack_team_id,
        candidate_org_ids=org_ids,
    )
    if linked_user is not None and is_slack_app_oauth_enabled(probe_integration, slack_team_id):
        return linked_user

    if slack_email is None:
        slack_email = get_slack_email_for_user(probe_integration, slack_user_id)
    if not slack_email:
        return None
    try:
        membership = (
            OrganizationMembership.objects.filter(organization_id__in=org_ids, user__email__iexact=slack_email)
            .select_related("user")
            .first()
        )
    except Exception:
        # Don't propagate transient DB errors to the Slack webhook — Slack
        # retries 5xx and would replay the event. The caller gets ``None`` and
        # treats it the same as "no membership found".
        logger.warning(
            "slack_app_resolve_user_membership_failed",
            integration_id=probe_integration.id,
            slack_user_id=slack_user_id,
            exc_info=True,
        )
        return None
    return membership.user if membership else None


def _post_pick_a_project_hint(
    probe: SlackIntegration,
    candidates: list[Integration],
    event: dict[str, Any],
) -> None:
    """Tell the user that this workspace is connected to multiple PostHog
    projects, and that they should pick one.

    The selection command differs by surface: in a channel the user mentions the app
    (`@PostHog project <id>`), but in a DM there is no app to mention, so they just reply
    with `project <id>`.
    """
    slack_user_id = event.get("user")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    if not isinstance(slack_user_id, str) or not isinstance(channel, str) or not isinstance(thread_ts, str):
        return
    pick_command = "`project <id>`" if event.get("channel_type") == "im" else "`@PostHog project <id>`"
    text = (
        "This Slack workspace is connected to multiple PostHog projects:\n"
        f"{format_project_candidate_list(candidates)}\n\n"
        f"Use {pick_command} to pick one — that also saves it as your default."
    )
    _post_slack_user_feedback(probe, channel, slack_user_id, thread_ts, text, prefer_thread_message=True)


def _post_user_resolution_failure_reply(
    *,
    probe: Integration,
    channel: str | None,
    slack_user_id: str | None,
    thread_ts: str | None,
    failure_reason: UserResolutionFailure | None,
    slack_email: str | None,
) -> None:
    """Tell a Slack user when we can't route their mention to a PostHog project.

    Posts in-thread (with the established ephemeral fallback in
    ``_post_slack_user_feedback``) so the message lands in the place the
    mention happened. ``failure_reason`` is mapped to the user-facing text by
    ``user_resolution_failure_reply``; ``slack_email`` is woven in when known
    so the user sees which address PostHog tried to match.
    """
    if not channel or not thread_ts or not slack_user_id:
        return
    text = user_resolution_failure_reply(failure_reason, slack_email=slack_email)
    if text is None:
        return
    slack_client = SlackIntegration(probe)
    # The text reply lands in the thread so the rest of the channel knows why
    # the bot stayed silent. The invite button is a separate ephemeral, visible
    # only to the affected user — both messages have distinct audiences and
    # neither is redundant. Only `user_not_found` is link-recoverable;
    # `no_team_access` means the user *is* known but lacks project access.
    _post_slack_user_feedback(slack_client, channel, slack_user_id, thread_ts, text, prefer_thread_message=True)
    if failure_reason == "user_not_found" and is_slack_app_oauth_enabled(probe, probe.integration_id):
        invite_url = build_invite_url(
            slack_user_id=slack_user_id,
            slack_team_id=probe.integration_id,
            posthog_team_id=probe.team_id,
            channel=channel,
            thread_ts=thread_ts,
        )
        post_link_invite_message(
            slack_client=slack_client.client,
            channel=channel,
            slack_user_id=slack_user_id,
            thread_ts=thread_ts,
            slack_email=slack_email,
            invite_url=invite_url,
        )


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
            task_queue=settings.TASKS_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


_ASSISTANT_CONTEXT_TTL_SECONDS = 60 * 60
_ASSISTANT_SUGGESTED_PROMPTS = [
    {"title": "Fix a bug", "message": "Open a PR to fix a bug in my connected repo"},
    {"title": "Investigate an issue", "message": "Investigate why one of my insights is slow"},
    {"title": "Work an inbox item", "message": "Pick up a signals inbox item that needs a code fix"},
]
_ASSISTANT_WELCOME = (
    "Hi! I'm PostHog, an AI agent. DM me to investigate issues using your PostHog data and "
    "open PRs in your connected repos to fix them!"
)
_ASSISTANT_INSTALL_WELCOME = (
    "Thanks for adding PostHog! :tada: I'm an AI agent - DM me here or @mention me in a channel "
    "to investigate issues or open PRs in your connected repos"
)
_ASSISTANT_UNAVAILABLE = (
    "I can only help PostHog org members whose project has a connected repo. Make sure your Slack "
    "email matches your PostHog account and that a repo is connected, then try again."
)


def _assistant_event_fields(event: dict) -> tuple[str, str | None, str | None, str | None]:
    """(slack_user_id, dm_channel_id, thread_ts, viewed_channel_id) for assistant events.

    For `message` events the fields live at the top level; for `assistant_thread_*` events
    they live under `assistant_thread` (with the viewed channel under `context`).
    """
    if event.get("type") == "message":
        ts = event.get("thread_ts") or event.get("ts")
        return (
            str(event.get("user") or ""),
            event.get("channel") if isinstance(event.get("channel"), str) else None,
            ts if isinstance(ts, str) else None,
            None,
        )
    thread = event.get("assistant_thread") or {}
    ctx = thread.get("context") or {}
    return (
        str(thread.get("user_id") or ""),
        thread.get("channel_id") if isinstance(thread.get("channel_id"), str) else None,
        thread.get("thread_ts") if isinstance(thread.get("thread_ts"), str) else None,
        ctx.get("channel_id") if isinstance(ctx.get("channel_id"), str) else None,
    )


def _assistant_context_cache_key(integration_id: int, channel_id: str, thread_ts: str) -> str:
    return f"slack_assistant_ctx:{integration_id}:{channel_id}:{thread_ts}"


def _store_assistant_channel_context(
    integration_id: int, channel_id: str, thread_ts: str, viewed_channel_id: str | None
) -> None:
    if viewed_channel_id:
        cache.set(
            _assistant_context_cache_key(integration_id, channel_id, thread_ts),
            viewed_channel_id,
            timeout=_ASSISTANT_CONTEXT_TTL_SECONDS,
        )


def _get_assistant_channel_context(integration_id: int, channel_id: str, thread_ts: str) -> str | None:
    value = cache.get(_assistant_context_cache_key(integration_id, channel_id, thread_ts))
    return value if isinstance(value, str) else None


def _handle_assistant_thread_started(slack: SlackIntegration, channel_id: str, thread_ts: str) -> str:
    """Greet the user and offer suggested prompts when they open the agent container."""
    try:
        slack.client.assistant_threads_setSuggestedPrompts(
            channel_id=channel_id,
            thread_ts=thread_ts,
            title="What can I help you ship?",
            prompts=_ASSISTANT_SUGGESTED_PROMPTS,
        )
        slack.client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=_ASSISTANT_WELCOME)
    except Exception:
        logger.warning("assistant_thread_started_failed", exc_info=True)
    return ROUTE_HANDLED_LOCALLY


def _post_assistant_unavailable(slack: SlackIntegration, channel_id: str, thread_ts: str) -> None:
    try:
        slack.client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=_ASSISTANT_UNAVAILABLE)
    except Exception:
        logger.warning("assistant_unavailable_post_failed", exc_info=True)


def send_assistant_install_welcome(integration: Integration) -> None:
    """DM the installing user the moment the app is added, when the assistant is enabled for their team."""
    if not is_slack_app_assistant_enabled(integration.team):
        return
    slack_user_id = ((integration.config or {}).get("authed_user") or {}).get("id")
    if not slack_user_id:
        return
    try:
        SlackIntegration(integration).client.chat_postMessage(channel=slack_user_id, text=_ASSISTANT_INSTALL_WELCOME)
    except Exception:
        logger.warning("assistant_install_welcome_failed", exc_info=True)


# The DM/agent surface needs the base coding-agent scopes plus the assistant container scopes.
# Kept separate from REQUIRED_SLACK_SCOPES so the mention flow isn't gated on im:history.
_ASSISTANT_REQUIRED_SLACK_SCOPES = REQUIRED_SLACK_SCOPES | frozenset({"assistant:write", "im:history"})


def _handle_assistant_dm_message(
    event: dict,
    integration: Integration,
    slack_team_id: str,
    event_id: str | None,
    channel_id: str,
    thread_ts: str,
    *,
    posthog_user: User,
) -> str:
    slack = SlackIntegration(integration)
    missing = slack.missing_scopes(_ASSISTANT_REQUIRED_SLACK_SCOPES)
    if missing:
        _notify_missing_slack_scopes(slack, event, missing)
        return ROUTE_HANDLED_LOCALLY

    try:
        slack.client.assistant_threads_setStatus(channel_id=channel_id, thread_ts=thread_ts, status="Working on it…")
    except Exception:
        logger.warning("assistant_set_status_failed", exc_info=True)

    # Carry the channel the user was viewing (from assistant_thread_context_changed) so the agent
    # can ground a "look into this" DM in that channel's context.
    viewed = _get_assistant_channel_context(integration.id, channel_id, thread_ts)
    agent_event = {**event, "assistant_viewed_channel_id": viewed} if viewed else event
    return _start_mention_workflow(agent_event, integration, slack_team_id, event_id, posthog_user=posthog_user)


def _route_assistant_event(
    request: HttpRequest,
    event: dict,
    slack_team_id: str,
    event_id: str | None,
    *,
    proxied: bool,
    incoming_host: str,
    other_domain: str,
    can_defer: bool,
) -> str:
    """Route DM / agent-container events through the same region + project resolution as mentions."""
    event_type = event.get("type")
    slack_user_id, channel_id, thread_ts, ctx_channel = _assistant_event_fields(event)

    # Only first-party human DMs proceed — ignore channel messages, bot echoes, and edits.
    if event_type == "message" and (
        event.get("channel_type") != "im"
        or event.get("bot_id")
        or event.get("subtype")
        or not str(event.get("text") or "").strip()
    ):
        return ROUTE_HANDLED_LOCALLY
    if not (slack_user_id and channel_id and thread_ts):
        return ROUTE_HANDLED_LOCALLY

    result = load_integrations(
        slack_team_id=slack_team_id,
        kinds=[SLACK_INTEGRATION_KIND],
        slack_user_id=slack_user_id,
        user=None,
        channel=channel_id,
        thread_ts=thread_ts,
    )
    region_route = resolve_region_or_terminal_route(
        request,
        slack_team_id,
        candidates_present=bool(result.candidates),
        kinds=[SLACK_INTEGRATION_KIND],
        proxied=proxied,
        other_domain=other_domain,
        incoming_host=incoming_host,
        can_defer=can_defer,
    )
    if region_route is not None:
        return region_route

    probe = result.integration if result.integration in result.candidates else result.candidates[0]

    # Kill-switch first: stay fully dark (no user resolution, no Slack reply) when the flag is off.
    if not is_slack_app_assistant_enabled(probe.team):
        return ROUTE_HANDLED_LOCALLY

    # Share the mention path's user resolution + access filter, so the DM only ever sees and runs
    # against projects the resolved PostHog user can actually access (no cross-org metadata leak).
    resolution = resolve_user_for_workspace(
        workspace_result=result,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        event_id=event_id,
    )
    if resolution.user is None:
        # Flag is on but the Slack user isn't a resolvable org member — tell them why (DMs only).
        if event_type == "message":
            _post_assistant_unavailable(SlackIntegration(probe), channel_id, thread_ts)
        return ROUTE_HANDLED_LOCALLY
    posthog_user = resolution.user

    if event_type == "assistant_thread_started":
        return _handle_assistant_thread_started(SlackIntegration(probe), channel_id, thread_ts)
    if event_type == "assistant_thread_context_changed":
        _store_assistant_channel_context(probe.id, channel_id, thread_ts, ctx_channel)
        return ROUTE_HANDLED_LOCALLY

    # message.im — run the agent against the user's accessible default project, else ask them to pick.
    accessible = resolution.candidates
    mention_target = resolution.integration or (accessible[0] if len(accessible) == 1 else None)
    if mention_target is None:
        _post_pick_a_project_hint(SlackIntegration(accessible[0]), accessible, event)
        return ROUTE_HANDLED_LOCALLY
    return _handle_assistant_dm_message(
        event, mention_target, slack_team_id, event_id, channel_id, thread_ts, posthog_user=posthog_user
    )


def route_posthog_code_event_to_relevant_region(
    request: HttpRequest,
    event: dict,
    slack_team_id: str,
    event_id: str | None = None,
    *,
    is_ext_shared_channel: bool = False,
) -> str:
    event_type = event.get("type")
    incoming_host = request.get_host()
    proxied = was_proxied(request)
    other_domain = other_region_domain(incoming_host)
    # In local dev we run a single instance, so cross-region routing is meaningless: the only
    # consumer is this process. Disable both the probe and the proxy hop and always handle
    # locally.
    can_defer_to_other_region = cross_region_routing_enabled() and not is_us_host(incoming_host) and not proxied

    logger.info(
        "slack_app_route_enter",
        incoming_host=incoming_host,
        is_us=is_us_host(incoming_host),
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

    # App Home tab: published per-user when they open the Home tab. Always
    # handled locally — `views.publish` just renders a snapshot of the user's
    # AI preferences against the integration row, no cross-region state.
    if event_type == "app_home_opened":
        try:
            _handle_app_home_opened(event, slack_team_id)
        except Exception:
            logger.exception("slack_app_home_opened_failed", slack_team_id=slack_team_id, event_id=event_id)
        return ROUTE_HANDLED_LOCALLY

    # Assistant surface: DMs to the app and agent-container events resolve the DMing user and run
    # against their project. A ``message`` is a DM iff ``channel_type == "im"`` — channel ``message``
    # events (untagged thread follow-ups) and ``app_mention`` share the pipeline below instead.
    if event_type in ("assistant_thread_started", "assistant_thread_context_changed") or (
        event_type == "message" and event.get("channel_type") == "im"
    ):
        return _route_assistant_event(
            request,
            event,
            slack_team_id,
            event_id,
            proxied=proxied,
            incoming_host=incoming_host,
            other_domain=other_domain,
            can_defer=can_defer_to_other_region,
        )

    if event_type in ("app_mention", "message"):
        if event_type == "app_mention":
            ignore_reason = _app_mention_ignore_reason(event)
            if ignore_reason:
                logger.info(
                    "slack_app_event_app_mention_ignored",
                    reason=ignore_reason,
                    slack_team_id=slack_team_id,
                    channel=event.get("channel"),
                    message_ts=event.get("ts"),
                )
                return ROUTE_HANDLED_LOCALLY
        else:
            ignore_reason = _thread_message_ignore_reason(event)
            if ignore_reason:
                logger.info(
                    "slack_app_thread_message_ignored",
                    reason=ignore_reason,
                    slack_team_id=slack_team_id,
                    channel=event.get("channel"),
                    message_ts=event.get("ts"),
                )
                return ROUTE_HANDLED_LOCALLY
            # Top-level channel posts dominate the wire volume; drop before any DB hit.
            top_level_thread_ts = event.get("thread_ts")
            if not isinstance(top_level_thread_ts, str) or top_level_thread_ts == event.get("ts"):
                return ROUTE_HANDLED_LOCALLY

        slack_user_id_str = str(event.get("user") or "")
        channel_str = event.get("channel") if isinstance(event.get("channel"), str) else None
        thread_ts_value = event.get("thread_ts") or event.get("ts")
        thread_ts_str = thread_ts_value if isinstance(thread_ts_value, str) else None

        # Region routing only needs candidate presence, not user resolution. We
        # defer the Slack ``users.info`` hit and the ``OrganizationMembership``
        # query until we know this region is handling the event so cross-region
        # proxied events don't pay for work the receiving region will redo.
        workspace_result = load_integrations(
            slack_team_id=slack_team_id,
            kinds=[SLACK_INTEGRATION_KIND],
            slack_user_id=slack_user_id_str,
            channel=channel_str,
            thread_ts=thread_ts_str,
        )
        region_route = resolve_region_or_terminal_route(
            request,
            slack_team_id,
            candidates_present=bool(workspace_result.candidates),
            kinds=[SLACK_INTEGRATION_KIND],
            proxied=proxied,
            other_domain=other_domain,
            incoming_host=incoming_host,
            can_defer=can_defer_to_other_region,
        )
        if region_route is not None:
            return region_route

        # Threads we don't own (and orgs that haven't opted in) are dropped here
        # so the rest of the pipeline only runs for actionable messages.
        untagged_followup_mapping: SlackThreadTaskMapping | None = None
        if event_type == "message":
            untagged_followup_mapping = _resolve_untagged_followup_mapping(
                candidates=workspace_result.candidates,
                channel=channel_str,
                thread_ts=thread_ts_str,
                slack_team_id=slack_team_id,
            )
            if untagged_followup_mapping is None:
                return ROUTE_HANDLED_LOCALLY

        # Both event types share the rest of the pipeline. Mention-only side
        # effects (failure reply, scope notice, approval prompt, rules command,
        # picker hint) are silent drops for untagged followups — the originating
        # ``app_mention`` already cleared those gates.
        resolution = resolve_user_for_workspace(
            workspace_result=workspace_result,
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id_str,
            event_id=event_id,
        )

        if resolution.user is None:
            if untagged_followup_mapping is not None:
                logger.info(
                    "slack_app_thread_message_unknown_user",
                    slack_team_id=slack_team_id,
                    channel=channel_str,
                    thread_ts=thread_ts_str,
                    slack_user_id=slack_user_id_str,
                )
                return ROUTE_HANDLED_LOCALLY
            # Skip the failure reply in an unapproved externally-shared channel —
            # the channel hasn't opted in yet, so a public "Sorry, I couldn't
            # find <email>" post would leak the integration's existence to
            # non-org members. Still capture the mention analytics-side so the
            # unknown-user funnel keeps reporting (it ran on every mention before
            # this PR moved resolution up).
            probe = workspace_result.candidates[0]
            _report_slack_mention_received(event, probe, slack_team_id, posthog_user=None)
            channel_id = event.get("channel") if isinstance(event.get("channel"), str) else None
            if not (is_ext_shared_channel and channel_id and not _channel_is_approved(slack_team_id, channel_id)):
                _post_user_resolution_failure_reply(
                    probe=probe,
                    channel=channel_str,
                    slack_user_id=slack_user_id_str,
                    thread_ts=thread_ts_str,
                    failure_reason=resolution.failure_reason,
                    slack_email=resolution.slack_email,
                )
            return ROUTE_HANDLED_LOCALLY

        posthog_user = resolution.user
        candidates = resolution.candidates
        target = resolution.integration

        # Rules command is meaningful only when the user actually typed
        # ``@PostHog`` — an untagged thread reply can never be a rules command.
        if untagged_followup_mapping is None and parse_rules_command(event.get("text", "")) is not None:
            return _start_command_workflow(event, candidates, slack_team_id, event_id, user_id=posthog_user.id)

        # A tagged-thread ``message`` is bound to its mapping's integration —
        # the mapping was the user's last explicit choice in this thread, so no
        # picker hint applies. The user must still have access to the bound
        # integration's team though: ``resolution.candidates`` is already
        # filtered by access, so requiring the mapping integration to be in it
        # closes the gap where the message author belongs to a different org
        # connected to the same workspace than the thread owner did.
        mention_target = target or (candidates[0] if len(candidates) == 1 else None)
        if untagged_followup_mapping is not None:
            if untagged_followup_mapping.integration_id not in {c.id for c in candidates}:
                logger.info(
                    "slack_app_thread_message_user_no_access_to_mapping_team",
                    slack_team_id=slack_team_id,
                    channel=channel_str,
                    thread_ts=thread_ts_str,
                    user_id=posthog_user.id,
                    mapping_integration_id=untagged_followup_mapping.integration_id,
                )
                return ROUTE_HANDLED_LOCALLY
            mention_target = untagged_followup_mapping.integration
        elif mention_target is None:
            _post_pick_a_project_hint(SlackIntegration(candidates[0]), candidates, event)
            return ROUTE_HANDLED_LOCALLY

        slack = SlackIntegration(mention_target)
        missing = slack.missing_scopes(REQUIRED_SLACK_SCOPES)
        if missing:
            if untagged_followup_mapping is not None:
                logger.info(
                    "slack_app_thread_message_missing_scopes",
                    slack_team_id=slack_team_id,
                    integration_id=mention_target.id,
                )
                return ROUTE_HANDLED_LOCALLY
            _notify_missing_slack_scopes(slack, event, missing)
            return ROUTE_HANDLED_LOCALLY

        channel_id = event.get("channel") if isinstance(event.get("channel"), str) else None
        if channel_id and is_ext_shared_channel and not _channel_is_approved(mention_target.integration_id, channel_id):
            if untagged_followup_mapping is not None:
                logger.info(
                    "slack_app_thread_message_channel_unapproved",
                    slack_team_id=slack_team_id,
                    channel=channel_id,
                )
                return ROUTE_HANDLED_LOCALLY
            _post_channel_approval_prompt(slack, mention_target, event)
            return ROUTE_HANDLED_LOCALLY

        return _start_mention_workflow(
            event,
            mention_target,
            slack_team_id,
            event_id,
            posthog_user=posthog_user,
            untagged_followup=untagged_followup_mapping is not None,
            is_ext_shared_channel=is_ext_shared_channel,
        )

    if event_type == "member_joined_channel":
        return _route_member_joined_channel(
            request,
            event,
            slack_team_id,
            proxied=proxied,
            other_domain=other_domain,
            can_defer_to_other_region=can_defer_to_other_region,
            incoming_host=incoming_host,
            is_ext_shared_channel=is_ext_shared_channel,
        )

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
        "slack_app_route_us_probe_result",
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

    Single-region deployments (local dev, hosted dev, E2E, self-hosted) have no other region
    to forward to, so we just record the miss and stop.
    """
    if proxied or not cross_region_routing_enabled():
        logger.warning(
            "slack_app_no_integration_found",
            slack_team_id=slack_team_id,
            incoming_host=request.get_host(),
        )
        return ROUTE_NO_INTEGRATION
    return _proxy_event_and_return_route(request, other_domain)


def resolve_region_or_terminal_route(
    request: HttpRequest,
    slack_team_id: str,
    *,
    candidates_present: bool,
    kinds: list[str],
    proxied: bool,
    other_domain: str,
    incoming_host: str,
    can_defer: bool,
) -> str | None:
    """Shared region gate for every coding-agent surface (mentions, channel followups, DMs).

    Returns a terminal route when the event leaves this region — forwarded/dropped because no
    local integration claims the workspace, or proxied to US under the US-precedence rule — else
    ``None`` to signal the caller should keep handling the event locally.
    """
    if not candidates_present:
        return _route_to_other_region_or_drop(request, slack_team_id, proxied=proxied, other_domain=other_domain)
    if _us_should_handle_instead(slack_team_id, kinds, can_defer, incoming_host):
        return _proxy_event_and_return_route(request, other_domain)
    return None


def _start_command_workflow(
    event: dict,
    integrations: list[Integration],
    slack_team_id: str,
    event_id: str | None,
    *,
    user_id: int | None,
    command_prefix: str = "@PostHog",
) -> str:
    # ``user_id=None`` defers user resolution into the workflow — the slash entry
    # point uses it to keep its ack under Slack's 3s budget.
    _start_posthog_code_workflow(
        PostHogCodeSlackMentionCommandWorkflow,
        PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[i.id for i in integrations],
            slack_team_id=slack_team_id,
            user_id=user_id,
            command_prefix=command_prefix,
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
            "slack_app_mention_count_failed",
            integration_id=integration.id,
            channel=channel,
            thread_ts=thread_ts,
            exc_info=True,
        )
        return None


def _route_member_joined_channel(
    request: HttpRequest,
    event: dict[str, Any],
    slack_team_id: str,
    *,
    proxied: bool,
    other_domain: str,
    can_defer_to_other_region: bool,
    incoming_host: str,
    is_ext_shared_channel: bool,
) -> str:
    """Welcome the @PostHog bot to a new channel exactly once.

    Slack fires ``member_joined_channel`` for every user (including bot users)
    added to a channel. We only act when the joining user is our own bot, and
    we cache the first post per (workspace, channel) so retries and re-adds
    don't double-post. Externally-shared channels are dropped before any DB
    work — anyone outside the home workspace would see the welcome, and the
    first @PostHog mention there will run the existing approval flow.
    """
    joined_user = event.get("user") if isinstance(event.get("user"), str) else None
    channel_id = event.get("channel") if isinstance(event.get("channel"), str) else None
    if not joined_user or not channel_id:
        return ROUTE_HANDLED_LOCALLY

    # Drop ext-shared channels before touching the DB. Anyone outside the home
    # workspace would see the welcome message, and the ``is_ext_shared_channel``
    # flag lives on the event envelope so this costs nothing.
    if is_ext_shared_channel:
        return ROUTE_HANDLED_LOCALLY

    workspace_result = load_integrations(slack_team_id=slack_team_id, kinds=[SLACK_INTEGRATION_KIND])
    if not workspace_result.candidates:
        return _route_to_other_region_or_drop(request, slack_team_id, proxied=proxied, other_domain=other_domain)

    if _us_should_handle_instead(slack_team_id, [SLACK_INTEGRATION_KIND], can_defer_to_other_region, incoming_host):
        return _proxy_event_and_return_route(request, other_domain)

    integration = workspace_result.candidates[0]
    slack = SlackIntegration(integration)

    bot_user_id = get_cached_bot_user_id(slack, integration)
    if bot_user_id is None or joined_user != bot_user_id:
        # We only care about our own bot joining a channel. Every other join
        # (humans, third-party bots) is ignored silently — Slack fires this
        # event for every channel-membership change, so the volume is high.
        return ROUTE_HANDLED_LOCALLY

    # The onboarding flow has its own messaging for the inbox channel — skip the generic welcome here.
    if inbox_channel.is_inbox_channel(integration, channel_id):
        return ROUTE_HANDLED_LOCALLY

    if not _claim_channel_onboarding(slack_team_id, channel_id):
        logger.info(
            "slack_app_channel_onboarding_skipped_duplicate",
            slack_team_id=slack_team_id,
            channel_id=channel_id,
        )
        return ROUTE_HANDLED_LOCALLY

    posted = _post_channel_onboarding_message(slack, integration, channel_id)
    if not posted:
        # Release the dedupe slot so the next delivery (retry or future re-add)
        # gets another shot rather than being silently swallowed.
        _release_channel_onboarding_claim(slack_team_id, channel_id)

    return ROUTE_HANDLED_LOCALLY


def _channel_onboarding_cache_key(slack_team_id: str, channel_id: str) -> str:
    return f"slack_app:channel_onboarded:v1:{slack_team_id}:{channel_id}"


def _claim_channel_onboarding(slack_team_id: str, channel_id: str) -> bool:
    """Atomically claim the right to send the onboarding message.

    ``cache.add`` is the Django-blessed idempotency primitive: it returns True
    only if the key didn't already exist, so concurrent webhook deliveries
    (Slack retries, two-region race during cutover) can't double-post.
    """
    return bool(
        cache.add(
            _channel_onboarding_cache_key(slack_team_id, channel_id),
            True,
            timeout=CHANNEL_ONBOARDING_DEDUPE_TTL_SECONDS,
        )
    )


def _release_channel_onboarding_claim(slack_team_id: str, channel_id: str) -> None:
    cache.delete(_channel_onboarding_cache_key(slack_team_id, channel_id))


def _post_channel_onboarding_message(slack: SlackIntegration, integration: Integration, channel_id: str) -> bool:
    """Post the welcome message. Returns True on success."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":wave: Thanks for adding the PostHog app to this channel! "
                    "Mention me with `@PostHog` to get started – I can answer "
                    "questions about your PostHog data, research your codebase, "
                    "and kick off coding tasks backed by real usage data. "
                    "I'll also unfurl PostHog links you share here."
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*Try one of these:*\n"
                    "• `@PostHog what's our weekly active user count this month?`\n"
                    "• `@PostHog open a PR that adds a unit test for src/utils.py`"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Read the docs"},
                    "url": CHANNEL_ONBOARDING_DOCS_URL,
                }
            ],
        },
    ]

    try:
        slack.client.chat_postMessage(
            channel=channel_id,
            text="Thanks for adding the PostHog app – mention me with @PostHog to get started.",
            blocks=blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
        logger.info(
            "slack_app_channel_onboarding_posted",
            integration_id=integration.id,
            slack_workspace_id=integration.integration_id,
            channel_id=channel_id,
        )
        return True
    except Exception:
        logger.warning(
            "slack_app_channel_onboarding_post_failed",
            integration_id=integration.id,
            slack_workspace_id=integration.integration_id,
            channel_id=channel_id,
            exc_info=True,
        )
        return False


def _channel_is_approved(slack_workspace_id: str, channel_id: str) -> bool:
    """True iff a user in this channel has already granted PostHog approval.

    The ``is_ext_shared_channel`` flag that gates whether approval is required
    at all lives on the Slack event envelope — see ``posthog_code_event_handler``
    — so this only needs to answer the persistence question.
    """
    return SlackChannel.objects.filter(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=channel_id,
        approved_at__isnull=False,
    ).exists()


def _post_channel_approval_prompt(
    slack: SlackIntegration,
    integration: Integration,
    event: dict[str, Any],
) -> None:
    """Post the approval prompt as an ephemeral message to the mentioner.

    The prompt itself stays ephemeral — only the mentioner sees the
    buttons — but every click *outcome* (approve, deny, non-member
    rejection) is posted as a public threaded reply under the original
    mention so the whole channel has a permanent record.

    The ephemeral is **not** threaded: Slack only renders ephemerals on
    the surface the user is currently viewing, so an ephemeral with
    ``thread_ts`` is invisible from the channel main view — i.e. the
    place where the mentioner usually is right after typing the mention.
    Dropping ``thread_ts`` here is what makes the prompt actually visible.
    """
    channel = event.get("channel") if isinstance(event.get("channel"), str) else None
    slack_user_id = event.get("user") if isinstance(event.get("user"), str) else None
    if not channel or not slack_user_id:
        return

    raw_thread_ts = event.get("thread_ts") if isinstance(event.get("thread_ts"), str) else None
    message_ts = event.get("ts") if isinstance(event.get("ts"), str) else None
    thread_ts = raw_thread_ts or message_ts

    context_data = {
        "kind": CHANNEL_APPROVAL_CONTEXT_KIND,
        "integration_id": integration.id,
        "slack_workspace_id": integration.integration_id,
        "slack_channel_id": channel,
        "thread_ts": thread_ts,
        "created_at": int(time.time()),
    }
    context_token = uuid.uuid4().hex
    cache.set(
        _picker_context_cache_key(context_token),
        context_data,
        timeout=PICKER_TOKEN_MAX_AGE_SECONDS,
    )

    org_label = _org_label(integration)
    text = (
        f":wave: This is an externally-shared Slack channel. My answers can pull from {org_label}'s "
        "PostHog project — including data about users, customers, and other internal metrics that aren't "
        "otherwise visible in this channel — and anything I post will be seen by every member here, "
        f"including people outside {org_label}'s workspace. A member of {org_label} can enable me below."
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "block_id": f"{CHANNEL_APPROVAL_BLOCK_ID_PREFIX}:{context_token}",
            "text": {"type": "mrkdwn", "text": text},
        },
        {
            "type": "actions",
            "block_id": f"{CHANNEL_APPROVAL_BLOCK_ID_PREFIX}_actions:{context_token}",
            "elements": [
                {
                    "type": "button",
                    "action_id": CHANNEL_APPROVAL_ACTION_APPROVE,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "✅ Allow PostHog in this channel"},
                    "value": context_token,
                },
                {
                    "type": "button",
                    "action_id": CHANNEL_APPROVAL_ACTION_DENY,
                    "text": {"type": "plain_text", "text": "✋ Not here"},
                    "value": context_token,
                },
            ],
        },
    ]

    logger.info(
        "slack_app_channel_approval_prompt_requested",
        integration_id=integration.id,
        slack_workspace_id=integration.integration_id,
        slack_channel_id=channel,
        slack_user_id=slack_user_id,
    )

    try:
        slack.client.chat_postEphemeral(
            channel=channel,
            user=slack_user_id,
            text="The PostHog Slack app needs approval before answering in this externally-shared channel.",
            blocks=blocks,
        )
    except Exception:
        logger.warning(
            "slack_app_channel_approval_prompt_failed",
            integration_id=integration.id,
            slack_workspace_id=integration.integration_id,
            slack_channel_id=channel,
            exc_info=True,
        )


def _report_slack_mention_received(
    event: dict,
    integration: Integration,
    slack_team_id: str,
    *,
    posthog_user: User | None = None,
) -> None:
    """Capture a product-analytics event each time the @PostHog bot is mentioned.

    A Slack thread is treated as the session: ``thread_ts`` identifies it, and a mention whose
    ``thread_ts`` is absent or equal to its own ``ts`` is the session's first message. The acting
    Slack user is resolved to a PostHog ``User`` so the event is attributed to a real person where
    one exists; otherwise it falls back to a stable Slack-derived distinct id.

    When the caller has already resolved the PostHog user at routing time it passes ``posthog_user``
    so we skip the redundant Slack ``users.info`` + ``OrganizationMembership`` roundtrip.
    """
    try:
        channel = event.get("channel") if isinstance(event.get("channel"), str) else None
        message_ts = event.get("ts") if isinstance(event.get("ts"), str) else None
        raw_thread_ts = event.get("thread_ts") if isinstance(event.get("thread_ts"), str) else None
        thread_ts = raw_thread_ts or message_ts
        is_first_message_in_session = raw_thread_ts is None or raw_thread_ts == message_ts

        slack_user_id = event.get("user") if isinstance(event.get("user"), str) and event.get("user") else None
        if posthog_user is None and slack_user_id:
            posthog_user = resolve_posthog_user_from_event(
                slack_user_id=slack_user_id,
                probe_integration=integration,
                candidate_integrations=[integration],
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
            "slack_app_mention_analytics_failed",
            slack_team_id=slack_team_id,
            integration_id=integration.id,
            exc_info=True,
        )


def _start_mention_workflow(
    event: dict,
    integration: Integration,
    slack_team_id: str,
    event_id: str | None,
    *,
    posthog_user: User | None,
    untagged_followup: bool = False,
    is_ext_shared_channel: bool = False,
) -> str:
    """Start the mention workflow for either an explicit ``app_mention`` or an
    untagged thread reply.

    ``untagged_followup`` toggles two mention-only side effects: the
    ``slack_mention_received`` analytics fire (which would otherwise pollute
    the mention funnel with non-mentions) and the pending-picker resolution
    (which is meaningful only when the user actually typed ``@PostHog``). It
    is also threaded into the workflow inputs so the workflow runs the
    classifier activity at the top of its body and short-circuits if the
    mapping is gone by the time the followup activity runs.

    ``posthog_user`` is optional only to keep the door open for the legacy
    in-workflow resolution path; in practice both event types resolve the
    user at routing time and pass it in.
    """
    if not untagged_followup:
        assert posthog_user is not None, "app_mention path must always resolve a user before dispatch"
        _report_slack_mention_received(event, integration, slack_team_id, posthog_user=posthog_user)
        if _resolve_pending_repo_picker_from_followup(event, integration):
            return ROUTE_HANDLED_LOCALLY
    workflow_inputs = PostHogCodeSlackMentionWorkflowInputs(
        event=event,
        integration_id=integration.id,
        slack_team_id=slack_team_id,
        slack_event_id=event_id,
        user_id=posthog_user.id if posthog_user else None,
        untagged_followup=untagged_followup,
        is_ext_shared_channel=is_ext_shared_channel,
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
        logger.warning("slack_app_event_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    retry_num = request.headers.get("X-Slack-Retry-Num")
    if retry_num:
        logger.info("slack_app_event_retry", retry_num=retry_num)
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
            # ``is_ext_shared_channel`` lives on the event envelope (Slack adds it for
            # any event delivered from a Slack Connect channel). Reading it here avoids
            # a per-mention ``conversations.info`` round-trip.
            is_ext_shared = bool(data.get("is_ext_shared_channel", False))
            result = route_posthog_code_event_to_relevant_region(
                request,
                event,
                slack_team_id,
                event_id=event_id,
                is_ext_shared_channel=is_ext_shared,
            )
            logger.info(
                "slack_app_event_dispatch_result",
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

    for action in payload.get("actions", []):
        if action.get("action_id") in {SLACK_PERMISSION_ACTION_APPROVE, SLACK_PERMISSION_ACTION_DENY}:
            action_value = action.get("value")
            if isinstance(action_value, str) and action_value:
                return action_value

    # fallback: message metadata
    return payload.get("message", {}).get("metadata", {}).get("event_payload", {}).get("context_token", "")


_AI_PREFERENCES_ACTION_IDS = frozenset(
    {
        ACTION_EDIT_PERSONAL,
        ACTION_EDIT_WORKSPACE,
        ACTION_RESET_PERSONAL,
        ACTION_RESET_PROJECT_PERSONAL,
        ACTION_SET_PROJECT_PERSONAL,
        ACTION_SET_PROJECT_WORKSPACE,
        ACTION_TASKS_FILTER_REPO,
        ACTION_TASKS_FILTER_STATUS,
        ACTION_TASKS_PAGE_NEXT,
        ACTION_TASKS_PAGE_PREV,
        ACTION_TASKS_REFRESH,
        ACTION_UNLINK_ACCOUNT,
        MODAL_ACTION_RUNTIME_ADAPTER,
        MODAL_ACTION_MODEL,
    }
)
_AI_PREFERENCES_CALLBACK_IDS = frozenset({EDIT_MODAL_PERSONAL_CALLBACK_ID, EDIT_MODAL_WORKSPACE_CALLBACK_ID})


def _is_ai_preferences_interactivity(payload: dict, payload_type: str) -> bool:
    """Return True if this payload is a Slack App Home AI-settings interaction.

    AI-settings buttons (Edit/Reset on the Home tab, runtime/model dispatch
    re-renders inside the modal) and modal submissions carry no per-row hint —
    the picker is workspace-scoped, not tied to a specific task or repo. The
    cross-region router uses this to claim locality based on the workspace
    integration alone rather than dropping the click.
    """
    if payload_type == "view_submission":
        return payload.get("view", {}).get("callback_id", "") in _AI_PREFERENCES_CALLBACK_IDS
    if payload_type == "block_actions":
        for action in payload.get("actions", []) or ():
            if action.get("action_id", "") in _AI_PREFERENCES_ACTION_IDS:
                return True
    return False


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
        logger.info("slack_app_repo_picker_options_missing_slack_team")
        return JsonResponse({"options": []})
    if not context_token:
        logger.info("slack_app_repo_picker_options_missing_token")
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
                    "slack_app_repo_picker_options_fallback_team",
                    context_token=context_token,
                    team_id=team_id,
                    integration_id=hinted_integration_id,
                )

    if not ctx and not hinted_integration_id:
        logger.info("slack_app_repo_picker_options_no_context", context_token=context_token)
        return JsonResponse({"options": []})

    requesting_user = payload.get("user", {}).get("id", "")
    expected_user = ctx["mentioning_slack_user_id"] if ctx else hinted_user_id
    if expected_user and requesting_user != expected_user:
        logger.info(
            "slack_app_repo_picker_options_user_mismatch",
            context_token=context_token,
            requesting_user=requesting_user,
            expected_user=expected_user,
        )
        return JsonResponse({"options": []})

    if not expected_user:
        logger.info("slack_app_repo_picker_options_missing_expected_user", context_token=context_token)

    try:
        integration_id: int | None = ctx["integration_id"] if ctx else hinted_integration_id
        if not integration_id:
            raise Integration.DoesNotExist
        # nosemgrep: idor-lookup-without-team — Slack webhook: no team context; scoped by PK + kind + Slack team ID
        integration = Integration.objects.get(
            id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
        )
    except Integration.DoesNotExist:
        logger.info("slack_app_repo_picker_options_no_integration", context_token=context_token)
        return JsonResponse({"options": []})

    mentioning_user_id = ctx.get("mentioning_user_id") if ctx else None
    if not isinstance(mentioning_user_id, int):
        # Without a known PostHog user we can't scope the options to a personal install;
        # return empty rather than falling back to the team install — the user can re-mention.
        logger.info("slack_app_repo_picker_options_missing_user_id", context_token=context_token)
        return JsonResponse({"options": []})

    try:
        all_repos = _get_full_repo_names(integration, user_id=mentioning_user_id)
    except Exception:
        logger.exception("twig_repo_picker_options_repo_fetch_error", integration_id=integration.id)
        return JsonResponse({"options": []})

    if not all_repos:
        logger.info(
            "slack_app_repo_picker_options_no_repos", context_token=context_token, integration_id=integration.id
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
                "slack_app_repo_submit_expired_feedback_missing_context",
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
                "slack_app_repo_submit_expired_feedback_failed",
                integration_id=integration_id,
                channel=channel,
                thread_ts=thread_ts,
            )

    if not selected_repo:
        return HttpResponse(status=200)

    if not workflow_id:
        logger.info("slack_app_repo_submit_missing_workflow_id")
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
        logger.warning("slack_app_repo_submit_signal_failed", workflow_id=workflow_id, error=str(e))
        post_selection_expired()
        return HttpResponse(status=200)


def _replace_repo_picker_with_selection(payload: dict, context: dict | None, selected_repo: str) -> None:
    integration_id = context.get("integration_id") if context else None
    slack_team_id = payload.get("team", {}).get("id")
    channel = context.get("channel") if context else payload.get("channel", {}).get("id")
    message_ts = payload.get("message", {}).get("ts")

    if not integration_id or not slack_team_id or not channel or not message_ts:
        logger.info(
            "slack_app_repo_submit_missing_picker_update_context",
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
        logger.info("slack_app_repo_none_missing_workflow_id")
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
        logger.warning("slack_app_repo_none_signal_failed", workflow_id=workflow_id, error=str(e))
        return HttpResponse(status=200)


def _delete_ephemeral_via_response_url(response_url: str) -> None:
    """Remove the original ephemeral prompt via the interactivity ``response_url`` once its public
    threaded outcome has been posted."""
    inbox_interactivity.post_response_url(response_url, {"delete_original": True})


def _post_channel_approval_outcome(
    integration: Integration,
    channel_id: str,
    thread_ts: str | None,
    text: str,
) -> None:
    """Post a public threaded reply documenting a click outcome.

    The prompt itself is ephemeral, so this is the only channel-visible
    record of what happened. ``thread_ts`` ties the message to the
    original mention so the audit trail sits next to the trigger.
    """
    if not thread_ts:
        return
    try:
        SlackIntegration(integration).client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=text,
        )
    except Exception:
        logger.warning(
            "slack_app_channel_approval_outcome_post_failed",
            integration_id=integration.id,
            channel=channel_id,
            exc_info=True,
        )


def _resolve_channel_approval_context(
    payload: dict,
) -> tuple[Integration, dict, str, str] | None:
    """Decode the click context and load the prompt's integration in one place.

    Returns ``(integration, context, channel_id, clicker_slack_user_id)`` on
    success, or ``None`` after silently cleaning up the ephemeral. Used by
    both approve and deny so they share the same context + integration
    resolution path.
    """
    response_url = payload.get("response_url", "")
    context_token = _extract_context_token(payload)
    context = _decode_picker_context(context_token) if context_token else None
    if not context or context.get("kind") != CHANNEL_APPROVAL_CONTEXT_KIND:
        _delete_ephemeral_via_response_url(response_url)
        return None

    integration_id = context.get("integration_id")
    channel_id = context.get("slack_channel_id")
    slack_team_id = payload.get("team", {}).get("id", "")
    clicker_slack_user_id = payload.get("user", {}).get("id", "")
    if not integration_id or not channel_id or not clicker_slack_user_id or not slack_team_id:
        _delete_ephemeral_via_response_url(response_url)
        return None

    integration = (
        Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        )
        .select_related("team__organization")
        .first()
    )
    if integration is None:
        _delete_ephemeral_via_response_url(response_url)
        return None

    return integration, context, channel_id, clicker_slack_user_id


def _is_org_member(integration: Integration, clicker_slack_user_id: str) -> User | None:
    """Resolve the clicker to a PostHog ``User`` belonging to the integration's
    organization, or ``None`` if no such membership exists.
    """
    return resolve_posthog_user_from_event(
        slack_user_id=clicker_slack_user_id,
        probe_integration=integration,
        candidate_integrations=[integration],
    )


def _org_label(integration: Integration) -> str:
    try:
        org_name = integration.team.organization.name
    except Exception:
        org_name = ""
    return f"*{org_name}*" if org_name else "this PostHog organization"


def _reject_non_member_click(
    integration: Integration,
    channel_id: str,
    thread_ts: str | None,
    response_url: str,
) -> None:
    """Post the public "only members can manage" rejection and clear the ephemeral.

    Shared between approve and deny so the rejection wording, the public
    placement, and the ephemeral cleanup all stay in one place.
    """
    _post_channel_approval_outcome(
        integration,
        channel_id,
        thread_ts,
        f":warning: Only members of {_org_label(integration)} can manage the PostHog Slack app in this channel.",
    )
    _delete_ephemeral_via_response_url(response_url)


def _handle_channel_approval_submit(payload: dict) -> HttpResponse:
    """Approve the bot for this Slack channel after verifying the clicker is a
    member of the integration's PostHog organization.

    The prompt is ephemeral to the mentioner; every outcome (approve, deny,
    non-member rejection) is posted as a public threaded reply so the whole
    channel sees the result.
    """
    resolved = _resolve_channel_approval_context(payload)
    if resolved is None:
        return HttpResponse(status=200)
    integration, context, channel_id, clicker_slack_user_id = resolved
    response_url = payload.get("response_url", "")
    thread_ts = context.get("thread_ts") if isinstance(context.get("thread_ts"), str) else None

    posthog_user = _is_org_member(integration, clicker_slack_user_id)
    if posthog_user is None:
        _reject_non_member_click(integration, channel_id, thread_ts, response_url)
        return HttpResponse(status=200)

    workspace_id = context.get("slack_workspace_id") or integration.integration_id
    SlackChannel.objects.update_or_create(
        slack_workspace_id=workspace_id,
        slack_channel_id=channel_id,
        defaults={
            "approved_at": timezone.now(),
            "approved_by": posthog_user,
        },
    )
    context_token = _extract_context_token(payload)
    if context_token:
        cache.delete(_picker_context_cache_key(context_token))

    _post_channel_approval_outcome(
        integration,
        channel_id,
        thread_ts,
        f"✅ <@{clicker_slack_user_id}> enabled the PostHog Slack app in this channel.",
    )
    _delete_ephemeral_via_response_url(response_url)
    return HttpResponse(status=200)


def _handle_channel_approval_deny(payload: dict) -> HttpResponse:
    """Dismiss the approval prompt without recording any state.

    Same membership gate as approve, since only the mentioner sees the
    ephemeral and a non-member mentioner's dismissal would otherwise just
    silently consume the prompt.
    """
    resolved = _resolve_channel_approval_context(payload)
    if resolved is None:
        return HttpResponse(status=200)
    integration, context, channel_id, clicker_slack_user_id = resolved
    response_url = payload.get("response_url", "")
    thread_ts = context.get("thread_ts") if isinstance(context.get("thread_ts"), str) else None

    posthog_user = _is_org_member(integration, clicker_slack_user_id)
    if posthog_user is None:
        _reject_non_member_click(integration, channel_id, thread_ts, response_url)
        return HttpResponse(status=200)

    context_token = _extract_context_token(payload)
    if context_token:
        cache.delete(_picker_context_cache_key(context_token))

    _post_channel_approval_outcome(
        integration,
        channel_id,
        thread_ts,
        f"✋ <@{clicker_slack_user_id}> dismissed the PostHog Slack app for this channel. Mention me again to retry.",
    )
    _delete_ephemeral_via_response_url(response_url)
    return HttpResponse(status=200)


def _permission_options_by_id(context: dict[str, Any]) -> dict[str, dict[str, str]]:
    options = context.get("options")
    if not isinstance(options, list):
        return {}

    by_id: dict[str, dict[str, str]] = {}
    for option in options:
        if not isinstance(option, dict):
            continue
        option_id = option.get("optionId")
        if not isinstance(option_id, str) or not option_id:
            continue
        kind = option.get("kind")
        label = option.get("label")
        by_id[option_id] = {
            "kind": kind if isinstance(kind, str) else "",
            "label": label if isinstance(label, str) else option_id,
        }
    return by_id


def _default_permission_option_id(context: dict[str, Any], options_by_id: dict[str, dict[str, str]]) -> str:
    default_option_id = context.get("default_option_id")
    if (
        isinstance(default_option_id, str)
        and default_option_id in options_by_id
        and not options_by_id[default_option_id]["kind"].startswith("reject")
    ):
        return default_option_id

    for option_id, option in options_by_id.items():
        if not option["kind"].startswith("reject"):
            return option_id

    return next(iter(options_by_id))


def _build_permission_denial_followup_message(context: dict[str, Any], denied_option_label: str) -> str:
    tool_label = context.get("tool_label")
    tool_detail = context.get("tool_detail")

    subject = tool_label if isinstance(tool_label, str) and tool_label.strip() else "the requested action"
    message = (
        f"The Slack user denied your approval request for {subject!r} "
        f"using the option {denied_option_label!r}.\n\n"
        "Treat this denial as a constraint, not as a reason to stop working. "
        "Do not retry the same denied action unchanged. Try a different safe approach that avoids the denied "
        "permission. If the denied action is truly required to complete the task, ask the user why they denied it "
        "or what constraint they want you to follow, then wait for their answer."
    )
    if isinstance(tool_detail, str) and tool_detail.strip():
        message = f"{message}\n\nDenied action detail:\n{tool_detail.strip()}"
    return message


def _post_permission_ephemeral_feedback(payload: dict, text: str) -> None:
    response_url = payload.get("response_url", "")
    if not response_url:
        return
    try:
        requests.post(
            response_url, json={"response_type": "ephemeral", "replace_original": False, "text": text}, timeout=3
        )
    except Exception:
        logger.warning("slack_app_permission_feedback_failed", exc_info=True)


def _resolve_permission_interaction(payload: dict) -> tuple[str, dict[str, Any], Integration, str] | None:
    context_token = _extract_context_token(payload)
    context = _decode_picker_context(context_token) if context_token else None
    if not context or context.get("kind") != SLACK_PERMISSION_CONTEXT_KIND:
        return None

    clicker_slack_user_id = payload.get("user", {}).get("id", "")
    expected_slack_user_id = context.get("expected_slack_user_id")
    if not isinstance(expected_slack_user_id, str) or clicker_slack_user_id != expected_slack_user_id:
        _post_permission_ephemeral_feedback(
            payload,
            "Only the person this approval was sent to can respond to it.",
        )
        return None

    integration_id = context.get("integration_id")
    slack_team_id = payload.get("team", {}).get("id", "")
    if not integration_id or not slack_team_id:
        return None

    integration = (
        Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        )
        .select_related("team")
        .first()
    )
    if integration is None:
        return None

    return context_token, context, integration, clicker_slack_user_id


def _replace_permission_prompt(payload: dict, text: str) -> None:
    response_url = payload.get("response_url", "")
    if not response_url:
        return
    try:
        requests.post(
            response_url,
            json={
                "replace_original": True,
                "text": text,
                "blocks": [
                    {
                        "type": "card",
                        "slack_icon": {"type": "icon", "name": "rocket"},
                        "title": {
                            "type": "mrkdwn",
                            "text": "Approval recorded",
                            "verbatim": False,
                        },
                        "subtitle": {
                            "type": "mrkdwn",
                            "text": "No further action is needed.",
                            "verbatim": False,
                        },
                        "body": {"type": "mrkdwn", "text": text, "verbatim": False},
                    }
                ],
            },
            timeout=3,
        )
    except Exception:
        logger.warning("slack_app_permission_replace_failed", exc_info=True)


def _selected_permission_mode(payload: dict) -> str | None:
    action = next(
        (a for a in payload.get("actions", []) if a.get("action_id") == SLACK_PERMISSION_ACTION_SELECT),
        None,
    )
    if not action:
        return None

    selected_option = action.get("selected_option")
    if not isinstance(selected_option, dict):
        return None

    value = selected_option.get("value")
    return value if isinstance(value, str) else None


def _sync_permission_config_to_task_run(context: dict[str, Any], integration: Integration, selected_tier: str) -> None:
    run_id = context.get("run_id")
    task_id = context.get("task_id")
    if not isinstance(run_id, str) or not isinstance(task_id, str):
        return

    try:
        task_run = TaskRun.objects.only("id", "status").get(
            id=run_id,
            task_id=task_id,
            team_id=integration.team_id,
        )
    except (TaskRun.DoesNotExist, ValidationError, ValueError):
        return

    if task_run.is_terminal:
        return

    TaskRun.update_state_atomic(task_run.id, updates={"slack_autonomy_tier": selected_tier})


def _handle_permission_config_select(payload: dict) -> HttpResponse:
    resolved = _resolve_permission_interaction(payload)
    if resolved is None:
        return HttpResponse(status=200)

    _context_token, context, integration, clicker_slack_user_id = resolved
    selected_mode = _selected_permission_mode(payload)

    from products.slack_app.backend.models import SlackPermissionMode, SlackSettings

    if selected_mode not in SlackPermissionMode.values:
        return HttpResponse(status=200)

    slack_workspace_id = context.get("slack_workspace_id") or integration.integration_id
    if not isinstance(slack_workspace_id, str) or not slack_workspace_id:
        return HttpResponse(status=200)

    SlackSettings.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_user_id=clicker_slack_user_id,
        defaults={
            "default_integration": integration,
            "permission_mode": selected_mode,
        },
    )
    _sync_permission_config_to_task_run(context, integration, selected_tier)

    selected_label = SlackPermissionMode(selected_mode).label
    _post_permission_ephemeral_feedback(payload, f"Permission mode saved: `{selected_label}`.")
    logger.info(
        "slack_app_permission_mode_saved",
        integration_id=integration.id,
        slack_workspace_id=slack_workspace_id,
        slack_user_id=clicker_slack_user_id,
        permission_mode=selected_mode,
    )
    return HttpResponse(status=200)


def _handle_permission_submit(payload: dict) -> HttpResponse:
    action = next(
        (
            a
            for a in payload.get("actions", [])
            if a.get("action_id") in {SLACK_PERMISSION_ACTION_APPROVE, SLACK_PERMISSION_ACTION_DENY}
        ),
        None,
    )
    if action is None:
        return HttpResponse(status=200)

    resolved = _resolve_permission_interaction(payload)
    if resolved is None:
        return HttpResponse(status=200)
    context_token, context, integration, clicker_slack_user_id = resolved

    options_by_id = _permission_options_by_id(context)
    if not options_by_id:
        return HttpResponse(status=200)

    request_id = context.get("request_id")
    run_id = context.get("run_id")
    task_id = context.get("task_id")
    if not isinstance(request_id, str) or not isinstance(run_id, str) or not isinstance(task_id, str):
        return HttpResponse(status=200)

    action_id = action.get("action_id")
    if action_id == SLACK_PERMISSION_ACTION_DENY:
        option_id = context.get("reject_option_id")
        action_label = "Denied"
    else:
        option_id = _default_permission_option_id(context, options_by_id)
        action_label = "Approved"

    if not isinstance(option_id, str) or option_id not in options_by_id:
        return HttpResponse(status=200)

    try:
        task_run = TaskRun.objects.select_related("task", "task__created_by").get(
            id=run_id,
            task_id=task_id,
            team_id=integration.team_id,
        )
    except TaskRun.DoesNotExist:
        return HttpResponse(status=200)

    if task_run.is_terminal:
        _replace_permission_prompt(payload, f"This run is already `{task_run.status}`. There is nothing to approve.")
        cache.delete(_picker_context_cache_key(context_token))
        return HttpResponse(status=200)

    channel = context.get("channel")
    thread_ts = context.get("thread_ts")
    if not isinstance(channel, str) or not isinstance(thread_ts, str):
        return HttpResponse(status=200)

    actor_context = resolve_slack_user(
        SlackIntegration(integration),
        integration,
        clicker_slack_user_id,
        channel,
        thread_ts,
        post_feedback=False,
    )
    if actor_context is None:
        _post_permission_ephemeral_feedback(
            payload,
            "I couldn't resolve your PostHog account for this approval. Please try again from the Task UI.",
        )
        return HttpResponse(status=200)

    option_label = options_by_id[option_id]["label"]
    denial_message = None
    if action_id == SLACK_PERMISSION_ACTION_DENY:
        denial_message = _build_permission_denial_followup_message(context, option_label)

    try:
        signal_task_permission_response(
            task_run.workflow_id,
            request_id=request_id,
            option_id=option_id,
            actor_user_id=actor_context.user.id,
            actor_slack_user_id=clicker_slack_user_id,
            is_denial=action_id == SLACK_PERMISSION_ACTION_DENY,
            denial_message=denial_message,
            broker_reason="slack_human_response",
        )
    except Exception:
        logger.warning(
            "slack_app_permission_response_signal_failed",
            run_id=run_id,
            request_id=request_id,
            option_id=option_id,
            actor_user_id=actor_context.user.id,
            exc_info=True,
        )
        _post_permission_ephemeral_feedback(
            payload,
            "I couldn't queue that response for the agent. Please try again from the Task UI.",
        )
        return HttpResponse(status=200)

    cache.delete(_picker_context_cache_key(context_token))
    if action_id == SLACK_PERMISSION_ACTION_DENY:
        _replace_permission_prompt(
            payload,
            f"{action_label} `{option_label}` for the agent. I told it to find another path or ask for context.",
        )
    else:
        _replace_permission_prompt(payload, f"{action_label} `{option_label}` for the agent.")
    logger.info(
        "slack_app_permission_response_signaled",
        run_id=run_id,
        request_id=request_id,
        option_id=option_id,
        action=action.get("action_id"),
        actor_user_id=actor_context.user.id,
    )
    return HttpResponse(status=200)


# Wire contract with products/signals/backend/slack_inbox_notifications.py (SIGNALS_DISMISS_REPORT_ACTION_ID).
SIGNALS_DISMISS_REPORT_ACTION_ID = "signals_dismiss_report"


def _dismiss_action_value(payload: dict) -> dict | None:
    action = next(
        (a for a in payload.get("actions", []) if a.get("action_id") == SIGNALS_DISMISS_REPORT_ACTION_ID), None
    )
    if not action:
        return None
    try:
        value = json.loads(action.get("value", ""))
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _extract_dismiss_hints(payload: dict) -> int | None:
    """Integration id carried by a signals 'Dismiss' button, used for region-ownership routing."""
    value = _dismiss_action_value(payload)
    if not value:
        return None
    integration_id = value.get("integration_id")
    return integration_id if isinstance(integration_id, int) else None


def _handle_signals_dismiss_report(payload: dict) -> HttpResponse:
    """Suppress a signals inbox report when a reviewer clicks 'Dismiss' in Slack."""
    from products.signals.backend.facade.api import (  # noqa: PLC0415 — cross-product action kept off the slack import path
        dismiss_report_from_slack,
    )

    value = _dismiss_action_value(payload)
    slack_team_id = payload.get("team", {}).get("id")
    if not value or not slack_team_id:
        return HttpResponse(status=200)

    integration_id = value.get("integration_id")
    report_id = value.get("report_id")
    report_team_id = value.get("team_id")
    if not (isinstance(integration_id, int) and report_id and isinstance(report_team_id, int)):
        return HttpResponse(status=200)

    try:
        # Slack webhook: no team context; scoped by PK + kind + workspace ID. The team match below
        # ensures the report belongs to the workspace's integration before we touch it.
        # nosemgrep: idor-lookup-without-team, idor-taint-user-input-to-model-get
        integration = Integration.objects.get(
            id=integration_id, kind=SLACK_INTEGRATION_KIND, integration_id=slack_team_id
        )
    except Integration.DoesNotExist:
        logger.info("signals_dismiss_report_no_integration", integration_id=integration_id)
        return HttpResponse(status=200)

    if integration.team_id != report_team_id:
        logger.warning(
            "signals_dismiss_report_team_mismatch",
            integration_team_id=integration.team_id,
            report_team_id=report_team_id,
        )
        return HttpResponse(status=200)

    slack_user_id = payload.get("user", {}).get("id", "")
    # Only PostHog org members may dismiss — a non-member in a shared channel must not suppress reports.
    org_member = _is_org_member(integration, slack_user_id)
    if org_member is None:
        logger.warning(
            "signals_dismiss_report_not_org_member",
            integration_id=integration.id,
            slack_user_id=slack_user_id,
        )
        return HttpResponse(status=200)

    suppressed = dismiss_report_from_slack(
        report_team_id, str(report_id), slack_user_id=slack_user_id, user_id=org_member.id
    )

    _post_signals_dismiss_feedback(payload, dismissed=suppressed, slack_user_id=slack_user_id)
    return HttpResponse(status=200)


def _post_signals_dismiss_feedback(payload: dict, *, dismissed: bool, slack_user_id: str) -> None:
    """Best-effort: replace the original message so it reads as dismissed."""
    response_url = payload.get("response_url")
    if not response_url:
        return

    if dismissed:
        actor = f"<@{slack_user_id}>" if slack_user_id else "a reviewer"
        text = f"✅ Dismissed by {actor}"
    else:
        text = "This report could not be dismissed — it may already be resolved or removed."

    original_message = payload.get("message", {})
    kept_blocks = [b for b in original_message.get("blocks", []) if b.get("type") != "actions"]
    kept_blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": text}]})

    try:
        requests.post(
            response_url,
            json={"replace_original": True, "text": text, "blocks": kept_blocks},
            timeout=5,
        )
    except requests.RequestException as e:
        logger.warning("signals_dismiss_report_feedback_failed", error=str(e))


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
                task_queue=settings.TASKS_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except Exception as e:
        logger.warning("slack_app_terminate_submit_start_failed", workflow_id=workflow_id, error=str(e))
    return HttpResponse(status=200)


@csrf_exempt
def posthog_code_interactivity_handler(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse(status=405)

    try:
        slack_config = SlackIntegration.slack_config()
        validate_slack_request(request, slack_config["SLACK_APP_SIGNING_SECRET"])
    except SlackIntegrationError as e:
        logger.warning("slack_app_interactivity_invalid_request", error=str(e))
        return HttpResponse("Invalid request", status=403)

    try:
        payload = json.loads(request.POST.get("payload", "{}"))
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    payload_type = payload.get("type")
    context_token = _extract_context_token(payload)
    logger.info(
        "slack_app_interactivity_received",
        payload_type=payload_type,
        context_token=context_token,
        host=request.get_host(),
    )

    # Check if we own this context locally
    context = _decode_picker_context(context_token) if context_token else None
    hinted_integration_id, hinted_user_id = _extract_picker_hints(payload)
    terminate_integration_id, terminate_user_id = _extract_terminate_hints(payload)
    dismiss_integration_id = _extract_dismiss_hints(payload)
    inbox_integration_id = inbox_interactivity.extract_inbox_hints(payload)
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
    elif slack_team_id and dismiss_integration_id:
        # Routing/region-ownership only — this just claims the workspace's integration locally.
        # Authorization (report-team match + org-member gate) is enforced in _handle_signals_dismiss_report.
        # Intended trust boundary for dismiss is org membership (any org member can dismiss the org's reports).
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=dismiss_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and inbox_integration_id:
        # Inbox onboarding buttons (create/join) are DMed to a user; any clicker may act, so this
        # is gated only on owning the integration locally.
        local = Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=inbox_integration_id,  # nosemgrep: idor-taint-user-input-to-model-get
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()
    elif slack_team_id and _is_ai_preferences_interactivity(payload, payload_type):
        # App Home AI-settings actions (Edit/Reset/Save) and the modal
        # re-render dispatched_actions carry no per-row hint — the button is
        # tied to the workspace, not a specific picker context. Claim locality
        # based on the workspace integration alone; if we own *any* Integration
        # for this Slack team, the click is ours to handle.
        local = Integration.objects.filter(
            kind=SLACK_INTEGRATION_KIND,
            integration_id=slack_team_id,
        ).exists()

    proxied = was_proxied(request)
    incoming_host = request.get_host()
    logger.info(
        "slack_app_interactivity_resolution",
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

    if not local and not proxied and cross_region_routing_enabled():
        # The payload's integration_id pinpoints exactly one row, so a lookup would tell us
        # nothing new — just forward to the other region. The loop header keeps us at one hop.
        # Skipped in single-region deployments (local dev, hosted dev, E2E, self-hosted) where
        # there is no other region to talk to.
        target = other_region_domain(incoming_host)
        upstream = _proxy_event_to_region(request, target)
        if upstream is not None:
            logger.info(
                "slack_app_interactivity_route",
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
            "slack_app_interactivity_route",
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
            "slack_app_interactivity_route",
            outcome="dropped",
            from_host=incoming_host,
            payload_type=payload_type,
            context_token=context_token,
        )
        if payload_type == "block_suggestion":
            return JsonResponse({"options": []})
        return HttpResponse(status=200)

    logger.info(
        "slack_app_interactivity_route",
        outcome="handled",
        from_host=incoming_host,
        payload_type=payload_type,
    )

    # Handled locally
    if payload_type == "block_suggestion":
        return _handle_repo_picker_options(payload)

    if payload_type == "view_submission":
        return _handle_app_home_view_submission(payload)

    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            action_id = action.get("action_id")
            if action_id == "posthog_code_repo_select":
                return _handle_repo_picker_submit(payload)
            if action_id == "posthog_code_repo_none":
                return _handle_no_repo_needed_submit(payload)
            if action_id == "posthog_code_terminate_task":
                return _handle_terminate_task_submit(payload)
            if action_id == CHANNEL_APPROVAL_ACTION_APPROVE:
                return _handle_channel_approval_submit(payload)
            if action_id == CHANNEL_APPROVAL_ACTION_DENY:
                return _handle_channel_approval_deny(payload)
            if action_id in {SLACK_PERMISSION_ACTION_APPROVE, SLACK_PERMISSION_ACTION_DENY}:
                return _handle_permission_submit(payload)
            if action_id == SLACK_PERMISSION_ACTION_SELECT:
                return _handle_permission_config_select(payload)
            if action_id == SIGNALS_DISMISS_REPORT_ACTION_ID:
                return _handle_signals_dismiss_report(payload)
            if action_id == onboarding.INBOX_CREATE_ACTION_ID:
                return inbox_interactivity.handle_inbox_create(payload)
            if action_id == onboarding.INBOX_JOIN_ACTION_ID:
                return inbox_interactivity.handle_inbox_join(payload)
            if action_id == onboarding.INBOX_SOURCES_CHECKBOXES_ACTION:
                return inbox_interactivity.handle_inbox_sources(payload)
            if action_id == onboarding.INBOX_AI_APPROVAL_ACTION_ID:
                return inbox_interactivity.handle_inbox_ai_approval(payload)
            if action_id in _AI_PREFERENCES_ACTION_IDS:
                return _handle_ai_preferences_block_action(payload, action)

    return HttpResponse(status=200)
