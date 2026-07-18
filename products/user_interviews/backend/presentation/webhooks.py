"""Public, unauthenticated endpoints for the user_interviews product.

Two surfaces live here, both keyed on a SharingConfiguration access token:

* ``start_call`` — called by the public interview page when the recipient clicks
  Start. Returns the Vapi credentials and the personalized assistant overrides
  (including merged ``agent_context``). Keeps that context off the initial HTML.
* ``vapi_webhook`` — called by Vapi at end-of-call. Persists a UserInterview row
  attributed to the topic creator. Signature-verified; idempotent on ``call.id``.
"""

import re
import hmac
import json
import string
import hashlib
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now

import structlog
import posthoganalytics
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.constants import AvailableFeature
from posthog.event_usage import groups
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team
from posthog.rate_limit import IPThrottle
from posthog.storage.llm_prompt_cache import get_prompt_by_name_from_cache

from ..facade.api import derive_auto_classifications, is_shared_interviewee_context, valid_distinct_id, valid_session_id
from ..models import UserInterview, UserInterviewClassification, UserInterviewTopic

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


class VapiWebhookIPThrottle(_RateLimitMetricsMixin, IPThrottle):
    """Per-IP cap on `vapi_webhook`. Vapi calls us a small handful of times per interview
    (status-update + end-of-call-report), but its egress is shared across all of our tenants,
    so the bucket has to be generous enough that a noisy concurrent interview hour doesn't
    bleed onto a normal one. 1200/min is well above legitimate aggregate volume while still
    stopping a persistent attacker from driving HMAC-verification CPU or structured-log
    volume from a single IP. Rejection emits `rate_limit_exceeded_total` via the parent
    mixin so we can alert if it ever trips."""

    scope = "user_interviews_vapi_webhook_ip"
    rate = "1200/minute"


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


# Vapi's HMAC-SHA256 hex digest is exactly 64 lowercase hex chars; reject other shapes
# pre-HMAC so casual probes can't drive log/CPU load.
_VAPI_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


_EMBEDDING_MODELS = [m.value for m in EmbeddingModelName]

# TODO: figure out a better story for transcripts that exceed our Kafka envelope
# than head-truncation. Options: (a) chunk + emit multiple documents per type, or
# (b) push large content to object storage and embed a reference. Truncation is a
# stop-gap so a 90-minute interview doesn't silently lose its embeddings entirely.
EMBEDDING_CONTENT_MAX_BYTES = 750_000


def _emit_interview_embeddings(interview: UserInterview, topic: UserInterviewTopic) -> None:
    """Emit transcript and summary as two separate embedding documents so each can be
    searched independently. Failures are logged but never propagated: Vapi retries are
    idempotent on call.id, so a re-delivery would skip creation and never re-emit —
    making a thrown exception here strictly worse than a degraded but acknowledged row."""
    metadata = {
        "topic_id": str(topic.id),
        "interviewee_identifier": interview.interviewee_identifier,
    }
    for document_type, content in (("transcript", interview.transcript), ("summary", interview.summary)):
        if not content or not content.strip():
            continue
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > EMBEDDING_CONTENT_MAX_BYTES:
            logger.warning(
                "user_interviews_embedding_content_truncated",
                team_id=interview.team_id,
                interview_id=str(interview.id),
                document_type=document_type,
                original_bytes=len(content_bytes),
                truncated_to_bytes=EMBEDDING_CONTENT_MAX_BYTES,
            )
            content = content_bytes[:EMBEDDING_CONTENT_MAX_BYTES].decode("utf-8", errors="ignore")
        try:
            emit_embedding_request(
                content=content,
                team_id=interview.team_id,
                product="user_interviews",
                document_type=document_type,
                rendering="plain",
                document_id=str(interview.id),
                models=_EMBEDDING_MODELS,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                "user_interviews_embedding_emit_failed",
                team_id=interview.team_id,
                interview_id=str(interview.id),
                document_type=document_type,
            )


def _resolve_share(access_token: str) -> SharingConfiguration | None:
    """Resolve a share token to its `SharingConfiguration`, mirroring the filters
    used by `SharingViewerPageViewSet.get_object()`:
    * `enabled=True`
    * not expired (`expires_at` null OR in the future) — rotated tokens past their
      5-minute grace period are excluded so this surface stays consistent with the
      public viewer.
    """
    try:
        return (
            SharingConfiguration.objects.select_related(
                "team",
                "team__organization",
                "interviewee_context",
                "interviewee_context__topic",
                "interviewee_context__topic__created_by",
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now()))
            .get(access_token=access_token, enabled=True)
        )
    except SharingConfiguration.DoesNotExist:
        return None


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


# Max lengths for the self-reported fields a shared-link respondent sends to start_call. These
# are echoed into Vapi metadata and persisted on the UserInterview, so cap them defensively.
_RESPONDENT_NAME_MAX_CHARS = 200
_RESPONDENT_KEY_MAX_CHARS = 64

# Every shared-link response is stored under an identifier carrying this prefix. It can NEVER equal a
# personalised interviewee's identifier (an email or distinct_id), so an anonymous respondent can
# neither be attributed to nor lock out a targeted invitee.
SHARED_RESPONDENT_IDENTIFIER_PREFIX = "shared:"


def _clean_field(value: Any, max_chars: int) -> str:
    return str(value).strip()[:max_chars] if value else ""


def _shared_interviewee_identifier(respondent_key: str) -> str:
    """Namespaced, non-authoritative identity for a shared-link respondent.

    Keyed on the stable per-browser ``respondent_key`` so a refreshed respondent keeps one identity;
    falls back to a random id when no key was supplied so rows stay distinct. Deliberately independent
    of any self-reported name or untrusted ``distinct_id`` — those never determine attribution."""
    return f"{SHARED_RESPONDENT_IDENTIFIER_PREFIX}{respondent_key or uuid4().hex}"


def _collapse_abandoned_partials(*, team: Team, topic: UserInterviewTopic, respondent_key: str, keep_pk: Any) -> None:
    """Delete the abandoned partial an accidental mid-call refresh leaves behind, when the same
    respondent (same ``respondent_key``) comes back and finishes — so the topic shows one response
    per respondent instead of a junk trail.

    Deletes only rows that STILL auto-derive as ``abandoned`` from their own transcript, rather than
    trusting the stored label. ``abandoned`` is user-mutable (writable via the update API and the MCP
    tool), so a real response a curator manually re-tagged ``abandoned`` would otherwise be
    permanently, unrecoverably deleted here. Re-deriving keeps this a cleanup of genuine AI-only
    partials and never touches a row that contains real interviewee content.
    """
    candidates = (
        UserInterview.objects.filter(
            team=team,
            topic=topic,
            respondent_key=respondent_key,
            classifications__contains=[UserInterviewClassification.ABANDONED],
        )
        .exclude(pk=keep_pk)
        .only("id", "transcript")
    )
    stale_pks = [
        c.pk for c in candidates if UserInterviewClassification.ABANDONED in derive_auto_classifications(c.transcript)
    ]
    if not stale_pks:
        return
    deleted_count, _ = UserInterview.objects.filter(pk__in=stale_pks).delete()
    logger.info(
        "user_interviews_collapsed_abandoned_partials",
        team_id=team.id,
        topic_id=str(topic.id),
        deleted_count=deleted_count,
    )


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
    """Return the Vapi credentials + assistant overrides for a public interview share.

    Handles both share types the token can resolve to:
    * a personalised (per-invitee) share — greets the named invitee, merges their per-person
      ``agent_context``;
    * a non-personalised (shared) topic share — every visitor is a new anonymous respondent who
      self-identifies with a name; ``distinct_id``/``session_id`` query params are carried through
      as best-effort person/session linkage, and a client ``respondent_key`` lets a refreshed call
      re-attach to the same respondent.

    The ``agent_context`` (which may include internal CRM notes about a personalised invitee) is
    intentionally NOT embedded in the public interview page's HTML — it's fetched from here only
    when the recipient clicks Start, keeping casual view-source inspection from leaking the prompt.

    Note: anyone with the share token can still get this payload — by design, since they also use it
    to actually start the call. The win is removing the leak from the initial HTML and giving us a
    single, auditable, rate-limitable surface.
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

    sharing_config = _resolve_share(access_token)
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
        respondent_name = _clean_field(body.get("name"), _RESPONDENT_NAME_MAX_CHARS)
        respondent_key = _clean_field(body.get("respondent_key"), _RESPONDENT_KEY_MAX_CHARS)
        user_name = respondent_name or "there"
        agent_context = topic.agent_context or ""
        # The response is stored under a namespaced identifier that can never collide with a targeted
        # invitee's. The distinct_id from the URL is best-effort, UNTRUSTED linkage carried in its own
        # metadata field — never folded into the identifier, so it can't forge attribution or lock a
        # targeted person out.
        metadata: dict[str, str] = {
            "topic_id": str(topic.id),
            "interviewee_identifier": _shared_interviewee_identifier(respondent_key),
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

    logger.info(
        "user_interviews_start_call_issued",
        team_id=sharing_config.team_id,
        topic_id=str(topic.id),
        shared=is_shared_interviewee_context(ic.interviewee_identifier),
    )

    return Response(
        {
            "public_key": settings.VAPI_PUBLIC_KEY,
            "assistant_id": settings.VAPI_ASSISTANT_ID,
            "assistant_overrides": {
                "firstMessage": first_message,
                # Scope server messages to just the lifecycle hooks we act on. Default Vapi
                # config sends ~10 message types (speech-update, conversation-update, etc.)
                # which we'd ignore anyway — and every ignored delivery still costs a
                # webhook round-trip and a signature verification.
                "serverMessages": ["status-update", "end-of-call-report"],
                "variableValues": {
                    "userName": user_name,
                    "topic": topic.topic or "",
                    "agent_context": agent_context,
                    # `json.dumps` so the Vapi assistant prompt receives standard JSON
                    # (`["q1", "q2"]`) rather than Python's repr (`['q1', 'q2']`).
                    "questions": json.dumps(topic.questions or []),
                },
                "metadata": metadata,
            },
        }
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([VapiWebhookIPThrottle])
def vapi_webhook(request: Request) -> Response:
    """Receive a Vapi ``end-of-call-report`` and persist it as a UserInterview.

    Fail-closed: if ``VAPI_WEBHOOK_SECRET`` is not configured we refuse to accept any
    request — treating an unconfigured deployment as inert rather than insecure.
    With the secret set, the request body is HMAC-SHA256 verified.

    Idempotent: Vapi retries on 5xx and transient errors, so we de-duplicate by
    ``call.id`` (stored in ``call_metadata.id``). A repeat delivery returns the
    existing interview's id instead of creating a second row.
    """
    if not settings.VAPI_WEBHOOK_SECRET:
        logger.warning("user_interviews_vapi_webhook_secret_missing")
        return Response(
            {"error": "Vapi webhook secret is not configured on this PostHog instance."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    provided = request.headers.get("X-Vapi-Signature")
    # Pre-HMAC shape gate: Vapi's HMAC-SHA256 hex digest is exactly 64 lowercase hex chars.
    # Anything else can't possibly be a valid signature, so reject before we compute the
    # HMAC over the body — saves CPU and stops casual probes from filling diagnostic logs.
    if not provided or not _VAPI_SIGNATURE_RE.match(provided):
        return Response({"error": "missing or malformed signature"}, status=status.HTTP_401_UNAUTHORIZED)
    expected = hmac.new(settings.VAPI_WEBHOOK_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
    logger.info(
        "user_interviews_vapi_webhook_received",
        header_keys=sorted(request.headers.keys()),
        has_provided_signature=bool(provided),
        body_bytes=len(request.body),
    )
    if not (provided and expected and hmac.compare_digest(provided, expected)):
        # TODO: REMOVE — temporary diagnostic dump of the raw body and the
        # provided signature so we can locally reproduce Vapi's HMAC and find
        # the byte-level mismatch that's causing 100% signature_failed. Safe
        # only because user_interviews is not yet shipped to real users.
        logger.warning(
            "user_interviews_vapi_webhook_signature_failed",
            has_provided_signature=bool(provided),
            expected_prefix=expected[:8] if expected else None,
            provided_prefix=provided[:8] if provided else None,
            provided_length=len(provided) if provided else 0,
            body_bytes=len(request.body),
            provided_signature=provided,
            raw_body=request.body.decode("utf-8", errors="replace"),
        )
        return Response({"error": "invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

    payload = request.data if isinstance(request.data, dict) else {}
    message: dict[str, Any] = payload.get("message", {})
    message_type = message.get("type")
    call: dict[str, Any] = message.get("call", {}) or {}
    # Vapi can surface our `assistant_overrides.metadata` (set in `start_call`) in two
    # places on the Call object: `call.metadata` for some message types, and nested under
    # `call.assistantOverrides.metadata` on others. Empirically end-of-call-report comes
    # through with the nested form, so try both.
    overrides_metadata: dict[str, Any] = (call.get("assistantOverrides") or {}).get("metadata") or {}
    top_metadata: dict[str, Any] = call.get("metadata") or {}
    access_token = (
        top_metadata.get("sharing_access_token")
        or top_metadata.get("access_token")
        or overrides_metadata.get("sharing_access_token")
        or overrides_metadata.get("access_token")
    )
    # Shared-link respondent fields (set in start_call's metadata, echoed back by Vapi). Merge with
    # top-level precedence, mirroring the access_token resolution above.
    merged_metadata: dict[str, Any] = {**overrides_metadata, **top_metadata}
    call_id = call.get("id")

    if message_type == "status-update":
        # Lifecycle ping. We only act on `in-progress` (call started) — the `ended` status
        # is followed by a separate `end-of-call-report` with the full transcript, so we
        # capture the ended event from that branch where we already have the interview row.
        call_status = message.get("status")
        if call_status == "in-progress" and access_token:
            sharing_config = _resolve_share(access_token)
            if sharing_config is not None and sharing_config.interviewee_context is not None:
                _capture_user_interview_event(
                    "user_interview_conversation_started",
                    sharing_config=sharing_config,
                    call_id=call_id,
                    session_id=valid_session_id(merged_metadata.get("session_id")),
                )
        logger.info(
            "user_interviews_vapi_webhook_status_update",
            call_status=call_status,
            call_id=call_id,
        )
        return Response({"status": "ok"})

    if message_type != "end-of-call-report":
        # Other event types (transcripts mid-call, speech-update, etc.) shouldn't reach us —
        # start_call's `serverMessages` override scopes Vapi to status-update + end-of-call-report.
        # Anything else here means the assistant config drifted; log it so we notice.
        logger.info(
            "user_interviews_vapi_webhook_ignored_message_type",
            message_type=message_type,
        )
        return Response({"status": "ignored"})

    if not access_token:
        logger.warning(
            "user_interviews_vapi_webhook_missing_access_token",
            call_id=call_id,
        )
        return Response(
            {"error": "missing sharing_access_token in call.metadata"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sharing_config = _resolve_share(access_token)
    if sharing_config is None:
        logger.warning(
            "user_interviews_vapi_webhook_unknown_access_token",
            call_id=call_id,
        )
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)

    interviewee_context = sharing_config.interviewee_context
    if interviewee_context is None:
        logger.warning(
            "user_interviews_vapi_webhook_wrong_share_type",
            team_id=sharing_config.team_id,
            call_id=call_id,
        )
        return Response(
            {"error": "access_token does not belong to a user interview share"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if call_id:
        existing = UserInterview.objects.filter(team=sharing_config.team, call_metadata__id=call_id).first()
        if existing is not None:
            logger.info(
                "user_interviews_vapi_webhook_duplicate",
                team_id=sharing_config.team_id,
                interview_id=str(existing.id),
                call_id=call_id,
            )
            return Response({"status": "duplicate", "interview_id": str(existing.id)}, status=status.HTTP_200_OK)

    recording_url = (message.get("recording") or {}).get("url", "") or message.get("recordingUrl", "") or ""
    transcript = message.get("transcript", "") or ""
    classifications = derive_auto_classifications(transcript)
    topic = interviewee_context.topic

    if is_shared_interviewee_context(interviewee_context.interviewee_identifier):
        respondent_name = _clean_field(merged_metadata.get("respondent_name"), _RESPONDENT_NAME_MAX_CHARS)
        respondent_key = _clean_field(merged_metadata.get("respondent_key"), _RESPONDENT_KEY_MAX_CHARS)
        # Recompute the identifier from respondent_key rather than trusting the echoed metadata, so it
        # is always a namespaced shared marker and can never be steered onto a targeted invitee.
        interviewee_identifier = _shared_interviewee_identifier(respondent_key)
        interviewee_emails = []
        # Best-effort, untrusted person linkage. Re-validated here (defense in depth) and stored in its
        # own column — never as the interviewee_identifier, so it can't forge attribution.
        distinct_id = valid_distinct_id(merged_metadata.get("distinct_id"))
        # session_id isn't persisted — it rides on the lifecycle event below. Re-validated here
        # (defense in depth) so only a well-formed UUIDv7 reaches the event.
        session_id = valid_session_id(merged_metadata.get("session_id"))
    else:
        interviewee_identifier = interviewee_context.interviewee_identifier
        interviewee_emails = [interviewee_identifier] if "@" in interviewee_identifier else []
        respondent_name = respondent_key = ""
        distinct_id = ""
        session_id = ""

    with transaction.atomic():
        interview = UserInterview.objects.create(
            team=sharing_config.team,
            topic=topic,
            interviewee_identifier=interviewee_identifier,
            interviewee_emails=interviewee_emails,
            respondent_name=respondent_name,
            respondent_key=respondent_key,
            distinct_id=distinct_id,
            transcript=transcript,
            summary=message.get("summary", "") or "",
            recording_url=recording_url,
            call_metadata=call,
            created_by=topic.created_by,
            classifications=classifications,
        )
        # Collapse the abandoned partial an accidental refresh leaves behind: when a shared-link
        # respondent comes back (same respondent_key) and finishes, drop their earlier abandoned
        # rows so the topic shows one response per respondent instead of a junk trail.
        if respondent_key and UserInterviewClassification.ABANDONED not in classifications:
            _collapse_abandoned_partials(
                team=sharing_config.team,
                topic=topic,
                respondent_key=respondent_key,
                keep_pk=interview.pk,
            )
        transaction.on_commit(lambda: _emit_interview_embeddings(interview, topic))

    _capture_user_interview_event(
        "user_interview_conversation_ended",
        sharing_config=sharing_config,
        call_id=call_id,
        session_id=session_id,
        extra_properties={
            "interview_id": str(interview.id),
            "had_transcript": bool(interview.transcript),
            "had_summary": bool(interview.summary),
        },
    )

    logger.info(
        "user_interviews_vapi_webhook_stored",
        team_id=sharing_config.team_id,
        topic_id=str(topic.id),
        interview_id=str(interview.id),
    )
    return Response({"status": "created", "interview_id": str(interview.id)}, status=status.HTTP_201_CREATED)


def _capture_user_interview_event(
    event: str,
    *,
    sharing_config: SharingConfiguration,
    call_id: str | None,
    session_id: str = "",
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """Fire a PostHog event for a user-interview lifecycle moment (conversation started/ended).
    Failures never propagate — analytics never blocks a webhook delivery.

    Vapi emits `status-update` per state transition and may re-fire `in-progress` after
    transient drops or warm-transfer flows, and end-of-call-report can be retried by Vapi
    until we ack. Set `$insert_id` to `<event>:<call_id>` so PostHog dedupes the second
    delivery at ingest — funnels see one start and one end per call.

    When a shared-link respondent supplied a valid session_id, it's attached as `$session_id` so
    the event (and thus the interview) associates with that session recording — this is how the
    session is linked without a dedicated DB column.

    The `distinct_id` is intentionally an opaque per-share UUID — *not* the interviewee's
    email/distinct_id — so these feature-usage events never create person profiles for the
    third-party interviewees themselves. The events report on the user_interviews feature, not
    the people being interviewed."""
    interviewee_context = sharing_config.interviewee_context
    if interviewee_context is None:
        return
    properties: dict[str, Any] = {
        "topic_id": str(interviewee_context.topic_id),
        "team_id": sharing_config.team_id,
        "call_id": call_id,
    }
    if session_id:
        properties["$session_id"] = session_id
    if call_id:
        properties["$insert_id"] = f"{event}:{call_id}"
    if extra_properties:
        properties.update(extra_properties)
    try:
        posthoganalytics.capture(
            distinct_id=f"user_interview:{interviewee_context.id}",
            event=event,
            properties=properties,
            groups=groups(organization=sharing_config.team.organization, team=sharing_config.team),
        )
    except Exception:
        logger.exception(
            "user_interviews_event_capture_failed",
            event=event,
            team_id=sharing_config.team_id,
            call_id=call_id,
        )
