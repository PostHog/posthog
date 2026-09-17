"""User interviews' handling of the inbound Vapi webhook.

The endpoint in ``presentation/webhooks.py`` calls in here once a delivery is verified. The
persistence side of the webhook lives beside ``logic.py`` rather than in the view file, so the
view holds the HTTP surfaces and this module holds what the product does with a call.
"""

from typing import Any

import structlog
import posthoganalytics

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.event_usage import groups
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.team import Team

from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.models import UserInterview, UserInterviewClassification, UserInterviewTopic

logger = structlog.get_logger(__name__)

_EMBEDDING_MODELS = [m.value for m in EmbeddingModelName]

# TODO: figure out a better story for transcripts that exceed our Kafka envelope
# than head-truncation. Options: (a) chunk + emit multiple documents per type, or
# (b) push large content to object storage and embed a reference. Truncation is a
# stop-gap so a 90-minute interview doesn't silently lose its embeddings entirely.
EMBEDDING_CONTENT_MAX_BYTES = 750_000


def emit_interview_embeddings(interview: UserInterview, topic: UserInterviewTopic) -> None:
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


def collapse_abandoned_partials(*, team: Team, topic: UserInterviewTopic, respondent_key: str, keep_pk: Any) -> None:
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
    deleted_count, _ = UserInterview.objects.filter(
        team=team,
        topic=topic,
        respondent_key=respondent_key,
        pk__in=stale_pks,
    ).delete()
    logger.info(
        "user_interviews_collapsed_abandoned_partials",
        team_id=team.id,
        topic_id=str(topic.id),
        deleted_count=deleted_count,
    )


def capture_user_interview_event(
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
