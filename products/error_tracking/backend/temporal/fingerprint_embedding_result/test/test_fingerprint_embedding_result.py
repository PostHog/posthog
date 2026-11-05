import uuid
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import override_settings

import httpx
from anthropic import APIConnectionError
from parameterized import parameterized
from temporalio.exceptions import CancelledError

from posthog.clickhouse.client.connection import ClickHouseUser, Workload
from posthog.models import Team

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueMergeOutcome,
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
)
from products.error_tracking.backend.temporal.fingerprint_embedding_result.types import (
    AutoMergeOutcome,
    FingerprintEmbeddingMergeResult,
    FingerprintEmbeddingResultInputs,
    SimilarFingerprintDistance,
)
from products.error_tracking.backend.temporal.grouping_judge.config import JudgeConfig
from products.error_tracking.backend.temporal.lifecycle.issue_created.activities import (
    merge_issue_created_fingerprint_activity,
)

JUDGE_MODULE = "products.error_tracking.backend.temporal.grouping_judge.inline"


def _inputs() -> FingerprintEmbeddingResultInputs:
    return FingerprintEmbeddingResultInputs(
        team_id=1,
        fingerprint="test-fingerprint",
        rendering="type_message_and_stack",
        timestamp="2026-06-08T00:00:00Z",
        model_name="text-embedding-3-large-3072",
        embedding=[0.1, 0.2, 0.3],
    )


class TestFingerprintEmbeddingResultActivity:
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
        closest_response = MagicMock(
            results=[["fingerprint-1", 0.01], ["fingerprint-2", 0.02], ["fingerprint-3", 0.03]]
        )
        team = MagicMock()

        with patch(
            "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.execute_hogql_query",
            return_value=closest_response,
        ) as execute_hogql_query:
            result = _query_closest_fingerprints(team, _inputs(), "text-embedding-3-large-3072")

        assert result == [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]
        execute_hogql_query.assert_called_once()
        assert execute_hogql_query.call_args.kwargs["team"] == team
        assert execute_hogql_query.call_args.kwargs["query_type"] == (
            "ErrorTrackingFingerprintEmbeddingResultClosestFingerprints"
        )
        assert execute_hogql_query.call_args.kwargs["workload"] == Workload.OFFLINE
        assert execute_hogql_query.call_args.kwargs["ch_user"] == ClickHouseUser.ERROR_TRACKING

    def test_target_embedding_from_inputs_rejects_invalid_embedding(self) -> None:
        inputs = FingerprintEmbeddingResultInputs(
            team_id=1,
            fingerprint="test-fingerprint",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_name="text-embedding-3-large-3072",
            embedding=cast(list[float], ["invalid"]),
        )

        with pytest.raises(TargetFingerprintEmbeddingNotFoundError, match="non-numeric"):
            _target_embedding_from_inputs(inputs)

    def test_report_closest_fingerprint_metrics_includes_fingerprints(self) -> None:
        team = MagicMock(uuid=uuid.uuid4())
        closest_fingerprints = [
            SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01),
            SimilarFingerprintDistance(fingerprint="fingerprint-2", distance=0.02),
            SimilarFingerprintDistance(fingerprint="fingerprint-3", distance=0.03),
        ]
        capture = MagicMock()

        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=capture,
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
                judge_properties={"live_decision": "merge"},
            )

        properties = capture.call_args.kwargs["properties"]
        assert properties["fingerprint"] == "test-fingerprint"
        assert "closest_fingerprints" not in properties
        assert properties["rank_1_fingerprint"] == "fingerprint-1"
        assert properties["rank_1_distance"] == 0.01
        assert properties["rank_2_fingerprint"] == "fingerprint-2"
        assert properties["rank_3_fingerprint"] == "fingerprint-3"
        assert properties["live_decision"] == "merge"

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
            result = merge_issue_created_fingerprint_activity(_inputs())

        assert result.merged_count == 0
        assert result.query_duration_ms is not None
        assert result.closest_fingerprints == closest_fingerprints

    def test_merge_activity_returns_empty_result_when_team_deleted(self) -> None:
        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.Team.objects.get",
                side_effect=Team.DoesNotExist(),
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._capture_activity_exception"
            ) as capture_exception,
        ):
            result = merge_issue_created_fingerprint_activity(_inputs())

        assert result == FingerprintEmbeddingMergeResult()
        capture_exception.assert_not_called()

    @pytest.mark.parametrize(
        "error,expect_captured",
        [
            # A drain cancels the activity, and Temporal retries it on a fresh worker.
            (CancelledError("Cancelled"), False),
            (OperationalError("server closed the connection unexpectedly"), False),
            (ValueError("boom"), True),
        ],
    )
    def test_merge_activity_captures_only_genuine_failures(self, error: Exception, expect_captured: bool) -> None:
        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.Team.objects.get",
                return_value=MagicMock(),
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._query_closest_fingerprints",
                side_effect=error,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._capture_activity_exception"
            ) as capture_activity_exception,
            pytest.raises(type(error)),
        ):
            merge_issue_created_fingerprint_activity(_inputs())

        assert capture_activity_exception.called is expect_captured

    def test_merge_activity_reports_an_error_decision_and_reraises_when_the_merge_raises(self) -> None:
        error = StaleAutoMergeStateError("ownership changed")
        capture = MagicMock()

        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.Team.objects.get",
                return_value=MagicMock(id=1, uuid=uuid.uuid4()),
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._query_closest_fingerprints",
                return_value=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01)],
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._merge_fingerprint_into_closest_issue",
                side_effect=error,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=capture,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.groups",
                return_value={},
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._capture_activity_exception"
            ),
            pytest.raises(StaleAutoMergeStateError) as raised,
        ):
            merge_issue_created_fingerprint_activity(_inputs())

        assert raised.value is error
        (call,) = capture.call_args_list
        assert call.kwargs["event"] == "error_tracking_fingerprint_embedding_result_metrics"
        assert call.kwargs["properties"]["live_decision"] == "error"
        assert call.kwargs["properties"]["live_target_fingerprint"] is None

    def test_merge_fingerprint_skips_when_auto_merge_disabled(self) -> None:
        with override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=False):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=1),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.01)],
            )

        assert result.merged_count == 0

    def test_merge_fingerprint_skips_distances_above_threshold(self) -> None:
        with override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.019)],
            )

        assert result.merged_count == 0

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
        target_issue.merge.return_value = ErrorTrackingIssueMergeOutcome(ErrorTrackingIssueMergeResult.MERGED)
        target_fingerprint = MagicMock(issue_id=target_issue_id, issue=target_issue, fingerprint="fingerprint-1")
        team = MagicMock(id=2, uuid=uuid.uuid4())
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            target_fingerprint,
            source_fingerprint,
        ]
        capture = MagicMock()

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ) as filter_fingerprints,
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=capture,
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

        assert result.merged_count == 1
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

    def test_merge_fingerprint_skips_missing_and_same_issue_candidates(self) -> None:
        source_issue_id = uuid.uuid4()
        target_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=source_issue_id, fingerprint="test-fingerprint")
        same_issue_fingerprint = MagicMock(issue_id=source_issue_id, fingerprint="same-issue")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeOutcome(ErrorTrackingIssueMergeResult.MERGED)
        target_fingerprint = MagicMock(issue_id=target_issue_id, issue=target_issue, fingerprint="valid-target")
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            source_fingerprint,
            same_issue_fingerprint,
            target_fingerprint,
        ]
        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=MagicMock(),
            ),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2, uuid=uuid.uuid4()),
                fingerprint="test-fingerprint",
                closest_fingerprints=[
                    SimilarFingerprintDistance(fingerprint="missing", distance=0.01),
                    SimilarFingerprintDistance(fingerprint="same-issue", distance=0.011),
                    SimilarFingerprintDistance(fingerprint="valid-target", distance=0.012),
                ],
            )

        assert result.merged_count == 1
        target_issue.merge.assert_called_once_with(
            issue_ids=[source_issue_id],
            expected_fingerprint_issue_ids={
                "test-fingerprint": source_issue_id,
                "valid-target": target_issue_id,
            },
        )

    def test_merge_fingerprint_retry_keeps_merged_outcome(self) -> None:
        original_issue_id = uuid.uuid4()
        merged_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=merged_issue_id, fingerprint="test-fingerprint")
        target_fingerprint = MagicMock(issue_id=merged_issue_id, fingerprint="fingerprint-1")
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            target_fingerprint,
            source_fingerprint,
        ]
        original_issue_query = MagicMock()
        original_issue_query.exists.return_value = False

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssue.objects.filter",
                return_value=original_issue_query,
            ),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.018)],
                expected_source_issue_id=str(original_issue_id),
            )

        assert result.merged_count == 1

    def test_merge_fingerprint_ownership_change_keeps_unmerged_outcome(self) -> None:
        original_issue_id = uuid.uuid4()
        reassigned_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=reassigned_issue_id, fingerprint="test-fingerprint")
        target_fingerprint = MagicMock(issue_id=uuid.uuid4(), fingerprint="fingerprint-1")
        fingerprint_query = MagicMock()
        fingerprint_query.select_related.return_value.order_by.return_value = [
            target_fingerprint,
            source_fingerprint,
        ]
        original_issue_query = MagicMock()
        original_issue_query.exists.return_value = True

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssueFingerprintV2.objects.filter",
                return_value=fingerprint_query,
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ErrorTrackingIssue.objects.filter",
                return_value=original_issue_query,
            ),
        ):
            result = _merge_fingerprint_into_closest_issue(
                team=MagicMock(id=2),
                fingerprint="test-fingerprint",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fingerprint-1", distance=0.018)],
                expected_source_issue_id=str(original_issue_id),
            )

        assert result.merged_count == 0

    def test_merge_fingerprint_retries_when_merge_state_is_stale(self) -> None:
        source_issue_id = uuid.uuid4()
        target_issue_id = uuid.uuid4()
        source_fingerprint = MagicMock(issue_id=source_issue_id, fingerprint="test-fingerprint")
        target_issue = MagicMock()
        target_issue.merge.return_value = ErrorTrackingIssueMergeOutcome(
            ErrorTrackingIssueMergeResult.STALE_FINGERPRINTS
        )
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

        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=MagicMock(),
            ),
        ):
            outcome = _merge_fingerprint_into_closest_issue(
                team=self.team,
                fingerprint="fp-source",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fp-target", distance=0.01)],
            )

        assert outcome.merged_count == 1

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


class TestAutoMergeReopensTarget(BaseTest):
    def _create_issue(self, fingerprint: str, status: str) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError", status=status)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def _merge(self, event_reference: str = "event-1") -> AutoMergeOutcome:
        with (
            override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=MagicMock(),
            ),
        ):
            return _merge_fingerprint_into_closest_issue(
                team=self.team,
                fingerprint="fp-source",
                closest_fingerprints=[SimilarFingerprintDistance(fingerprint="fp-target", distance=0.01)],
                event_reference=event_reference,
            )

    def test_auto_merge_into_resolved_target_reports_the_reopen(self) -> None:
        self._create_issue("fp-source", "active")
        target = self._create_issue("fp-target", "resolved")
        ErrorTrackingIssueAssignment.objects.create(issue=target, user=self.user)

        outcome = self._merge()

        target.refresh_from_db()
        assert target.status == "active"
        assert outcome.reopened_target is not None
        assert outcome.reopened_target.issue_id == str(target.id)
        # The notification carries the target's state after the reopen, so subscribers
        # do not read it as still resolved.
        assert outcome.reopened_target.issue.status == "active"
        assert outcome.reopened_target.issue.name == "TypeError"
        assert outcome.reopened_target.assignee == f'{{"type":"user","id":{self.user.id}}}'
        assert outcome.reopened_target.notification_id == str(
            uuid.uuid5(uuid.NAMESPACE_OID, f"issue_reopened:{self.team.id}:{target.id}:event-1")
        )

    def test_auto_merge_into_active_target_reports_no_reopen(self) -> None:
        self._create_issue("fp-source", "active")
        self._create_issue("fp-target", "active")

        outcome = self._merge()

        assert outcome.merged_count == 1
        assert outcome.reopened_target is None

    def test_auto_merge_reports_the_reopen_when_the_clickhouse_sync_fails(self) -> None:
        self._create_issue("fp-source", "active")
        target = self._create_issue("fp-target", "resolved")

        # A failed sync after the commit must not fail the activity. A retry would find the
        # source gone, report a plain merge and never send the reopened alert.
        with (
            patch(
                "products.error_tracking.backend.models.sync_issues_to_clickhouse",
                side_effect=Exception("clickhouse sync failed"),
            ),
            patch(
                "products.error_tracking.backend.models.update_error_tracking_issue_fingerprint_overrides",
                side_effect=Exception("fingerprint override sync failed"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            outcome = self._merge()

        target.refresh_from_db()
        assert target.status == "active"
        assert outcome.merged_count == 1
        assert outcome.reopened_target is not None
        assert outcome.reopened_target.issue_id == str(target.id)


@override_settings(ERROR_TRACKING_AUTO_MERGE_ENABLED=True)
class TestGroupingJudgeNeverChangesTheMerge(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        for fingerprint in ("fp-source", "fp-target"):
            issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        self.target_issue_id = ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fp-target").issue_id

    def _run(self, client: MagicMock | None = None, build_error: Exception | None = None) -> tuple[Any, list[Any]]:
        inputs = FingerprintEmbeddingResultInputs(
            team_id=self.team.id,
            fingerprint="fp-source",
            rendering="type_message_and_stack",
            timestamp="2026-06-08T00:00:00Z",
            model_name="text-embedding-3-large-3072",
            embedding=[0.1],
        )
        texts = MagicMock(results=[("fp-source", "TypeError: a"), ("fp-target", "TypeError: b")])
        capture = MagicMock()
        with (
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities._query_closest_fingerprints",
                return_value=[SimilarFingerprintDistance(fingerprint="fp-target", distance=0.01)],
            ),
            patch(
                "products.error_tracking.backend.temporal.fingerprint_embedding_result.activities.ph_background_capture",
                return_value=capture,
            ),
            patch(f"{JUDGE_MODULE}.execute_hogql_query", return_value=texts),
            patch(f"{JUDGE_MODULE}.build_ai_gateway_anthropic_client", return_value=client, side_effect=build_error),
            patch(f"{JUDGE_MODULE}.TOTAL_BUDGET_SECONDS", 0.5),
            patch(f"{JUDGE_MODULE}.current_judge_config", return_value=JudgeConfig(sample_rate=1.0)),
        ):
            result = merge_issue_created_fingerprint_activity(inputs)
        events = [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs["event"] == "error_tracking_fingerprint_embedding_result_metrics"
        ]
        return result, events

    @parameterized.expand(
        [
            ("judged", "judged"),
            ("judge_raises", "unavailable"),
            ("gateway_not_configured", "unavailable"),
            ("gateway_down", "unavailable"),
            ("judge_hangs", "timeout"),
            ("worker_drains_during_the_judge", "cancelled"),
        ]
    )
    def test_merge_and_event_survive_any_judge_failure(self, case: str, outcome: str) -> None:
        release = threading.Event()
        client = MagicMock()
        create = client.with_options.return_value.messages.create
        build_error: Exception | None = None
        if case == "judged":
            create.return_value = SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", name="record_verdict", input={"same_issue": True})]
            )
        elif case == "judge_raises":
            build_error = RuntimeError("judge bug")
        elif case == "gateway_not_configured":
            build_error = ValueError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")
        elif case == "gateway_down":
            create.side_effect = APIConnectionError(request=httpx.Request("POST", "http://gateway.example.com"))
        elif case == "worker_drains_during_the_judge":
            create.side_effect = CancelledError("Cancelled")
        else:
            create.side_effect = lambda **_: release.wait(timeout=5)

        try:
            result, events = self._run(client, build_error)
        finally:
            release.set()

        assert (result.merged_count, result.reopened_target, result.closest_fingerprints) == (
            1,
            None,
            [SimilarFingerprintDistance(fingerprint="fp-target", distance=0.01)],
        )
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fp-source").issue_id == self.target_issue_id
        (event,) = events
        assert (
            event["live_decision"],
            event["live_target_fingerprint"],
            event["live_merge_decision"],
            event["judge_outcome"],
        ) == ("merge", "fp-target", "distance", outcome)

    def test_merge_and_event_survive_a_failure_outside_the_judge_call(self) -> None:
        with patch(f"{JUDGE_MODULE}.band_for", side_effect=RuntimeError("judge bug")):
            result, events = self._run()

        assert result.merged_count == 1
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fp-source").issue_id == self.target_issue_id
        assert [event["live_decision"] for event in events] == ["merge"]
