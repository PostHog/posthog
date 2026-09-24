import time
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils.dateparse import parse_datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import ph_background_capture
from posthog.temporal.common.posthog_client import is_expected_activity_failure

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.error_tracking.backend.logic.assignees import current_assignee_property
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueMergeResult,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    AutoMergeOutcome,
    AutoMergeReopenedTarget,
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)
from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

AUTO_MERGE_DISTANCE_THRESHOLD = 0.019
NIL_UUID = "00000000-0000-0000-0000-000000000000"

CLOSEST_FINGERPRINTS_QUERY_BY_MODEL = {
    "text-embedding-3-large-3072": """
        SELECT document_id, cosineDistance({target_embedding}, embedding) AS distance
        FROM document_embeddings_text_embedding_3_large_3072
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND document_id != {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND timestamp >= {min_timestamp}
        ORDER BY distance ASC
        LIMIT 10
        """,
    "text-embedding-3-small-1536": """
        SELECT document_id, cosineDistance({target_embedding}, embedding) AS distance
        FROM document_embeddings_text_embedding_3_small_1536
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND document_id != {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND timestamp >= {min_timestamp}
        ORDER BY distance ASC
        LIMIT 10
        """,
}


class TargetFingerprintEmbeddingNotFoundError(RuntimeError):
    pass


class FingerprintIssueNotFoundError(RuntimeError):
    pass


class StaleAutoMergeStateError(RuntimeError):
    pass


def _capture_activity_exception(
    error: Exception,
    inputs: FingerprintEmbeddingResultInputs,
    *,
    activity_name: str,
    workflow_name: str,
) -> None:
    properties: dict[str, object] = {
        "activity": activity_name,
        "workflow": workflow_name,
        "team_id": inputs.team_id,
        "fingerprint": inputs.fingerprint,
        "rendering": inputs.rendering,
        "embedding_timestamp": inputs.timestamp,
        "model_name": inputs.model_name,
    }

    capture_exception(error, additional_properties=properties)


def _model_specific_embeddings_table_name(model_name: str) -> str:
    for table in EMBEDDING_TABLES:
        if table.model_name == model_name:
            return f"document_embeddings_{table.normalized_model_name}"
    raise ValueError(f"Invalid embedding model: {model_name}")


def _model_specific_query(query_by_model: dict[str, str], model_name: str) -> str:
    _model_specific_embeddings_table_name(model_name)
    query = query_by_model.get(model_name)
    if query is None:
        raise ValueError(f"No query configured for embedding model: {model_name}")
    return query


def _parse_timestamp(timestamp: str) -> datetime:
    parsed = parse_datetime(timestamp)
    if parsed is None:
        raise ValueError(f"Invalid embedding timestamp: {timestamp}")
    return parsed


def _closest_fingerprints_query(
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
    target_embedding: list[float],
) -> ast.SelectQuery | ast.SelectSetQuery:
    min_timestamp = _parse_timestamp(inputs.timestamp) - timedelta(days=30)
    return parse_select(
        _model_specific_query(CLOSEST_FINGERPRINTS_QUERY_BY_MODEL, model_name),
        placeholders={
            "fingerprint": ast.Constant(value=inputs.fingerprint),
            "rendering": ast.Constant(value=inputs.rendering),
            "team_id": ast.Constant(value=inputs.team_id),
            "min_timestamp": ast.Constant(value=min_timestamp),
            "target_embedding": ast.Constant(value=target_embedding),
        },
    )


def _target_embedding_from_inputs(inputs: FingerprintEmbeddingResultInputs) -> list[float]:
    target_embedding = inputs.embedding
    if not target_embedding:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding is empty for fingerprint {inputs.fingerprint} with model {inputs.model_name}"
        )
    try:
        return [float(value) for value in target_embedding]
    except (TypeError, ValueError) as err:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding contains non-numeric values for fingerprint {inputs.fingerprint} with model {inputs.model_name}"
        ) from err


def _query_closest_fingerprints(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
) -> list[SimilarFingerprintDistance]:
    query = _closest_fingerprints_query(
        inputs=inputs,
        model_name=model_name,
        target_embedding=_target_embedding_from_inputs(inputs),
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingFingerprintEmbeddingResultClosestFingerprints",
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
    )
    return [SimilarFingerprintDistance(fingerprint=row[0], distance=float(row[1])) for row in response.results]


def _report_closest_fingerprint_metrics(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    closest_fingerprints: list[SimilarFingerprintDistance],
    model_name: str,
    query_duration_ms: float,
) -> None:
    properties: dict[str, object] = {
        "model_name": model_name,
        "rendering": inputs.rendering,
        "fingerprint": inputs.fingerprint,
        "query_duration_ms": query_duration_ms,
        "closest_fingerprint_count": len(closest_fingerprints),
    }
    for index, closest_fingerprint in enumerate(closest_fingerprints[:3], start=1):
        properties[f"rank_{index}_fingerprint"] = closest_fingerprint.fingerprint
        properties[f"rank_{index}_distance"] = closest_fingerprint.distance

    capture = ph_background_capture()
    capture(
        distinct_id=str(team.uuid),
        event="error_tracking_fingerprint_embedding_result_metrics",
        groups=groups(team=team),
        properties=properties,
    )


def _event_reference(inputs: FingerprintEmbeddingResultInputs) -> str:
    """Name the exception that caused the reopen, for the notification id.

    A nil event uuid is truthy but names nothing, so it falls back to the exception's own
    timestamp. `timestamp` is the issue's creation time, so it is the last resort only.
    """
    if inputs.event_uuid and inputs.event_uuid != NIL_UUID:
        return inputs.event_uuid
    return inputs.event_timestamp or inputs.timestamp


def _reopened_target(
    issue: ErrorTrackingIssue,
    *,
    event_reference: str,
) -> AutoMergeReopenedTarget:
    # Same key shape cymbal uses for a reopen it detects during linking, so the two paths
    # cannot deliver two notifications for one exception.
    notification_id = uuid.uuid5(uuid.NAMESPACE_OID, f"issue_reopened:{issue.team_id}:{issue.id}:{event_reference}")
    return AutoMergeReopenedTarget(
        notification_id=str(notification_id),
        issue_id=str(issue.id),
        issue=LifecycleIssueSnapshot(
            name=issue.name,
            description=issue.description,
            status=issue.status,
            created_at=issue.created_at.isoformat(),
            severity=issue.severity,
        ),
        assignee=current_assignee_property(issue),
    )


def _merge_fingerprint_into_closest_issue(
    team: Team,
    fingerprint: str,
    closest_fingerprints: list[SimilarFingerprintDistance],
    expected_source_issue_id: str | None = None,
    event_reference: str = "",
) -> AutoMergeOutcome:
    team_id = team.id
    if not settings.ERROR_TRACKING_AUTO_MERGE_ENABLED:
        return AutoMergeOutcome()

    eligible_fingerprints = [
        candidate for candidate in closest_fingerprints if candidate.distance < AUTO_MERGE_DISTANCE_THRESHOLD
    ]
    if not eligible_fingerprints:
        return AutoMergeOutcome()

    fingerprints_by_value = {
        row.fingerprint: row
        for row in ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=team_id,
            fingerprint__in=[fingerprint, *(candidate.fingerprint for candidate in eligible_fingerprints)],
        )
        .select_related("issue")
        .order_by("fingerprint", "id")
    }
    source_fingerprint = fingerprints_by_value.get(fingerprint)
    if source_fingerprint is None:
        raise FingerprintIssueNotFoundError(f"Source fingerprint {fingerprint} not found for team {team_id}")

    if expected_source_issue_id is not None and str(source_fingerprint.issue_id) != expected_source_issue_id:
        source_issue_exists = ErrorTrackingIssue.objects.filter(team_id=team_id, id=expected_source_issue_id).exists()
        if not source_issue_exists:
            # The merge committed but its activity completion may have been lost. Treat a deleted
            # source issue as merged so an activity retry cannot emit a duplicate issue-created alert.
            return AutoMergeOutcome(merged_count=1)
        # A split or reassignment moved the fingerprint without deleting the issue. No merge
        # completed, so allow the issue-created side effects instead of exhausting activity retries.
        return AutoMergeOutcome()

    for candidate in eligible_fingerprints:
        target_fingerprint = fingerprints_by_value.get(candidate.fingerprint)
        if target_fingerprint is None or source_fingerprint.issue_id == target_fingerprint.issue_id:
            continue

        source_issue_id = source_fingerprint.issue_id
        target_issue_id = target_fingerprint.issue_id
        target_issue = target_fingerprint.issue
        merge_outcome = target_issue.merge(
            issue_ids=[source_issue_id],
            expected_fingerprint_issue_ids={
                fingerprint: source_issue_id,
                candidate.fingerprint: target_issue_id,
            },
        )
        if merge_outcome.result == ErrorTrackingIssueMergeResult.NO_SOURCE_ISSUES:
            return AutoMergeOutcome()
        if merge_outcome.result != ErrorTrackingIssueMergeResult.MERGED:
            raise StaleAutoMergeStateError(f"Fingerprint issue ownership changed before auto-merge for team {team_id}")

        capture = ph_background_capture()
        capture(
            distinct_id=str(team.uuid),
            event="error_tracking_issue_merged",
            groups=groups(team=team),
            properties={
                "merge_source": "auto",
                "source_issue_id": str(source_issue_id),
                "target_issue_id": str(target_issue_id),
                "source_fingerprint": fingerprint,
                "target_fingerprint": candidate.fingerprint,
                "distance": candidate.distance,
            },
        )
        reopened_target = (
            _reopened_target(target_issue, event_reference=event_reference) if merge_outcome.reopened else None
        )
        return AutoMergeOutcome(merged_count=1, reopened_target=reopened_target)

    return AutoMergeOutcome()


def merge_similar_fingerprints(
    inputs: FingerprintEmbeddingResultInputs,
    *,
    activity_name: str,
    workflow_name: str,
) -> FingerprintEmbeddingMergeResult:
    try:
        try:
            team = Team.objects.get(id=inputs.team_id)
        except Team.DoesNotExist:
            # The team can be deleted while the workflow waits to invoke this activity.
            return FingerprintEmbeddingMergeResult()

        start = time.monotonic()
        closest_fingerprints = _query_closest_fingerprints(team, inputs, inputs.model_name)
        query_duration_seconds = time.monotonic() - start
        query_duration_ms = query_duration_seconds * 1000

        # Keep emitting candidate metrics for every run; merging is gated separately by configuration.
        _report_closest_fingerprint_metrics(team, inputs, closest_fingerprints, inputs.model_name, query_duration_ms)
        merge_outcome = _merge_fingerprint_into_closest_issue(
            team,
            inputs.fingerprint,
            closest_fingerprints,
            inputs.source_issue_id,
            event_reference=_event_reference(inputs),
        )

        return FingerprintEmbeddingMergeResult(
            merged_count=merge_outcome.merged_count,
            query_duration_ms=query_duration_ms,
            closest_fingerprints=closest_fingerprints,
            reopened_target=merge_outcome.reopened_target,
        )
    except Exception as err:
        # A drained worker raises a cancellation straight into this thread, usually while the
        # merge waits on a row lock, so the trace looks like a database fault.
        if not is_expected_activity_failure(err):
            _capture_activity_exception(
                err,
                inputs,
                activity_name=activity_name,
                workflow_name=workflow_name,
            )
        raise
