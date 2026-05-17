"""Public, unauthenticated endpoints for the user_interviews product.

Two surfaces live here, both keyed on a SharingConfiguration access token:

* ``start_call`` — called by the public interview page when the recipient clicks
  Start. Returns the Vapi credentials and the personalized assistant overrides
  (including merged ``agent_context``). Keeps that context off the initial HTML.
* ``vapi_webhook`` — called by Vapi at end-of-call. Persists a UserInterview row
  attributed to the topic creator. Signature-verified; idempotent on ``call.id``.
"""

import hmac
import json
import hashlib
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now

import structlog
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.constants import AvailableFeature
from posthog.models.sharing_configuration import SharingConfiguration

from .models import UserInterview, UserInterviewTopic

logger = structlog.get_logger(__name__)


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


def _verify_signature(secret: str, raw_body: bytes, provided_signature: str | None) -> bool:
    if not secret or not provided_signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided_signature, expected)


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


def _normalise_topic(topic_text: str) -> str:
    return " ".join(topic_text.split())[:_TOPIC_MAX_CHARS]


def _build_first_message(*, user_name: str, topic_text: str) -> str:
    name_part = f"Hi {user_name.strip()}!" if user_name.strip() else "Hi there!"
    greeting = f"{name_part} Thanks for joining."
    topic_normalised = _normalise_topic(topic_text)
    if topic_normalised:
        return (
            f"{greeting} Today we're talking about {topic_normalised}. I'd love your perspective. Ready when you are."
        )
    return f"{greeting} I'd love your perspective. Ready when you are."


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def start_call(request: Request, access_token: str) -> Response:
    """Return the Vapi credentials + assistant overrides for a public interview share.

    The personalized ``agent_context`` (which may include internal CRM notes about the
    interviewee) is intentionally NOT embedded in the public interview page's HTML — it
    is fetched from here only when the recipient clicks Start. This keeps casual
    view-source / window.POSTHOG_EXPORTED_DATA inspection from leaking the agent prompt.

    Note: anyone with the share token can still get this payload — by design, since
    they also use it to actually start the call. The win is removing the leak from the
    initial HTML and giving us a single, auditable, rate-limitable surface.
    """
    from .api import _merge_agent_context, _parse_identifier

    if not settings.VAPI_PUBLIC_KEY or not settings.VAPI_ASSISTANT_ID:
        return Response(
            {"error": "Vapi is not configured on this PostHog instance."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    sharing_config = _resolve_share(access_token)
    if sharing_config is None or sharing_config.interviewee_context is None:
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)
    if _public_sharing_disabled_for_org(sharing_config):
        # Match the public viewer's behavior: return 404 so the kill switch is opaque to
        # link recipients (doesn't reveal whether the token is real, just disabled).
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)

    ic = sharing_config.interviewee_context
    topic = ic.topic
    user_name, _ = _parse_identifier(ic.interviewee_identifier)
    agent_context = _merge_agent_context(topic.agent_context or "", ic.agent_context or "")
    first_message = _build_first_message(user_name=user_name, topic_text=topic.topic or "")

    return Response(
        {
            "public_key": settings.VAPI_PUBLIC_KEY,
            "assistant_id": settings.VAPI_ASSISTANT_ID,
            "assistant_overrides": {
                "firstMessage": first_message,
                "variableValues": {
                    "userName": user_name,
                    "topic": topic.topic or "",
                    "agent_context": agent_context,
                    # `json.dumps` so the Vapi assistant prompt receives standard JSON
                    # (`["q1", "q2"]`) rather than Python's repr (`['q1', 'q2']`).
                    "questions": json.dumps(topic.questions or []),
                },
                "metadata": {
                    "topic_id": str(topic.id),
                    "interviewee_identifier": ic.interviewee_identifier,
                    "sharing_access_token": access_token,
                },
            },
        }
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
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
        return Response(
            {"error": "Vapi webhook secret is not configured on this PostHog instance."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    provided = request.headers.get("x-vapi-signature") or request.headers.get("X-Vapi-Signature")
    if not _verify_signature(settings.VAPI_WEBHOOK_SECRET, request.body, provided):
        return Response({"error": "invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

    payload = request.data if isinstance(request.data, dict) else {}
    message: dict[str, Any] = payload.get("message", {})
    if message.get("type") != "end-of-call-report":
        # Other event types (status updates, transcripts mid-call) are ignored.
        return Response({"status": "ignored"})

    call: dict[str, Any] = message.get("call", {}) or {}
    metadata: dict[str, Any] = call.get("metadata", {}) or {}
    access_token = metadata.get("sharing_access_token") or metadata.get("access_token")
    call_id = call.get("id")

    if not access_token:
        return Response(
            {"error": "missing sharing_access_token in call.metadata"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sharing_config = _resolve_share(access_token)
    if sharing_config is None:
        return Response({"error": "unknown access_token"}, status=status.HTTP_404_NOT_FOUND)

    interviewee_context = sharing_config.interviewee_context
    if interviewee_context is None:
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

    topic = interviewee_context.topic
    recording_url = (message.get("recording") or {}).get("url", "") or message.get("recordingUrl", "") or ""

    with transaction.atomic():
        interview = UserInterview.objects.create(
            team=sharing_config.team,
            topic=topic,
            interviewee_identifier=interviewee_context.interviewee_identifier,
            interviewee_emails=[interviewee_context.interviewee_identifier]
            if "@" in interviewee_context.interviewee_identifier
            else [],
            transcript=message.get("transcript", "") or "",
            summary=message.get("summary", "") or "",
            recording_url=recording_url,
            call_metadata=call,
            created_by=topic.created_by,
        )
        transaction.on_commit(lambda: _emit_interview_embeddings(interview, topic))

    logger.info(
        "user_interviews_vapi_webhook_stored",
        team_id=sharing_config.team_id,
        topic_id=str(topic.id),
        interview_id=str(interview.id),
        interviewee=interviewee_context.interviewee_identifier,
    )
    return Response({"status": "created", "interview_id": str(interview.id)}, status=status.HTTP_201_CREATED)
