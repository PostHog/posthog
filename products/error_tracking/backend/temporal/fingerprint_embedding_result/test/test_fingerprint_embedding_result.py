import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import (
    TargetFingerprintEmbeddingNotFoundError,
    _query_closest_fingerprints,
    _report_closest_fingerprint_metrics,
    _select_model_name,
    _target_embedding_query,
    merge_similar_fingerprints_activity,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.workflow import (
    ErrorTrackingFingerprintEmbeddingResultWorkflow,
)


def _inputs() -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=1,
        fingerprint="test-fingerprint",
        rendering="type_message_and_stack",
        timestamp="2026-06-08T00:00:00Z",
        model_names=["text-embedding-3-large-3072"],
    )


async def _run_workflow_with_mock_activity(
    inputs: FingerprintEmbeddingResultInputs,
    activity_result: FingerprintEmbeddingMergeResult,
) -> tuple[FingerprintEmbeddingMergeResult, FingerprintEmbeddingResultInputs]:
    captured: dict[str, FingerprintEmbeddingResultInputs] = {}

    @activity.defn(name="merge_similar_fingerprints_activity")
    async def mock_activity(activity_inputs: FingerprintEmbeddingResultInputs) -> FingerprintEmbeddingMergeResult:
        captured["inputs"] = activity_inputs
        return activity_result

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingFingerprintEmbeddingResultWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ErrorTrackingFingerprintEmbeddingResultWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return result, captured["inputs"]


class TestFingerprintEmbeddingResultActivity:
    def test_select_model_prefers_large_embedding_model(self) -> None:
        assert _select_model_name(["text-embedding-3-small-1536", "text-embedding-3-large-3072"]) == (
            "text-embedding-3-large-3072"
        )

    def test_target_embedding_query_uses_one_hour_timestamp_window(self) -> None:
        embedding_timestamp = datetime(2026, 6, 8, tzinfo=UTC)

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.parse_select"
        ) as parse_select:
            _target_embedding_query(_inputs(), "text-embedding-3-large-3072", embedding_timestamp)

        placeholders = parse_select.call_args.kwargs["placeholders"]
        assert placeholders["min_timestamp"].value == embedding_timestamp - timedelta(hours=1)
        assert placeholders["max_timestamp"].value == embedding_timestamp + timedelta(hours=1)

    def test_query_closest_fingerprints_returns_distances(self) -> None:
        target_response = MagicMock(results=[[[0.1, 0.2, 0.3]]])
        closest_response = MagicMock(
            results=[["fingerprint-1", 0.01], ["fingerprint-2", 0.02], ["fingerprint-3", 0.03]]
        )
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            side_effect=[target_response, closest_response],
        ) as execute_hogql_query:
            result = _query_closest_fingerprints(team, _inputs(), "text-embedding-3-large-3072")

        assert result == [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]
        assert execute_hogql_query.call_count == 2
        assert execute_hogql_query.call_args_list[0].kwargs["team"] == team
        assert execute_hogql_query.call_args_list[0].kwargs["query_type"] == (
            "ErrorTrackingFingerprintEmbeddingResultTargetEmbedding"
        )
        assert execute_hogql_query.call_args_list[1].kwargs["team"] == team
        assert execute_hogql_query.call_args_list[1].kwargs["query_type"] == (
            "ErrorTrackingFingerprintEmbeddingResultClosestFingerprints"
        )

    def test_query_closest_fingerprints_raises_without_target_embedding(self) -> None:
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            return_value=MagicMock(results=[]),
        ) as execute_hogql_query:
            with pytest.raises(TargetFingerprintEmbeddingNotFoundError, match="Target embedding not found"):
                _query_closest_fingerprints(team, _inputs(), "text-embedding-3-large-3072")

        execute_hogql_query.assert_called_once()

    def test_query_closest_fingerprints_raises_with_invalid_target_embedding(self) -> None:
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            return_value=MagicMock(results=[[None]]),
        ):
            with pytest.raises(TargetFingerprintEmbeddingNotFoundError, match="Target embedding is invalid"):
                _query_closest_fingerprints(team, _inputs(), "text-embedding-3-large-3072")

    def test_report_closest_fingerprint_metrics_includes_fingerprints(self) -> None:
        team = MagicMock(uuid=uuid.uuid4())
        closest_fingerprints = [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]
        capture = MagicMock()
        capture_context = MagicMock()
        capture_context.__enter__.return_value = capture

        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_scoped_capture",
                return_value=capture_context,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.groups",
                return_value={"team": "test"},
            ),
        ):
            _report_closest_fingerprint_metrics(
                team=team,
                inputs=_inputs(),
                closest_fingerprints=closest_fingerprints,
                model_name="text-embedding-3-large-3072",
                query_duration_ms=12.3,
            )

        properties = capture.call_args.kwargs["properties"]
        assert properties["fingerprint"] == "test-fingerprint"
        assert "closest_fingerprints" not in properties
        assert properties["rank_1_fingerprint"] == "fingerprint-1"
        assert properties["rank_1_distance"] == 0.01
        assert properties["rank_2_fingerprint"] == "fingerprint-2"
        assert properties["rank_3_fingerprint"] == "fingerprint-3"

    @pytest.mark.asyncio
    async def test_merge_activity_reports_distances(self) -> None:
        closest_fingerprints = [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]

        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.Team.objects.aget",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._query_closest_fingerprints",
                return_value=closest_fingerprints,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._report_closest_fingerprint_metrics"
            ),
        ):
            result = await merge_similar_fingerprints_activity(_inputs())

        assert result.merged_count == 0
        assert result.query_duration_ms is not None
        assert result.closest_fingerprints == closest_fingerprints


class TestFingerprintEmbeddingResultWorkflow:
    def test_parse_inputs_requires_payload(self) -> None:
        with pytest.raises(ValueError, match="requires exactly one input"):
            ErrorTrackingFingerprintEmbeddingResultWorkflow.parse_inputs([])

    def test_parse_inputs_rejects_multiple_payloads(self) -> None:
        with pytest.raises(ValueError, match="requires exactly one input"):
            ErrorTrackingFingerprintEmbeddingResultWorkflow.parse_inputs(["{}", "{}"])

    def test_parse_inputs(self) -> None:
        inputs = ErrorTrackingFingerprintEmbeddingResultWorkflow.parse_inputs(
            [
                json.dumps(
                    {
                        "team_id": 1,
                        "fingerprint": "test-fingerprint",
                        "rendering": "type_message_and_stack",
                        "timestamp": "2026-06-08T00:00:00Z",
                        "model_names": ["text-embedding-3-large-3072"],
                    }
                )
            ]
        )

        assert inputs == _inputs()

    def test_workflow_id_for_is_stable_and_bounded(self) -> None:
        workflow_id = ErrorTrackingFingerprintEmbeddingResultWorkflow.workflow_id_for(
            team_id=1,
            fingerprint="test-fingerprint",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
        )

        assert workflow_id == ErrorTrackingFingerprintEmbeddingResultWorkflow.workflow_id_for(
            team_id=1,
            fingerprint="test-fingerprint",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
        )
        assert workflow_id.startswith("error-tracking-fingerprint-embedding-result-1-")
        assert len(workflow_id) < 100

    @pytest.mark.asyncio
    async def test_workflow_calls_merge_activity(self) -> None:
        inputs = _inputs()
        expected = FingerprintEmbeddingMergeResult(merged_count=2)

        result, activity_inputs = await _run_workflow_with_mock_activity(inputs, expected)

        assert result == expected
        assert activity_inputs == inputs
