import uuid
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from temporalio import activity
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team

from products.error_tracking.backend.logic.recommendations.long_running_issues import LongRunningIssuesRecommendation
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRecommendation,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.sql import TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL
from products.error_tracking.backend.temporal.recommendations_refresh.activities import (
    get_team_batches_activity,
    pack_team_batches,
    refresh_recommendations_batch_activity,
)
from products.error_tracking.backend.temporal.recommendations_refresh.types import (
    RecommendationsRefreshInputs,
    RecommendationsRefreshResult,
    RefreshBatchInputs,
    RefreshBatchResult,
)
from products.error_tracking.backend.temporal.recommendations_refresh.workflow import (
    ErrorTrackingRecommendationsRefreshWorkflow,
)

_ALERTS_COMPUTE_BATCH = (
    "products.error_tracking.backend.logic.recommendations.alerts.AlertsRecommendation.compute_batch"
)
_LONG_RUNNING_COMPUTE_BATCH = "products.error_tracking.backend.logic.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute_batch"
_SOURCE_MAPS_COMPUTE_BATCH = (
    "products.error_tracking.backend.logic.recommendations.source_maps.SourceMapsRecommendation.compute_batch"
)
_RATE_LIMITS_COMPUTE_BATCH = (
    "products.error_tracking.backend.logic.recommendations.rate_limits.RateLimitsRecommendation.compute_batch"
)

_ALERTS_META = {"alerts": [{"key": "error-tracking-issue-created", "enabled": False}]}
_LONG_RUNNING_META: dict = {"issues": []}
_SOURCE_MAPS_META = {"total_frames": 0, "unresolved_frames": 0, "unresolved_pct": 0.0}
_RATE_LIMITS_META = {"rate_limits": [{"key": "project", "enabled": False}, {"key": "per_issue", "enabled": False}]}


def _batch_meta(meta: dict):
    return lambda team_ids: dict.fromkeys(team_ids, meta)


def _run_batch_activity(inputs: RefreshBatchInputs) -> RefreshBatchResult:
    return ActivityEnvironment().run(refresh_recommendations_batch_activity, inputs)


class TestGetTeamBatchesActivity(ClickhouseTestMixin, APIBaseTest):
    def test_returns_only_teams_with_recent_exceptions(self):
        team_pageview_only = Team.objects.create(organization=self.organization, name="Pageviews")
        team_old_exception = Team.objects.create(organization=self.organization, name="Old")

        _create_event(distinct_id="u1", event="$exception", team=self.team, timestamp=timezone.now().isoformat())
        _create_event(
            distinct_id="u2", event="$pageview", team=team_pageview_only, timestamp=timezone.now().isoformat()
        )
        _create_event(
            distinct_id="u3",
            event="$exception",
            team=team_old_exception,
            timestamp=(timezone.now() - timedelta(days=10)).isoformat(),
        )
        flush_persons_and_events()

        batches = get_team_batches_activity(RecommendationsRefreshInputs(lookback_days=7))

        all_team_ids = [team_id for batch in batches for team_id in batch]
        assert self.team.id in all_team_ids
        assert team_pageview_only.id not in all_team_ids
        assert team_old_exception.id not in all_team_ids


class TestPackTeamBatches:
    @parameterized.expand(
        [
            ("all_fit_in_one_batch", [(1, 10), (2, 10)], 5, 100, [[1, 2]]),
            ("team_cap_closes_batch", [(1, 1), (2, 1), (3, 1)], 2, 100, [[1, 2], [3]]),
            ("volume_cap_closes_batch", [(1, 60), (2, 50), (3, 10)], 5, 100, [[1], [2, 3]]),
            ("oversized_team_gets_own_batch", [(1, 500), (2, 10), (3, 10)], 5, 100, [[1], [2, 3]]),
            ("empty_input", [], 5, 100, []),
        ]
    )
    def test_packing(self, _name, teams_with_counts, max_teams, max_events, expected):
        assert pack_team_batches(teams_with_counts, max_teams=max_teams, max_events=max_events) == expected


class TestRefreshRecommendationsBatchActivity(APIBaseTest):
    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=_batch_meta(_ALERTS_META))
    def test_computes_recommendations_for_all_teams(self, _alerts, _long, _source, _rate_limits):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        result = _run_batch_activity(RefreshBatchInputs(team_ids=[self.team.id, team_b.id]))

        assert result.teams_processed == 2
        assert result.recommendations_kicked == 8
        for team_id in (self.team.id, team_b.id):
            recs = ErrorTrackingRecommendation.objects.filter(team_id=team_id)
            assert recs.count() == 4
            for rec in recs:
                assert rec.status == ErrorTrackingRecommendation.Status.READY
                assert rec.computed_at is not None

    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=_batch_meta(_ALERTS_META))
    def test_rerun_only_recomputes_stale_recommendations(self, _alerts, _long, _source, _rate_limits):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        batch = RefreshBatchInputs(team_ids=[self.team.id, team_b.id])

        first = _run_batch_activity(batch)
        assert first.recommendations_kicked == 8

        second = _run_batch_activity(batch)
        # `alerts` and `rate_limits` have no refresh_interval, so they recompute for both teams;
        # long_running_issues and source_maps (both 6h) are still fresh and are skipped.
        assert second.recommendations_kicked == 4

    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=Exception("boom"))
    def test_failing_recommendation_reverts_claims_and_spares_others(self, _alerts, _long, _source, _rate_limits):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        result = _run_batch_activity(RefreshBatchInputs(team_ids=[self.team.id, team_b.id]))

        assert result.recommendations_kicked == 6
        alerts_rows = ErrorTrackingRecommendation.objects.filter(type="alerts")
        assert alerts_rows.count() == 2
        for row in alerts_rows:
            assert row.status == ErrorTrackingRecommendation.Status.READY
            assert row.computed_at is None

    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=_batch_meta(_ALERTS_META))
    def test_skips_deleted_teams_without_failing_batch(self, _alerts, _long, _source, _rate_limits):
        # ClickHouse retains events for teams later deleted from Postgres; the batch must
        # process surviving teams and not blow up on the missing team_id foreign key.
        deleted_team = Team.objects.create(organization=self.organization, name="Doomed")
        deleted_team_id = deleted_team.id
        deleted_team.delete()

        result = _run_batch_activity(RefreshBatchInputs(team_ids=[self.team.id, deleted_team_id]))

        # teams_processed reflects only the surviving team, not the raw input count.
        assert result.teams_processed == 1
        assert result.recommendations_kicked == 4
        assert ErrorTrackingRecommendation.objects.filter(team_id=self.team.id).count() == 4
        assert ErrorTrackingRecommendation.objects.filter(team_id=deleted_team_id).count() == 0

    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=_batch_meta(_ALERTS_META))
    def test_all_teams_deleted_kicks_nothing(self, _alerts, _long, _source, _rate_limits):
        deleted_team = Team.objects.create(organization=self.organization, name="Doomed")
        deleted_team_id = deleted_team.id
        deleted_team.delete()

        result = _run_batch_activity(RefreshBatchInputs(team_ids=[deleted_team_id]))

        assert result.teams_processed == 0
        assert result.recommendations_kicked == 0
        assert ErrorTrackingRecommendation.objects.filter(team_id=deleted_team_id).count() == 0

    @patch(_RATE_LIMITS_COMPUTE_BATCH, side_effect=_batch_meta(_RATE_LIMITS_META))
    @patch(_SOURCE_MAPS_COMPUTE_BATCH, side_effect=_batch_meta(_SOURCE_MAPS_META))
    @patch(_LONG_RUNNING_COMPUTE_BATCH, side_effect=_batch_meta(_LONG_RUNNING_META))
    @patch(_ALERTS_COMPUTE_BATCH, side_effect=lambda team_ids: {})
    def test_missing_meta_reverts_claim(self, _alerts, _long, _source, _rate_limits):
        result = _run_batch_activity(RefreshBatchInputs(team_ids=[self.team.id]))

        assert result.recommendations_kicked == 3
        alerts_row = ErrorTrackingRecommendation.objects.get(team_id=self.team.id, type="alerts")
        assert alerts_row.status == ErrorTrackingRecommendation.Status.READY
        assert alerts_row.computed_at is None


class TestLongRunningIssuesComputeBatch(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        from posthog.clickhouse.client import sync_execute

        sync_execute(TRUNCATE_ERROR_TRACKING_FINGERPRINT_ISSUE_STATE_TABLE_SQL())

    def _create_issue_with_events(
        self, team: Team, fingerprint: str, first_seen, event_count: int, **issue_kwargs
    ) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team, **issue_kwargs)
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=fingerprint)
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=issue).update(first_seen=first_seen)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=team.id)

        for i in range(event_count):
            _create_event(
                distinct_id=f"u{i}",
                event="$exception",
                team=team,
                timestamp=timezone.now().isoformat(),
                properties={"$exception_fingerprint": fingerprint},
            )
        return issue

    def test_returns_long_running_issues_per_team(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        team_quiet = Team.objects.create(organization=self.organization, name="Quiet")

        old = timezone.now() - timedelta(days=30)
        long_running = self._create_issue_with_events(
            self.team, "fp_old", old, event_count=3, name="Old issue", description="Still firing"
        )
        # Recent issue: first_seen inside the 7 day window, so not long-running.
        self._create_issue_with_events(self.team, "fp_new", timezone.now(), event_count=2, name="New issue")
        # Resolved long-running issue on another team: excluded by status.
        self._create_issue_with_events(
            team_b, "fp_resolved", old, event_count=2, name="Done", status=ErrorTrackingIssue.Status.RESOLVED
        )
        flush_persons_and_events()

        metas = LongRunningIssuesRecommendation().compute_batch([self.team.id, team_b.id, team_quiet.id])

        assert set(metas.keys()) == {self.team.id, team_b.id, team_quiet.id}
        assert metas[team_b.id] == {"issues": []}
        assert metas[team_quiet.id] == {"issues": []}

        issues = metas[self.team.id]["issues"]
        assert len(issues) == 1
        assert issues[0]["id"] == str(long_running.id)
        assert issues[0]["name"] == "Old issue"
        assert issues[0]["description"] == "Still firing"
        assert issues[0]["occurrences"] == 3
        assert issues[0]["status"] == ErrorTrackingIssue.Status.ACTIVE

    def test_compute_delegates_to_batch(self):
        old = timezone.now() - timedelta(days=30)
        issue = self._create_issue_with_events(self.team, "fp_old", old, event_count=1, name="Old issue")
        flush_persons_and_events()

        meta = LongRunningIssuesRecommendation().compute(self.team)

        assert [i["id"] for i in meta["issues"]] == [str(issue.id)]


async def _run_refresh_workflow(
    inputs: RecommendationsRefreshInputs | None, team_batches: list[list[int]]
) -> tuple[RecommendationsRefreshResult, list[list[int]]]:
    captured_batches: list[list[int]] = []

    @activity.defn(name="get_team_batches_activity")
    async def mock_enumerate(activity_inputs: RecommendationsRefreshInputs) -> list[list[int]]:
        return team_batches

    @activity.defn(name="refresh_recommendations_batch_activity")
    async def mock_batch(batch_inputs: RefreshBatchInputs) -> RefreshBatchResult:
        captured_batches.append(list(batch_inputs.team_ids))
        return RefreshBatchResult(
            teams_processed=len(batch_inputs.team_ids),
            recommendations_kicked=len(batch_inputs.team_ids),
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ErrorTrackingRecommendationsRefreshWorkflow],
            activities=[mock_enumerate, mock_batch],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ErrorTrackingRecommendationsRefreshWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return result, captured_batches


class TestRecommendationsRefreshWorkflow:
    @pytest.mark.asyncio
    async def test_fans_out_batches_and_aggregates(self):
        team_batches = [[1, 2, 3], [4, 5], [6]]

        result, batches = await _run_refresh_workflow(RecommendationsRefreshInputs(), team_batches)

        assert result.teams_total == 6
        assert result.recommendations_kicked == 6
        assert result.batches_failed == 0
        assert sorted(batches) == sorted(team_batches)

    @pytest.mark.asyncio
    async def test_no_eligible_teams_skips_batch_activity(self):
        result, batches = await _run_refresh_workflow(RecommendationsRefreshInputs(), [])

        assert result == RecommendationsRefreshResult(teams_total=0, recommendations_kicked=0, batches_failed=0)
        assert batches == []
