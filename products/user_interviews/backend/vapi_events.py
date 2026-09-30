"""User interviews' handling of the inbound Vapi webhook.

``handle_vapi_webhook_delivery`` runs in the Celery task that the ingress vapi consumer
enqueues through ``facade.api.accept_vapi_event``. It persists a UserInterview row attributed
to the topic creator, idempotent on ``call.id``.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from django.db import connection, transaction

import structlog

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.event_usage import groups
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.user_interviews.backend.classification import derive_auto_classifications
from products.user_interviews.backend.logic import (
    RESPONDENT_KEY_MAX_CHARS,
    RESPONDENT_NAME_MAX_CHARS,
    clean_field,
    is_shared_interviewee_context,
    shared_interviewee_identifier,
    valid_distinct_id,
    valid_session_id,
)
from products.user_interviews.backend.models import UserInterview, UserInterviewClassification, UserInterviewTopic

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


def _lock_call(team_id: int, call_id: str) -> None:
    """Hold the sole right to store this call's report until the transaction ends.

    Nothing in the schema stops a second row for one call. Vapi resends a report whose receipt it
    lost, the endpoint asks for a resend when the enqueue fails, and the task is acknowledged after
    the run, so two runs for one call can be in flight together. Without this lock both pass the
    existence check and both insert, which gives the topic two interviews for one call and emits
    the embeddings twice. The run that loses waits here until the winner commits, and its next read
    then sees the row.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            [f"user_interviews_vapi_call:{team_id}:{call_id}"],
        )


def _capture_user_interview_event(
    event: str,
    *,
    team: Team,
    topic_id: str,
    interviewee_context_id: str,
    call_id: str | None,
    received_at: str | None,
    session_id: str = "",
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """Fire a PostHog event for a user-interview lifecycle moment (conversation started/ended).
    Failures never propagate — analytics never blocks a webhook delivery.

    Vapi emits `status-update` per state transition and may re-fire `in-progress` after
    transient drops or warm-transfer flows, and end-of-call-report can be retried by Vapi
    until we ack. Set `$insert_id` to `<event>:<call_id>` so PostHog dedupes the second
    delivery at ingest — funnels see one start and one end per call.

    The event carries the moment the endpoint received the delivery, not the moment this ran. The
    worker runs after the request, and later again on a retry, so the run time would put
    "conversation started" after "conversation ended" for the same call.

    When a shared-link respondent supplied a valid session_id, it's attached as `$session_id` so
    the event (and thus the interview) associates with that session recording — this is how the
    session is linked without a dedicated DB column.

    The `distinct_id` is intentionally an opaque per-share UUID — *not* the interviewee's
    email/distinct_id — so these feature-usage events never create person profiles for the
    third-party interviewees themselves. The events report on the user_interviews feature, not
    the people being interviewed."""
    properties: dict[str, Any] = {
        "topic_id": topic_id,
        "team_id": team.id,
        "call_id": call_id,
    }
    if session_id:
        properties["$session_id"] = session_id
    if call_id:
        properties["$insert_id"] = f"{event}:{call_id}"
    if extra_properties:
        properties.update(extra_properties)
    try:
        # This runs in the Celery task, where the global client's background flush may never run
        # before the worker exits, so the event is lost without a word. The scoped client flushes
        # when the context exits. A run emits at most one event, so the client is opened once.
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=f"user_interview:{interviewee_context_id}",
                event=event,
                properties=properties,
                timestamp=received_at,
                groups=groups(organization=team.organization, team=team),
            )
    except Exception:
        logger.exception(
            "user_interviews_event_capture_failed",
            event=event,
            team_id=team.id,
            call_id=call_id,
        )


def _backdate_to_receipt(interview: UserInterview, received_at: str | None) -> None:
    """Stamp the interview with the time the endpoint accepted the report, not the worker's."""
    if not received_at:
        return
    try:
        accepted_at = datetime.fromisoformat(received_at)
    except ValueError:
        return
    # created_at is auto_now_add, so the row must be updated after the insert.
    UserInterview.objects.filter(pk=interview.pk).update(created_at=accepted_at)
    interview.created_at = accepted_at


def handle_vapi_webhook_delivery(
    payload: Mapping[str, Any],
    event_type: str,
    *,
    team_id: int,
    topic_id: str,
    interviewee_context_id: str,
    interviewee_identifier: str,
    received_at: str | None,
) -> None:
    """Act on one verified Vapi delivery: the lifecycle event, and the end-of-call report.

    The share is not read here. ``accept_vapi_event`` resolved the token in the request, before
    the endpoint accepted the delivery, and took out of the share everything this needs. The
    share row does not survive the wait: the team can disable it, its token can leave the
    rotation grace period, and ``cleanup_expired_sharing_configs`` then deletes the row itself.
    Each of those would turn an accepted report into nothing. The topic and the interviewee
    context the share names outlive it.

    Idempotent on ``call.id`` (stored in ``call_metadata.id``). Vapi repeats that id across the
    status update and the end-of-call report, so ingress cannot dedup on it and this does
    instead: a repeat delivery of a report already stored creates nothing. The idempotency also
    covers the Celery retry that persistence rides on, and an advisory lock holds it when two of
    those runs overlap.
    """
    message: dict[str, Any] = payload.get("message") or {}
    call: dict[str, Any] = message.get("call") or {}
    # Vapi can surface our `assistant_overrides.metadata` (set in `start_call`) in two
    # places on the Call object: `call.metadata` for some message types, and nested under
    # `call.assistantOverrides.metadata` on others. Empirically end-of-call-report comes
    # through with the nested form, so try both.
    overrides_metadata: dict[str, Any] = (call.get("assistantOverrides") or {}).get("metadata") or {}
    top_metadata: dict[str, Any] = call.get("metadata") or {}
    # Shared-link respondent fields (set in start_call's metadata, echoed back by Vapi). Merge with
    # top-level precedence, mirroring how the access token is resolved when the delivery arrives.
    merged_metadata: dict[str, Any] = {**overrides_metadata, **top_metadata}
    call_id = call.get("id")
    if event_type == "end-of-call-report" and not call_id:
        # The call id is what makes a report idempotent, so a report without one would create a
        # blank interview on every redelivery.
        logger.warning("user_interviews_vapi_webhook_missing_call_id", team_id=team_id, topic_id=topic_id)
        return

    topic = (
        UserInterviewTopic.objects.select_related("team", "team__organization", "created_by")
        .filter(team_id=team_id, id=topic_id)
        .first()
    )
    if topic is None:
        # The team deleted the topic while the report waited in the queue, so there is nothing
        # left to file the report under. Say so, because the alternative reads like a delivery
        # that never arrived.
        logger.warning(
            "user_interviews_vapi_webhook_topic_gone",
            team_id=team_id,
            topic_id=topic_id,
            call_id=call_id,
        )
        return

    if event_type == "status-update":
        # Lifecycle ping. We only act on `in-progress` (call started) — the `ended` status
        # is followed by a separate `end-of-call-report` with the full transcript, so we
        # capture the ended event from that branch where we already have the interview row.
        call_status = message.get("status")
        if call_status == "in-progress":
            _capture_user_interview_event(
                "user_interview_conversation_started",
                team=topic.team,
                topic_id=topic_id,
                interviewee_context_id=interviewee_context_id,
                call_id=call_id,
                received_at=received_at,
                session_id=valid_session_id(merged_metadata.get("session_id")),
            )
        logger.info(
            "user_interviews_vapi_webhook_status_update",
            call_status=call_status,
            call_id=call_id,
        )
        return

    # The consumer registers for status-update and end-of-call-report only, so the registry
    # drops every other message type before this runs and the rest is the end-of-call report.
    recording_url = (message.get("recording") or {}).get("url", "") or message.get("recordingUrl", "") or ""
    transcript = message.get("transcript", "") or ""
    classifications = derive_auto_classifications(transcript)

    if is_shared_interviewee_context(interviewee_identifier):
        respondent_name = clean_field(merged_metadata.get("respondent_name"), RESPONDENT_NAME_MAX_CHARS)
        respondent_key = clean_field(merged_metadata.get("respondent_key"), RESPONDENT_KEY_MAX_CHARS)
        # Recompute the identifier from respondent_key rather than trusting the echoed metadata, so it
        # is always a namespaced shared marker and can never be steered onto a targeted invitee.
        stored_identifier = shared_interviewee_identifier(respondent_key)
        interviewee_emails = []
        # Best-effort, untrusted person linkage. Re-validated here (defense in depth) and stored in its
        # own column — never as the interviewee_identifier, so it can't forge attribution.
        distinct_id = valid_distinct_id(merged_metadata.get("distinct_id"))
        # session_id isn't persisted — it rides on the lifecycle event below. Re-validated here
        # (defense in depth) so only a well-formed UUIDv7 reaches the event.
        session_id = valid_session_id(merged_metadata.get("session_id"))
    else:
        stored_identifier = interviewee_identifier
        interviewee_emails = [stored_identifier] if "@" in stored_identifier else []
        respondent_name = respondent_key = ""
        distinct_id = ""
        session_id = ""

    with transaction.atomic():
        if call_id:
            _lock_call(team_id, call_id)
            existing = UserInterview.objects.filter(team_id=team_id, call_metadata__id=call_id).first()
            if existing is not None:
                logger.info(
                    "user_interviews_vapi_webhook_duplicate",
                    team_id=team_id,
                    interview_id=str(existing.id),
                    call_id=call_id,
                )
                return
        interview = UserInterview.objects.create(
            team=topic.team,
            topic=topic,
            interviewee_identifier=stored_identifier,
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
        _backdate_to_receipt(interview, received_at)
        # Collapse the abandoned partial an accidental refresh leaves behind: when a shared-link
        # respondent comes back (same respondent_key) and finishes, drop their earlier abandoned
        # rows so the topic shows one response per respondent instead of a junk trail.
        if respondent_key and UserInterviewClassification.ABANDONED not in classifications:
            _collapse_abandoned_partials(
                team=topic.team,
                topic=topic,
                respondent_key=respondent_key,
                keep_pk=interview.pk,
            )
        transaction.on_commit(lambda: _emit_interview_embeddings(interview, topic))

    _capture_user_interview_event(
        "user_interview_conversation_ended",
        team=topic.team,
        topic_id=topic_id,
        interviewee_context_id=interviewee_context_id,
        call_id=call_id,
        received_at=received_at,
        session_id=session_id,
        extra_properties={
            "interview_id": str(interview.id),
            "had_transcript": bool(interview.transcript),
            "had_summary": bool(interview.summary),
        },
    )

    logger.info(
        "user_interviews_vapi_webhook_stored",
        team_id=team_id,
        topic_id=topic_id,
        interview_id=str(interview.id),
    )
