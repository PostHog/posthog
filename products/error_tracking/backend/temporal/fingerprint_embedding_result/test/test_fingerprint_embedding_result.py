import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models import Team

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueMergeResult,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.activities import (
    FingerprintIssueNotFoundError,
    StaleAutoMergeStateError,
    TargetFingerprintEmbeddingNotFoundError,
    _closest_fingerprints_query,
    _merge_fingerprint_into_closest_issue,
    _model_specific_embeddings_table_name,
    _query_closest_fingerprints,
    _report_closest_fingerprint_metrics,
    _target_embedding_from_inputs,
    _target_embedding_query,
    merge_similar_fingerprints_activity,
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
    select_model_name,
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


def _inputs_with_embedding() -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=1,
        fingerprint="test-fingerprint",
        rendering="type_message_and_stack",
        timestamp="2026-06-08T00:00:00Z",
        model_name="text-embedding-3-large-3072",
        model_names=["text-embedding-3-large-3072"],
        embedding=[0.1, 0.2, 0.3],
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
        assert select_model_name(["text-embedding-3-small-1536", "text-embedding-3-large-3072"]) == (
            "text-embedding-3-large-3072"
        )

    def test_target_embedding_query_uses_one_hour_timestamp_window(self) -> None:
        embedding_timestamp = datetime(2026, 6, 8, tzinfo=UTC)

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.parse_select"
        ) as parse_select:
            _target_embedding_query(_inputs(), "text-embedding-3-large-3072", embedding_timestamp)

        query = parse_select.call_args.args[0]
        assert "FROM document_embeddings_text_embedding_3_large_3072" in query
        assert "model_name" not in query
        placeholders = parse_select.call_args.kwargs["placeholders"]
        assert placeholders["min_timestamp"].value == embedding_timestamp - timedelta(hours=1)
        assert placeholders["max_timestamp"].value == embedding_timestamp + timedelta(hours=1)

    def test_closest_fingerprints_query_uses_model_specific_table(self) -> None:
        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.parse_select"
        ) as parse_select:
            _closest_fingerprints_query(
                _inputs(),
                "text-embedding-3-large-3072",
                [0.1, 0.2, 0.3],
            )

        query = parse_select.call_args.args[0]
        assert "FROM document_embeddings_text_embedding_3_large_3072" in query
        assert "model_name" not in query
        assert "length(embedding)" not in query
        assert "timestamp >= {min_timestamp}" in query
        assert parse_select.call_args.kwargs["placeholders"]["min_timestamp"].value == datetime(2026, 5, 9, tzinfo=UTC)

    def test_model_specific_embeddings_table_name_rejects_unknown_model(self) -> None:
        with pytest.raises(ValueError, match="Invalid embedding model"):
            _model_specific_embeddings_table_name("unknown-model")

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
        assert execute_hogql_query.call_args_list[0].kwargs["ch_user"] == ClickHouseUser.ERROR_TRACKING
        assert execute_hogql_query.call_args_list[1].kwargs["team"] == team
        assert execute_hogql_query.call_args_list[1].kwargs["query_type"] == (
            "ErrorTrackingFingerprintEmbeddingResultClosestFingerprints"
        )
        assert execute_hogql_query.call_args_list[1].kwargs["ch_user"] == ClickHouseUser.ERROR_TRACKING

    def test_query_closest_fingerprints_uses_input_embedding(self) -> None:
        closest_response = MagicMock(
            results=[["fingerprint-1", 0.01], ["fingerprint-2", 0.02], ["fingerprint-3", 0.03]]
        )
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            return_value=closest_response,
        ) as execute_hogql_query:
            result = _query_closest_fingerprints(team, _inputs_with_embedding(), "text-embedding-3-large-3072")

        assert result == [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]
        execute_hogql_query.assert_called_once()
        assert execute_hogql_query.call_args.kwargs["query_type"] == (
            "ErrorTrackingFingerprintEmbeddingResultClosestFingerprints"
        )
        assert execute_hogql_query.call_args.kwargs["ch_user"] == ClickHouseUser.ERROR_TRACKING

    def test_target_embedding_from_inputs_rejects_invalid_embedding(self) -> None:
        inputs = FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="test-fingerprint",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_names=["text-embedding-3-large-3072"],
            embedding=cast(list[float], ["invalid"]),
        )

        with pytest.raises(TargetFingerprintEmbeddingNotFoundError, match="non-numeric"):
            _target_embedding_from_inputs(inputs, "text-embedding-3-large-3072")

    def test_query_closest_fingerprints_raises_without_target_embedding(self) -> None:
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            return_value=MagicMock(results=[]),
        ) as execute_hogql_query:
            with pytest.raises(TargetFingerprintEmbeddingNotFoundError, match="Target embedding not found"):
                _query_closest_fingerprints(team, _inputs(), "text-embedding-3-large-3072")

        execute_hogql_query.assert_called_once()
        assert execute_hogql_query.call_args.kwargs["ch_user"] == ClickHouseUser.ERROR_TRACKING

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

    def test_merge_activity_reports_distances(self) -> None:
        closest_fingerprints = [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]

        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.Team.objects.get",
                return_value=MagicMock(),
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._query_closest_fingerprints",
                return_value=closest_fingerprints,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._report_closest_fingerprint_metrics"
            ),
        ):
            result = merge_similar_fingerprints_activity(_inputs())

        assert result.merged_count == 0
        assert result.query_duration_ms is not None
        assert result.closest_fingerprints == closest_fingerprints

    def test_merge_fingerprint_skips_when_auto_merge_disabled(self) -> None:
        with override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=False):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=1),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01)],
            )

        assert result == 0

    def test_merge_fingerprint_skips_distances_above_threshold(self) -> None:
        with override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.019)],
            )

        assert result == 0

    def test_merge_fingerprint_raises_when_source_fingerprint_is_missing(self) -> None:
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = []

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ),
            pytest.raises(FingerprintIssueNotFoundError, match="Source fingerprint test-fingerprint not found"),
        ):
            _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.018)],
            )

    def test_merge_fingerprint_moves_source_fingerprint_to_closest_issue(self) -> None:
        source_issue_id = uuid.uuid4()
        target_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=source_issue_id, fingerprint="test-fingerprint")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeResult.MERGED
        target_fingerprint = MagicMock(issue_id=target_issue_id, issue=target_issue, fingerprint="fingerprint-1")
        team = MagicMock(id=2, uuid=uuid.uuid4())
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            target_fingerprint,
            source_fingerprint,
        ]
        capture = MagicMock()
        capture_context = MagicMock()
        capture_context.__enter__.return_value = capture

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ) as filter_fingerprints,
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_scoped_capture",
                return_value=capture_context,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.groups",
                return_value={"team": "test"},
            ),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=team,
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.018)],
            )

        assert result == 1
        assert filter_fingerprints.call_args.kwargs == {
            "team_id": 2,
            "fingerprint__in": ["test-fingerprint", "fingerprint-1"],
        }
        target_issue.merge.assert_called_once_with(
            issue_ids=[source_issue_id],
            expected_fingerprint_issue_ids={
                "test-fingerprint": source_issue_id,
                "fingerprint-1": target_issue_id,
            },
        )
        properties = capture.call_args.kwargs["properties"]
        assert properties["merge_source"] == "auto"
        assert properties["source_issue_id"] == str(source_issue_id)
        assert properties["target_issue_id"] == str(target_issue_id)

    def test_merge_fingerprint_retries_when_merge_state_is_stale(self) -> None:
        source_issue_id = uuid.uuid4()
        target_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=source_issue_id, fingerprint="test-fingerprint")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeResult.STALE_FINGERPRINTS
        target_fingerprint = MagicMock(issue_id=target_issue_id, issue=target_issue, fingerprint="fingerprint-1")
        team = MagicMock(id=2, uuid=uuid.uuid4())
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            target_fingerprint,
            source_fingerprint,
        ]

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ),
            pytest.raises(StaleAutoMergeStateError, match="Fingerprint issue ownership changed"),
        ):
            _merge_fingerprint_into_closest_issue(
                team=team,
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.018)],
            )


class TestMergeFingerprintCrossTeamIsolation(BaseTest):
    def _create_issue(self, team: Team, fingerprint: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fingerprint)
        return issue

    def test_merge_only_affects_requesting_team_when_fingerprints_collide_across_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        source_issue = self._create_issue(self.team, "fp-source")
        target_issue = self._create_issue(self.team, "fp-target")
        other_source_issue = self._create_issue(other_team, "fp-source")
        other_target_issue = self._create_issue(other_team, "fp-target")

        capture_context = MagicMock()
        capture_context.__enter__.return_value = MagicMock()

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_scoped_capture",
                return_value=capture_context,
            ),
        ):
            merged_count = _merge_fingerprint_into_closest_issue(
                team=self.team,
                fingerprint="fp-source",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fp-target", distance=0.01)],
            )

        assert merged_count == 1

        # requesting team: source issue merged into target, fingerprint repointed with bumped version
        assert not ErrorTrackingIssue.objects.filter(id=source_issue.id).exists()
        merged_fingerprint = ErrorTrackingIssueFingerprintV2.objects.get(team=self.team, fingerprint="fp-source")
        assert merged_fingerprint.issue_id == target_issue.id
        assert merged_fingerprint.version == 1

        # other team: same fingerprint strings remain completely untouched
        assert ErrorTrackingIssue.objects.filter(id=other_source_issue.id).exists()
        assert ErrorTrackingIssue.objects.filter(id=other_target_issue.id).exists()
        other_fingerprint = ErrorTrackingIssueFingerprintV2.objects.get(team=other_team, fingerprint="fp-source")
        assert other_fingerprint.issue_id == other_source_issue.id
        assert other_fingerprint.version == 0


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

    def test_parse_inputs_preserves_embedding_payload(self) -> None:
        inputs = ErrorTrackingFingerprintEmbeddingResultWorkflow.parse_inputs(
            [
                json.dumps(
                    {
                        "team_id": 1,
                        "fingerprint": "test-fingerprint",
                        "rendering": "type_message_and_stack",
                        "timestamp": "2026-06-08T00:00:00Z",
                        "model_name": "text-embedding-3-large-3072",
                        "model_names": ["text-embedding-3-large-3072"],
                        "embedding": [0.1, 0.2, 0.3],
                    }
                )
            ]
        )

        assert inputs == _inputs_with_embedding()

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
