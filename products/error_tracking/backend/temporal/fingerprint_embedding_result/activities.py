import time
from datetime import datetime, timedelta

from django.utils.dateparse import parse_datetime

from temporalio import activity

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal

from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)

PREFERRED_EMBEDDING_MODEL = "text-embedding-3-large-3072"


class TargetFingerprintEmbeddingNotFoundError(RuntimeError):
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


def _select_model_name(model_names: list[str]) -> str:
    if PREFERRED_EMBEDDING_MODEL in model_names:
        return PREFERRED_EMBEDDING_MODEL
    if model_names:
        return model_names[0]
    return PREFERRED_EMBEDDING_MODEL


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
        """
        SELECT embedding
        FROM document_embeddings
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND model_name = {model_name}
        AND document_id = {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND timestamp >= {min_timestamp}
        AND timestamp <= {max_timestamp}
        ORDER BY inserted_at DESC
        LIMIT 1
        """,
        placeholders={
            "fingerprint": ast.Constant(value=inputs.fingerprint),
            "model_name": ast.Constant(value=model_name),
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
    return parse_select(
        """
        SELECT document_id, cosineDistance({target_embedding}, embedding) AS distance
        FROM document_embeddings
        WHERE document_type = 'fingerprint'
        AND rendering = {rendering}
        AND model_name = {model_name}
        AND document_id != {fingerprint}
        AND product = 'error_tracking'
        AND team_id = {team_id}
        AND length(embedding) = length({target_embedding})
        ORDER BY distance ASC
        LIMIT 3
        """,
        placeholders={
            "fingerprint": ast.Constant(value=inputs.fingerprint),
            "model_name": ast.Constant(value=model_name),
            "rendering": ast.Constant(value=inputs.rendering),
            "team_id": ast.Constant(value=inputs.team_id),
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


def _query_closest_fingerprints(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
) -> list[SimilarFingerprintDistance]:
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


@activity.defn
@scoped_temporal()
async def merge_similar_fingerprints_activity(
    inputs: FingerprintEmbeddingResultInputs,
) -> FingerprintEmbeddingMergeResult:
    model_name: str | None = None
    try:
        team = await Team.objects.aget(id=inputs.team_id)
        model_name = _select_model_name(inputs.model_names)

        start = time.monotonic()
        closest_fingerprints = await database_sync_to_async(_query_closest_fingerprints)(team, inputs, model_name)
        query_duration_seconds = time.monotonic() - start
        query_duration_ms = query_duration_seconds * 1000

        # Keep emitting candidate metrics for every run; merging is gated separately by configuration.
        _report_closest_fingerprint_metrics(team, inputs, closest_fingerprints, model_name, query_duration_ms)

        return FingerprintEmbeddingMergeResult(
            query_duration_ms=query_duration_ms,
            closest_fingerprints=closest_fingerprints,
        )
    except Exception as err:
        _capture_activity_exception(err, inputs, model_name)
        raise
