import time
from datetime import datetime, timedelta

from django.conf import settings
from django.utils.dateparse import parse_datetime

import posthoganalytics
from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2, ErrorTrackingIssueMergeResult
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
    select_model_name,
)

AUTO_MERGE_DISTANCE_THRESHOLD = 0.019

TARGET_EMBEDDING_QUERY_BY_MODEL = {
    "text-embedding-3-large-3072": """
        SELECT embedding
        FROM document_embeddings_text_embedding_3_large_3072
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND document_id = {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND timestamp >= {min_timestamp}
        AND timestamp <= {max_timestamp}
        ORDER BY inserted_at DESC
        LIMIT 1
        """,
    "text-embedding-3-small-1536": """
        SELECT embedding
        FROM document_embeddings_text_embedding_3_small_1536
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND document_id = {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND timestamp >= {min_timestamp}
        AND timestamp <= {max_timestamp}
        ORDER BY inserted_at DESC
        LIMIT 1
        """,
}

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
        LIMIT 3
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
        LIMIT 3
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
    model_name: str | None,
) -> None:
    properties: dict[str, object] = {
        "activity": "merge_similar_fingerprints_activity",
        "workflow": "error-tracking-fingerprint-embedding-result",
        "team_id": inputs.team_id,
        "fingerprint": inputs.fingerprint,
        "rendering": inputs.rendering,
        "embedding_timestamp": inputs.timestamp,
        "model_names": inputs.model_names,
    }
    if model_name is not None:
        properties["model_name"] = model_name

    capture_exception(error, additional_properties=properties)


def _input_model_name(inputs: FingerprintEmbeddingResultInputs) -> str:
    return inputs.model_name or select_model_name(inputs.model_names)


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


def _target_embedding_query(
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
    embedding_timestamp: datetime,
) -> ast.SelectQuery | ast.SelectSetQuery:
    return parse_select(
        _model_specific_query(TARGET_EMBEDDING_QUERY_BY_MODEL, model_name),
        placeholders={
            "fingerprint": ast.Constant(value=inputs.fingerprint),
            "rendering": ast.Constant(value=inputs.rendering),
            "team_id": ast.Constant(value=inputs.team_id),
            "min_timestamp": ast.Constant(value=embedding_timestamp - timedelta(hours=1)),
            "max_timestamp": ast.Constant(value=embedding_timestamp + timedelta(hours=1)),
        },
    )


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


def _query_target_embedding(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
) -> list[float]:
    query = _target_embedding_query(
        inputs=inputs,
        model_name=model_name,
        embedding_timestamp=_parse_timestamp(inputs.timestamp),
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingFingerprintEmbeddingResultTargetEmbedding",
    )
    if not response.results:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding not found for fingerprint {inputs.fingerprint} with model {model_name}"
        )
    target_embedding = response.results[0][0]
    if not isinstance(target_embedding, list) or not target_embedding:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding is invalid for fingerprint {inputs.fingerprint} with model {model_name}"
        )
    try:
        return [float(value) for value in target_embedding]
    except (TypeError, ValueError) as err:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding contains non-numeric values for fingerprint {inputs.fingerprint} with model {model_name}"
        ) from err


def _target_embedding_from_inputs(inputs: FingerprintEmbeddingResultInputs, model_name: str) -> list[float] | None:
    if model_name != _input_model_name(inputs) or inputs.embedding is None:
        return None
    target_embedding = inputs.embedding
    if not target_embedding:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding is empty for fingerprint {inputs.fingerprint} with model {model_name}"
        )
    try:
        return [float(value) for value in target_embedding]
    except (TypeError, ValueError) as err:
        raise TargetFingerprintEmbeddingNotFoundError(
            f"Target embedding contains non-numeric values for fingerprint {inputs.fingerprint} with model {model_name}"
        ) from err


def _query_closest_fingerprints(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
) -> list[SimilarFingerprintDistance]:
    target_embedding = _target_embedding_from_inputs(inputs, model_name)
    if target_embedding is None:
        target_embedding = _query_target_embedding(team, inputs, model_name)

    query = _closest_fingerprints_query(
        inputs=inputs,
        model_name=model_name,
        target_embedding=target_embedding,
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingFingerprintEmbeddingResultClosestFingerprints",
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

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            event="error_tracking_fingerprint_embedding_result_metrics",
            groups=groups(team=team),
            properties=properties,
        )


def _merge_fingerprint_into_closest_issue(
    team: Team,
    fingerprint: str,
    closest_fingerprints: list[SimilarFingerprintDistance],
) -> int:
    closest_fingerprint = closest_fingerprints[0] if closest_fingerprints else None
    team_id = team.id
    if not settings.ERROR_TRACKING_AUTO_MERGE_ENABLED or closest_fingerprint is None:
        return 0
    if closest_fingerprint.distance >= AUTO_MERGE_DISTANCE_THRESHOLD:
        return 0

    fingerprints_by_value = {
        row.fingerprint: row
        for row in ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=team_id, fingerprint__in=[fingerprint, closest_fingerprint.fingerprint]
        )
        .select_related("issue")
        .order_by("fingerprint", "id")
    }
    source_fingerprint = fingerprints_by_value.get(fingerprint)
    if source_fingerprint is None:
        raise FingerprintIssueNotFoundError(f"Source fingerprint {fingerprint} not found for team {team_id}")

    target_fingerprint = fingerprints_by_value.get(closest_fingerprint.fingerprint)
    if target_fingerprint is None:
        raise FingerprintIssueNotFoundError(
            f"Target fingerprint {closest_fingerprint.fingerprint} not found for team {team_id}"
        )
    if source_fingerprint.issue_id == target_fingerprint.issue_id:
        return 0

    source_issue_id = source_fingerprint.issue_id
    target_issue_id = target_fingerprint.issue_id
    merge_result = target_fingerprint.issue.merge(
        issue_ids=[source_issue_id],
        expected_fingerprint_issue_ids={
            fingerprint: source_issue_id,
            closest_fingerprint.fingerprint: target_issue_id,
        },
    )
    if merge_result == ErrorTrackingIssueMergeResult.NO_SOURCE_ISSUES:
        return 0
    if merge_result != ErrorTrackingIssueMergeResult.MERGED:
        raise StaleAutoMergeStateError(f"Fingerprint issue ownership changed before auto-merge for team {team_id}")

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            event="error_tracking_issue_merged",
            groups=groups(team=team),
            properties={
                "merge_source": "auto",
                "source_issue_id": str(source_issue_id),
                "target_issue_id": str(target_issue_id),
                "source_fingerprint": fingerprint,
                "target_fingerprint": closest_fingerprint.fingerprint,
                "distance": closest_fingerprint.distance,
            },
        )
    return 1


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def merge_similar_fingerprints_activity(
    inputs: FingerprintEmbeddingResultInputs,
) -> FingerprintEmbeddingMergeResult:
    model_name: str | None = None
    try:
        team = Team.objects.get(id=inputs.team_id)
        model_name = _input_model_name(inputs)

        start = time.monotonic()
        closest_fingerprints = _query_closest_fingerprints(team, inputs, model_name)
        query_duration_seconds = time.monotonic() - start
        query_duration_ms = query_duration_seconds * 1000

        # Keep emitting candidate metrics for every run; merging is gated separately by configuration.
        _report_closest_fingerprint_metrics(team, inputs, closest_fingerprints, model_name, query_duration_ms)
        merged_count = _merge_fingerprint_into_closest_issue(
            team,
            inputs.fingerprint,
            closest_fingerprints,
        )

        return FingerprintEmbeddingMergeResult(
            merged_count=merged_count,
            query_duration_ms=query_duration_ms,
            closest_fingerprints=closest_fingerprints,
        )
    except Exception as err:
        _capture_activity_exception(err, inputs, model_name)
        raise
