import math
import time
import uuid

from django.conf import settings

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.event_usage import groups
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import ph_background_capture
from posthog.temporal.common.posthog_client import is_expected_activity_failure

from products.error_tracking.backend.indexed_embedding import EMBEDDING_TABLES
from products.error_tracking.backend.logic.assignees import resolve_current_assignee
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueMergeResult,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.judge import (
    DEFAULT_AUTO_MERGE_CONFIG,
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    AutoMergeConfig,
    JudgeUnavailableError,
    JudgeVerdict,
    ask_judge,
    load_auto_merge_config,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    CLOSEST_FINGERPRINTS_WINDOW,
    AutoMergeOutcome,
    AutoMergeReopenedTarget,
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
    parse_embedding_timestamp,
)
from products.error_tracking.backend.temporal.grouping_judge.inline import grouping_judge_properties
from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

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


FINGERPRINT_DOCUMENT_QUERY_BY_MODEL = {
    "text-embedding-3-large-3072": """
        SELECT document_id, argMax(content, inserted_at) AS content
        FROM document_embeddings_text_embedding_3_large_3072
        WHERE document_type = 'fingerprint'
        AND product = 'error_tracking'
        AND rendering = {rendering}
        AND team_id = {team_id}
        AND document_id = {fingerprint}
        AND timestamp >= {min_timestamp}
        GROUP BY document_id
        """,
    "text-embedding-3-small-1536": """
        SELECT document_id, argMax(content, inserted_at) AS content
        FROM document_embeddings_text_embedding_3_small_1536
        WHERE document_type = 'fingerprint'
        AND product = 'error_tracking'
        AND rendering = {rendering}
        AND team_id = {team_id}
        AND document_id = {fingerprint}
        AND timestamp >= {min_timestamp}
        GROUP BY document_id
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


def _closest_fingerprints_query(
    inputs: FingerprintEmbeddingResultInputs,
    model_name: str,
    target_embedding: list[float],
) -> ast.SelectQuery | ast.SelectSetQuery:
    min_timestamp = parse_embedding_timestamp(inputs.timestamp) - CLOSEST_FINGERPRINTS_WINDOW
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
    judge_properties: dict[str, object],
) -> None:
    properties: dict[str, object] = {
        "model_name": model_name,
        "rendering": inputs.rendering,
        "fingerprint": inputs.fingerprint,
        "query_duration_ms": query_duration_ms,
        "closest_fingerprint_count": len(closest_fingerprints),
        **judge_properties,
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
    current_assignee = resolve_current_assignee(issue.id)
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
        assignee=current_assignee.property_value if current_assignee is not None else None,
    )


def _merge_into_candidate(
    team: Team,
    fingerprint: str,
    source_fingerprint: ErrorTrackingIssueFingerprintV2,
    target_fingerprint: ErrorTrackingIssueFingerprintV2,
    candidate: SimilarFingerprintDistance,
    event_reference: str,
    decision_properties: dict[str, object],
) -> AutoMergeOutcome:
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
        raise StaleAutoMergeStateError(f"Fingerprint issue ownership changed before auto-merge for team {team.id}")

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
            **decision_properties,
        },
    )
    reopened_target = (
        _reopened_target(target_issue, event_reference=event_reference) if merge_outcome.reopened else None
    )
    return AutoMergeOutcome(
        merged_count=1,
        reopened_target=reopened_target,
        target_fingerprint=candidate.fingerprint,
        merge_decision=str(decision_properties["merge_decision"]),
    )


def _fetch_fingerprint_document(
    team: Team, inputs: FingerprintEmbeddingResultInputs, fingerprint: str, *, timeout_seconds: float
) -> str | None:
    """The text that was embedded for a fingerprint, within the nearest-neighbour search window."""
    query = parse_select(
        _model_specific_query(FINGERPRINT_DOCUMENT_QUERY_BY_MODEL, inputs.model_name),
        placeholders={
            "rendering": ast.Constant(value=inputs.rendering),
            "team_id": ast.Constant(value=team.id),
            "fingerprint": ast.Constant(value=fingerprint),
            "min_timestamp": ast.Constant(
                value=parse_embedding_timestamp(inputs.timestamp) - CLOSEST_FINGERPRINTS_WINDOW
            ),
        },
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ErrorTrackingAutoMergeJudgeDocument",
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.ERROR_TRACKING,
        settings=HogQLGlobalSettings(max_execution_time=max(1, math.ceil(timeout_seconds))),
    )
    return next((row[1] for row in response.results if row[1]), None)


def _judge(
    team: Team, inputs: FingerprintEmbeddingResultInputs, candidate: SimilarFingerprintDistance, config: AutoMergeConfig
) -> JudgeVerdict:
    """Judge one pair within the judge timeout. Raises JudgeUnavailableError with the reason when it can't."""
    # Consent can be withdrawn between embedding and this (possibly retried) activity.
    if not team.organization.is_ai_data_processing_approved:
        raise JudgeUnavailableError("ai_processing_not_approved")
    # One budget for the lookup and the inference, so a slow ClickHouse can't hold the activity longer.
    deadline = time.monotonic() + config.judge_timeout_seconds
    try:
        candidate_document = _fetch_fingerprint_document(
            team, inputs, candidate.fingerprint, timeout_seconds=config.judge_timeout_seconds
        )
    except Exception as err:
        if is_expected_activity_failure(err):
            raise
        capture_exception(err, additional_properties={"team_id": team.id, "fingerprint": inputs.fingerprint})
        raise JudgeUnavailableError("document_fetch_failed") from err
    # The source text arrives with the inputs: ClickHouse may not have ingested it yet.
    if not inputs.content or not candidate_document:
        raise JudgeUnavailableError("missing_document")
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise JudgeUnavailableError("judge_timeout")
    return ask_judge(team.id, inputs.content, candidate_document, remaining_seconds)


def _judge_candidate(
    team: Team,
    inputs: FingerprintEmbeddingResultInputs,
    candidate: SimilarFingerprintDistance,
    config: AutoMergeConfig,
) -> float | None:
    """Ask the judge about one candidate and report the verdict. Returns the score, or None when unavailable.

    A judge failure never fails the activity: the fingerprint just stays unmerged, as it would today.
    """
    score: float | None = None
    latency_ms: float | None = None
    error: str | None = None
    try:
        verdict = _judge(team, inputs, candidate, config)
        score, latency_ms = verdict.score, verdict.latency_ms
    except JudgeUnavailableError as err:
        error = str(err)

    capture = ph_background_capture()
    capture(
        distinct_id=str(team.uuid),
        event="error_tracking_auto_merge_judged",
        groups=groups(team=team),
        properties={
            "source_fingerprint": inputs.fingerprint,
            "target_fingerprint": candidate.fingerprint,
            "distance": candidate.distance,
            "judge_score": score,
            "judge_latency_ms": latency_ms,
            "judge_error": error,
            "judge_model": JUDGE_MODEL,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_cutoff": config.judge_cutoff,
            "judge_max_distance": config.judge_max_distance,
            "judge_shadow": config.judge_shadow,
            "auto_merge_threshold": config.auto_merge_threshold,
            "would_merge": score is not None and score >= config.judge_cutoff,
        },
    )
    return score


def _merge_fingerprint_into_closest_issue(
    team: Team,
    fingerprint: str,
    closest_fingerprints: list[SimilarFingerprintDistance],
    expected_source_issue_id: str | None = None,
    event_reference: str = "",
    config: AutoMergeConfig = DEFAULT_AUTO_MERGE_CONFIG,
    judge_inputs: FingerprintEmbeddingResultInputs | None = None,
) -> AutoMergeOutcome:
    """Merge into the nearest neighbour in another issue: directly below the threshold, else if the judge agrees.

    `judge_inputs` carries what the judge needs (model, rendering, source text); without it only the
    distance rule applies.
    """
    team_id = team.id
    if not settings.ERROR_TRACKING_AUTO_MERGE_ENABLED:
        return AutoMergeOutcome()

    judging = config.judge_enabled and judge_inputs is not None
    candidates = [
        candidate
        for candidate in closest_fingerprints
        if candidate.distance < config.auto_merge_threshold
        or (judging and candidate.distance <= config.judge_max_distance)
    ]
    if not candidates:
        return AutoMergeOutcome()

    fingerprints_by_value = {
        row.fingerprint: row
        for row in ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=team_id,
            fingerprint__in=[fingerprint, *(candidate.fingerprint for candidate in candidates)],
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

    # Candidates come nearest first, so a distance merge always wins over a judged one.
    for candidate in candidates:
        target_fingerprint = fingerprints_by_value.get(candidate.fingerprint)
        if target_fingerprint is None or source_fingerprint.issue_id == target_fingerprint.issue_id:
            continue
        if candidate.distance < config.auto_merge_threshold:
            decision: dict[str, object] = {
                "merge_decision": "distance",
                "auto_merge_threshold": config.auto_merge_threshold,
            }
        elif judge_inputs is not None:
            score = _judge_candidate(team, judge_inputs, candidate, config)
            if score is None or score < config.judge_cutoff or config.judge_shadow:
                return AutoMergeOutcome()
            decision = {
                "merge_decision": "judge",
                "judge_score": score,
                "judge_cutoff": config.judge_cutoff,
                "judge_model": JUDGE_MODEL,
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
            }
        else:
            continue
        return _merge_into_candidate(
            team, fingerprint, source_fingerprint, target_fingerprint, candidate, event_reference, decision
        )

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

        # Only read the flag when there is something to decide.
        config = (
            load_auto_merge_config(team)
            if settings.ERROR_TRACKING_AUTO_MERGE_ENABLED and closest_fingerprints
            else DEFAULT_AUTO_MERGE_CONFIG
        )
        merge_outcome: AutoMergeOutcome | None = None
        try:
            merge_outcome = _merge_fingerprint_into_closest_issue(
                team,
                inputs.fingerprint,
                closest_fingerprints,
                inputs.source_issue_id,
                event_reference=_event_reference(inputs),
                config=config,
                judge_inputs=inputs,
            )
        finally:
            # Keep emitting candidate metrics for every run; merging is gated separately by configuration.
            # The grouping judge runs only after the merge decision, so it cannot change it.
            judge_properties = grouping_judge_properties(team, inputs, closest_fingerprints, merge_outcome, config)
            _report_closest_fingerprint_metrics(
                team, inputs, closest_fingerprints, inputs.model_name, query_duration_ms, judge_properties
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
