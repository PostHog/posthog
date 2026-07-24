import json
from datetime import UTC

from django.utils.dateparse import parse_datetime

import httpx
import requests
import posthoganalytics
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.api.embedding_worker import generate_embedding
from posthog.kafka_client.routing import producer_scope
from posthog.kafka_client.topics import KAFKA_DOCUMENT_EMBEDDINGS_TOPIC
from posthog.models import Team
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import merge_similar_fingerprints
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
)
from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties
from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
    GeneratedIssueEmbedding,
    IssueCreatedWorkflowInputs,
    IssueEmbeddingPreparationResult,
)
from products.error_tracking.backend.temporal.lifecycle.rendering import render_stacktrace
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    KAFKA_DELIVERY_TIMEOUT_SECONDS,
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)

EMBEDDING_MODEL = "text-embedding-3-large-3072"
EMBEDDING_RENDERING = "type_message_and_stack"
EMBEDDING_MAX_TOKENS = 7000
EMBEDDING_DISABLED_LIBRARIES = {"posthog-elixir"}


def _embedding_skip_reason(event_properties: dict[str, object]) -> str | None:
    fingerprint_record = event_properties.get("$exception_fingerprint_record")
    if isinstance(fingerprint_record, list):
        for value in fingerprint_record:
            if not isinstance(value, dict):
                continue
            record_type = value.get("type")
            if record_type == "manual":
                return "manual_fingerprint"
            if record_type == "custom":
                return "custom_grouping_rule"

    library = event_properties.get("$lib")
    if isinstance(library, str) and library in EMBEDDING_DISABLED_LIBRARIES:
        return "disabled_sdk"
    return None


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def generate_issue_created_embedding_activity(
    inputs: IssueCreatedWorkflowInputs,
) -> IssueEmbeddingPreparationResult:
    try:
        team = Team.objects.get(id=inputs.team_id)
    except Team.DoesNotExist:
        return IssueEmbeddingPreparationResult(team_exists=False)

    if not team.organization.is_ai_data_processing_approved:
        return IssueEmbeddingPreparationResult(
            team_exists=True,
            skipped_reason="ai_data_processing_not_approved",
        )

    event_properties = fetch_event_properties(team, inputs)
    skipped_reason = _embedding_skip_reason(event_properties)
    if skipped_reason is not None:
        return IssueEmbeddingPreparationResult(team_exists=True, skipped_reason=skipped_reason)

    content = render_stacktrace(event_properties, EMBEDDING_MAX_TOKENS)
    try:
        response = generate_embedding(team, content, model=EMBEDDING_MODEL, no_truncate=True, timeout=60)
    except (requests.RequestException, httpx.HTTPError) as error:
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        if status_code is not None and status_code < 500 and status_code != 429:
            raise ApplicationError(
                f"Embedding service rejected the request with status {status_code}",
                type="EmbeddingRequestRejected",
                non_retryable=True,
            ) from error
        raise ApplicationError(
            "Embedding service is unavailable",
            type=EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
        ) from error
    except (KeyError, TypeError) as error:
        raise ApplicationError(
            "Embedding service returned an invalid response",
            type=EMBEDDING_SERVICE_UNAVAILABLE_ERROR_TYPE,
        ) from error
    return IssueEmbeddingPreparationResult(
        team_exists=True,
        embedding=GeneratedIssueEmbedding(
            merge_inputs=FingerprintEmbeddingResultInputs(
                team_id=inputs.team_id,
                fingerprint=inputs.fingerprint,
                rendering=EMBEDDING_RENDERING,
                timestamp=inputs.issue.created_at,
                model_name=EMBEDDING_MODEL,
                embedding=response.embedding,
                source_issue_id=inputs.issue_id,
            ),
            content=content,
        ),
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def persist_issue_created_embedding_activity(inputs: GeneratedIssueEmbedding) -> None:
    merge_inputs = inputs.merge_inputs
    timestamp = parse_datetime(merge_inputs.timestamp)
    if timestamp is None:
        raise ValueError(f"Invalid issue creation timestamp: {merge_inputs.timestamp}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    payload = {
        "team_id": merge_inputs.team_id,
        "product": "error_tracking",
        "document_type": "fingerprint",
        "model_name": merge_inputs.model_name,
        "rendering": merge_inputs.rendering,
        "document_id": merge_inputs.fingerprint,
        "timestamp": timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "embedding": merge_inputs.embedding,
        "content": inputs.content,
        "metadata": json.dumps({}),
    }

    with producer_scope(
        topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, flush_timeout=KAFKA_DELIVERY_TIMEOUT_SECONDS
    ) as producer:
        result = producer.produce(topic=KAFKA_DOCUMENT_EMBEDDINGS_TOPIC, data=payload)
    result.get(timeout=0)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def merge_issue_created_fingerprint_activity(
    inputs: FingerprintEmbeddingResultInputs,
) -> FingerprintEmbeddingMergeResult:
    return merge_similar_fingerprints(
        inputs,
        activity_name="merge_issue_created_fingerprint_activity",
        workflow_name="error-tracking-issue-created",
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def emit_issue_created_internal_event_activity(inputs: IssueCreatedWorkflowInputs) -> None:
    produce_issue_lifecycle_internal_event(
        inputs,
        event="$error_tracking_issue_created",
        exception_timestamp=inputs.event_timestamp,
        humanize_status=False,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def emit_issue_created_signal_activity(inputs: IssueCreatedWorkflowInputs) -> None:
    await emit_issue_lifecycle_signal(
        inputs,
        source_type="issue_created",
        preamble="New error tracking issue created - this particular exception was observed for the first time",
    )


ACTIVITIES = [
    generate_issue_created_embedding_activity,
    persist_issue_created_embedding_activity,
    merge_issue_created_fingerprint_activity,
    emit_issue_created_internal_event_activity,
    emit_issue_created_signal_activity,
]
