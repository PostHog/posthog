"""Public, unauthenticated endpoints for the user_interviews product.

Two surfaces live here, both keyed on a SharingConfiguration access token:

* ``start_call`` — called by the public interview page when the recipient clicks
  Start. Creates one Vapi web call server-side and returns only its join payload.
* ``vapi_webhook`` — the endpoint Vapi calls during and after a call. The throttle,
  verification and fan-out are the ingress vapi incarnation's, and the consumer it
  dispatches to lives in ``backend/webhook_consumers.py``.
"""

import json
import string
import hashlib
from typing import Any

from django.conf import settings

import requests
import structlog
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from posthog.constants import AvailableFeature
from posthog.egress.vapi import vapi_request
from posthog.ingress.vapi.provider import build_vapi_provider
from posthog.ingress.views import build_webhook_view
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team
from posthog.rate_limit import IPThrottle
from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

from ..facade.api import is_shared_interviewee_context, valid_distinct_id, valid_session_id
from ..logic import (
    RESPONDENT_KEY_MAX_CHARS,
    RESPONDENT_NAME_MAX_CHARS,
    clean_field,
    resolve_share,
    shared_interviewee_identifier,
)

logger = structlog.get_logger(__name__)


class _RateLimitMetricsMixin(SimpleRateThrottle):
    """Mixin that emits `rate_limit_exceeded_total` whenever the throttle it's mixed into rejects
    a request. Mixed *ahead* of the concrete throttle base (`IPThrottle` or `SimpleRateThrottle`)
    so `super().allow_request()` runs the real throttle logic, then this records the rejection.

    Kept product-local (not folded into the base `IPThrottle`) on purpose: tweaking the base would
    cascade into unrelated products that subclass it. One mixin serves both the IP-keyed and the
    token/respondent-keyed throttles here — `IPThrottle` is itself a `SimpleRateThrottle`, so the MRO
    resolves `super()` to whichever concrete base each throttle names.
    """

    def allow_request(self, request: Request, view: Any) -> bool:
        from posthog.rate_limit import RATE_LIMIT_EXCEEDED_COUNTER, get_route_from_path

        allowed = super().allow_request(request, view)
        if not allowed:
            route = get_route_from_path(getattr(request, "path", None))
            RATE_LIMIT_EXCEEDED_COUNTER.labels(team_id="", scope=self.scope, path=route, route=route).inc()
        return bool(allowed)


class InterviewStartCallIPThrottle(_RateLimitMetricsMixin, IPThrottle):
    """Per-IP cap on `start_call`. The endpoint is `AllowAny`, so without this any caller can spin DB
    queries on share-token lookups indefinitely. This cap's real job is bounding cross-token probing
    from one IP — per-token abuse is bounded by the token burst (120/min) + sustained (600/hour)
    buckets. It sits above the token burst on purpose: a shared link's headline use case is many
    people behind one corporate NAT / mobile CGNAT egress IP opening the same link, so a tight per-IP
    cap would 429 legitimate concurrent respondents who share an egress. 200/min clears the token
    burst (so the token bucket, not the IP, governs a single link's concurrency) while still stopping
    a single IP from probing many tokens."""

    scope = "user_interviews_start_call_ip"
    rate = "200/minute"


class InterviewStartCallTokenThrottle(_RateLimitMetricsMixin):
    """Sustained per-share-token ceiling on `start_call`. One token maps to either a single invited
    person (personalised link) or many self-serve respondents (a shared topic link), so this is a
    generous *sustained* bucket. On its own it would still let the whole hour's budget be spent in a
    burst — the per-IP cap doesn't bind a caller spread across many IPs, and the respondent throttle
    keys on a client-supplied respondent_key an attacker can rotate — so the companion
    `InterviewStartCallTokenBurstThrottle` adds a short-window per-token cap. Keying on the token (not
    IP) means an attacker rotating IPs still can't drain a guessed token faster than these two allow."""

    scope = "user_interviews_start_call_token"
    rate = "600/hour"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        resolver_match = getattr(request, "resolver_match", None)
        token = resolver_match.kwargs.get("access_token") if resolver_match else None
        if not token:
            return None
        return self.cache_format % {"scope": self.scope, "ident": token}


class InterviewStartCallTokenBurstThrottle(InterviewStartCallTokenThrottle):
    """Short-window per-share-token burst cap. Bounds the *instantaneous* rate a single token can be
    driven at — regardless of how many IPs or rotated respondent_keys a caller uses — so the sustained
    hourly budget can't be dumped in seconds. Recovers within the minute, and 120/min sits well above
    the realistic concurrent-Start volume for a shared link at this stage, so legitimate respondents
    aren't throttled. Reuses the parent's token-keyed cache key under its own scope."""

    scope = "user_interviews_start_call_token_burst"
    rate = "120/minute"


class InterviewStartCallRespondentThrottle(_RateLimitMetricsMixin):
    """Per-respondent burst on `start_call`, mirroring the support widget's `WidgetUserBurstThrottle`.
    Keys on the client-generated `respondent_key` (a random per-browser id a shared-link visitor
    sends) so one respondent hammering Start is bounded without penalising the next visitor sharing
    the same token. Falls back to IP when no key is present (personalised links, which don't send one)
    — so a personalised interviewee's effective per-IP ceiling is this 30/min (the lower of this and
    the 200/min IP throttle), which is still far above one person clicking Start."""

    scope = "user_interviews_start_call_respondent"
    rate = "30/minute"

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        respondent_key = request.data.get("respondent_key") if isinstance(request.data, dict) else None
        if respondent_key:
            ident = hashlib.sha256(str(respondent_key).encode()).hexdigest()
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _public_sharing_disabled_for_org(sharing_config: SharingConfiguration) -> bool:
    """Mirror of `SharingViewerPageViewSet.retrieve()`'s org-level kill switch."""
    organization = sharing_config.team.organization
    return (
        organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
        and not organization.allow_publicly_shared_resources
    )


_TOPIC_MAX_CHARS = 200

FIRST_MESSAGE_PROMPT_NAME = "user_interviews_vapi_first_message"

DEFAULT_FIRST_MESSAGE_TEMPLATE = (
    "Hey $user_name! Thanks for making time — I know you're busy. "
    "I'm here to learn how you actually use $topic_text in the wild. "
    "Mind if I ask a few questions? Should take about 5-10 minutes."
)

_FIRST_MESSAGE_MAX_CHARS = 1000


def _normalise_topic(topic_text: str) -> str:
    return " ".join(topic_text.split())[:_TOPIC_MAX_CHARS]


def _resolve_first_message_template(team: Team) -> str:
    try:
        cached = get_prompt_by_name_from_cache(team, FIRST_MESSAGE_PROMPT_NAME)
    except Exception as err:
        logger.warning(
            "user_interviews_first_message_prompt_lookup_failed",
            team_id=team.id,
            error=str(err),
        )
        return DEFAULT_FIRST_MESSAGE_TEMPLATE
    if cached is not None:
        template = cached.get("prompt")
        if isinstance(template, str) and template.strip():
            return template
    return DEFAULT_FIRST_MESSAGE_TEMPLATE


def _build_first_message(
    template: str,
    *,
    user_name: str,
    topic_text: str,
    team_id: int | None = None,
) -> str:
    name_part = user_name.strip() or "there"
    topic_part = _normalise_topic(topic_text) or "your experience"
    try:
        rendered = string.Template(template).substitute(user_name=name_part, topic_text=topic_part)
    except (KeyError, ValueError):
        logger.warning(
            "user_interviews_first_message_template_invalid",
            team_id=team_id,
            template_prefix=template[:60],
        )
        rendered = string.Template(DEFAULT_FIRST_MESSAGE_TEMPLATE).substitute(
            user_name=name_part, topic_text=topic_part
        )
    if len(rendered) > _FIRST_MESSAGE_MAX_CHARS:
        logger.warning(
            "user_interviews_first_message_too_long",
            team_id=team_id,
            rendered_chars=len(rendered),
            limit=_FIRST_MESSAGE_MAX_CHARS,
        )
        rendered = string.Template(DEFAULT_FIRST_MESSAGE_TEMPLATE).substitute(
            user_name=name_part, topic_text=topic_part
        )
    return rendered[:_FIRST_MESSAGE_MAX_CHARS]


VAPI_WEB_CALL_URL = "https://api.vapi.ai/call/web"


class VapiWebCallError(Exception):
    def __init__(self, message: str, status_code: int = status.HTTP_502_BAD_GATEWAY) -> None:
        super().__init__(message)
        self.status_code = status_code


def _create_vapi_web_call(assistant_overrides: dict[str, Any]) -> dict[str, Any]:
    try:
        response = vapi_request(
            "POST",
            VAPI_WEB_CALL_URL,
            api_token=settings.VAPI_PUBLIC_KEY,
            source="user_interviews",
            endpoint="/call/web",
            timeout=(3.05, 15),
            json={
                "assistantId": settings.VAPI_ASSISTANT_ID,
                "assistantOverrides": assistant_overrides,
                "roomDeleteOnUserLeaveEnabled": True,
            },
        )
    except requests.RequestException as error:
        raise VapiWebCallError("Could not connect to Vapi.") from error

    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        raise VapiWebCallError("Vapi is temporarily rate limited.", status.HTTP_429_TOO_MANY_REQUESTS)
    if not 200 <= response.status_code < 300:
        raise VapiWebCallError(f"Vapi rejected web call creation with status {response.status_code}.")

    try:
        payload = response.json()
    except ValueError as error:
        raise VapiWebCallError("Vapi returned an invalid web call response.") from error
    if not isinstance(payload, dict):
        raise VapiWebCallError("Vapi returned an invalid web call response.")

    transport = payload.get("transport")
    transport_url = transport.get("callUrl") if isinstance(transport, dict) else None
    web_call_url = payload.get("webCallUrl") or transport_url
    if not isinstance(web_call_url, str) or not web_call_url:
        raise VapiWebCallError("Vapi returned a web call without a join URL.")

    web_call: dict[str, Any] = {"webCallUrl": web_call_url}
    call_id = payload.get("id")
    if isinstance(call_id, str):
        web_call["id"] = call_id
    artifact_plan = payload.get("artifactPlan")
    if isinstance(artifact_plan, dict):
        web_call["artifactPlan"] = {"videoRecordingEnabled": bool(artifact_plan.get("videoRecordingEnabled", False))}
    return web_call


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes(
    [
        InterviewStartCallIPThrottle,
        InterviewStartCallRespondentThrottle,
        InterviewStartCallTokenBurstThrottle,
        InterviewStartCallTokenThrottle,
    ]
)
def start_call(request: Request, access_token: str) -> Response:
    """Create a Vapi web call and return its join payload for a public interview share.

    Handles both share types the token can resolve to:
    * a personalised (per-invitee) share — greets the named invitee, merges their per-person
      ``agent_context``;
    * a non-personalised (shared) topic share — every visitor is a new anonymous respondent who
      self-identifies with a name; ``distinct_id``/``session_id`` query params are carried through
      as best-effort person/session linkage, and a client ``respondent_key`` lets a refreshed call
      re-attach to the same respondent.

    The ``agent_context`` (which may include internal CRM notes about a personalised invitee) and
    reusable Vapi credentials stay server-side. The browser receives only a single call's join
    payload after the existing start-call throttles have accepted the request.
    """
    from .views import _merge_agent_context, _parse_identifier

    if not settings.VAPI_PUBLIC_KEY or not settings.VAPI_ASSISTANT_ID:
        logger.warning("user_interviews_start_call_misconfigured")
        return Response(
            {"error": "Vapi is not configured on this PostHog instance."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    body = request.data if isinstance(request.data, dict) else {}
    # Honeypot: a hidden field real users never fill, but naive bots do. Present on the shared-link
    # name form; reject silently-ish with a 400 so a bot can't spin up calls. Log it so a bot wave —
    # or a false positive dropping a real respondent — is visible rather than a silent black hole.
    if body.get("_hp"):
        logger.warning(
            "user_interviews_start_call_honeypot_tripped",
            access_token_suffix=access_token[-6:] if access_token else None,
        )
        return Response({"error": "invalid request"}, status=status.HTTP_400_BAD_REQUEST)

    sharing_config = resolve_share(access_token)
    if sharing_config is None or sharing_config.interviewee_context is None:
        logger.warning("user_interviews_start_call_unknown_access_token")
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)
    if _public_sharing_disabled_for_org(sharing_config):
        # Match the public viewer's behavior: return 404 so the kill switch is opaque to
        # link recipients (doesn't reveal whether the token is real, just disabled).
        logger.info(
            "user_interviews_start_call_sharing_disabled",
            team_id=sharing_config.team_id,
        )
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)

    ic = sharing_config.interviewee_context
    topic = ic.topic
    if is_shared_interviewee_context(ic.interviewee_identifier):
        respondent_name = clean_field(body.get("name"), RESPONDENT_NAME_MAX_CHARS)
        if not respondent_name:
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)
        respondent_key = clean_field(body.get("respondent_key"), RESPONDENT_KEY_MAX_CHARS)
        user_name = respondent_name or "there"
        agent_context = topic.agent_context or ""
        # The response is stored under a namespaced identifier that can never collide with a targeted
        # invitee's. The distinct_id from the URL is best-effort, UNTRUSTED linkage carried in its own
        # metadata field — never folded into the identifier, so it can't forge attribution or lock a
        # targeted person out.
        metadata: dict[str, str] = {
            "topic_id": str(topic.id),
            "interviewee_identifier": shared_interviewee_identifier(respondent_key),
            "sharing_access_token": access_token,
            "shared": "true",
            "respondent_name": respondent_name,
            "respondent_key": respondent_key,
            "distinct_id": valid_distinct_id(body.get("distinct_id")),
            # session_id isn't persisted in the DB — it rides on the lifecycle PostHog event (as
            # $session_id, which associates the interview with the session recording). Validated
            # here at the trust boundary; invalid values are dropped, not rejected.
            "session_id": valid_session_id(body.get("session_id")),
        }
    else:
        user_name, _ = _parse_identifier(ic.interviewee_identifier)
        agent_context = _merge_agent_context(topic.agent_context or "", ic.agent_context or "")
        metadata = {
            "topic_id": str(topic.id),
            "interviewee_identifier": ic.interviewee_identifier,
            "sharing_access_token": access_token,
        }

    first_message_template = _resolve_first_message_template(sharing_config.team)
    first_message = _build_first_message(
        first_message_template,
        user_name=user_name,
        topic_text=topic.topic or "",
        team_id=sharing_config.team_id,
    )

    assistant_overrides: dict[str, Any] = {
        "firstMessage": first_message,
        # Scope server messages to just the lifecycle hooks we act on. Default Vapi
        # config sends ~10 message types that we'd otherwise ignore.
        "serverMessages": ["status-update", "end-of-call-report"],
        "variableValues": {
            "userName": user_name,
            "topic": topic.topic or "",
            "agent_context": agent_context,
            "questions": json.dumps(topic.questions or []),
        },
        "metadata": metadata,
    }
    try:
        web_call = _create_vapi_web_call(assistant_overrides)
    except VapiWebCallError as error:
        logger.exception(
            "user_interviews_vapi_web_call_creation_failed",
            team_id=sharing_config.team_id,
            topic_id=str(topic.id),
            status_code=error.status_code,
        )
        return Response({"error": str(error)}, status=error.status_code)

    logger.info(
        "user_interviews_start_call_issued",
        team_id=sharing_config.team_id,
        topic_id=str(topic.id),
        shared=is_shared_interviewee_context(ic.interviewee_identifier),
        call_id=web_call.get("id"),
    )
    return Response({"web_call": web_call})


# Built once per process: the provider holds a secret getter, and reads the secret per request.
# The per-IP cap rides on the provider's `throttle_class`, so the throttle, the 429 and its
# `Retry-After` are the ingress lane's, the same as every other provider that caps.
vapi_webhook = build_webhook_view(build_vapi_provider())
