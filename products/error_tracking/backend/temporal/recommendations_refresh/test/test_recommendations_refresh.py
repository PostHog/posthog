import uuid
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.utils import timezone

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.temporal.recommendations_refresh.activities import (
    get_teams_with_recent_exceptions_activity,
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

_CLOSE_CONNECTIONS = "products.error_tracking.backend.temporal.recommendations_refresh.activities.close_old_connections"
_ALERTS_COMPUTE = "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute"
_LONG_RUNNING_COMPUTE = (
    "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute"
)
_SOURCE_MAPS_COMPUTE = "products.error_tracking.backend.recommendations.source_maps.SourceMapsRecommendation.compute"

_ALERTS_META = {"alerts": [{"key": "error-tracking-issue-created", "enabled": False}]}
_LONG_RUNNING_META: dict = {"issues": []}
_SOURCE_MAPS_META = {"total_frames": 0, "unresolved_frames": 0, "unresolved_pct": 0.0}


class TestGetTeamsWithRecentExceptionsActivity(ClickhouseTestMixin, APIBaseTest):
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

        team_ids = get_teams_with_recent_exceptions_activity(RecommendationsRefreshInputs(lookback_days=7))

        assert self.team.id in team_ids
        assert team_pageview_only.id not in team_ids
        assert team_old_exception.id not in team_ids


class TestRefreshRecommendationsBatchActivity(BaseTest):
    @patch(_SOURCE_MAPS_COMPUTE, return_value=_SOURCE_MAPS_META)
    @patch(_LONG_RUNNING_COMPUTE, return_value=_LONG_RUNNING_META)
    @patch(_ALERTS_COMPUTE, return_value=_ALERTS_META)
    @patch(_CLOSE_CONNECTIONS)
    def test_computes_recommendations_inline_for_all_teams(self, _close, _alerts, _long, _source):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        result = refresh_recommendations_batch_activity(RefreshBatchInputs(team_ids=[self.team.id, team_b.id]))

        assert result.teams_processed == 2
        assert result.recommendations_kicked == 6
        for team_id in (self.team.id, team_b.id):
            recs = ErrorTrackingRecommendation.objects.filter(team_id=team_id)
            assert recs.count() == 3
            for rec in recs:
                assert rec.status == ErrorTrackingRecommendation.Status.READY
                assert rec.computed_at is not None

    @patch(_SOURCE_MAPS_COMPUTE, return_value=_SOURCE_MAPS_META)
    @patch(_LONG_RUNNING_COMPUTE, return_value=_LONG_RUNNING_META)
    @patch(_ALERTS_COMPUTE, return_value=_ALERTS_META)
    @patch(_CLOSE_CONNECTIONS)
    def test_rerun_only_recomputes_stale_recommendations(self, _close, _alerts, _long, _source):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        batch = RefreshBatchInputs(team_ids=[self.team.id, team_b.id])

        first = refresh_recommendations_batch_activity(batch)
        assert first.recommendations_kicked == 6

        second = refresh_recommendations_batch_activity(batch)
        # Only `alerts` has no refresh_interval, so it recomputes for both teams; long_running_issues
        # (1h) and source_maps (6h) are still fresh and are skipped.
        assert second.recommendations_kicked == 2


async def _run_refresh_workflow(
    inputs: RecommendationsRefreshInputs | None, team_ids: list[int]
) -> tuple[RecommendationsRefreshResult, list[list[int]]]:
    captured_batches: list[list[int]] = []

    @activity.defn(name="get_teams_with_recent_exceptions_activity")
    async def mock_enumerate(activity_inputs: RecommendationsRefreshInputs) -> list[int]:
        return team_ids

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
    async def test_fans_out_into_batches_and_aggregates(self):
        inputs = RecommendationsRefreshInputs(batch_size=100, max_concurrent_batches=10)
        team_ids = list(range(1, 251))

        result, batches = await _run_refresh_workflow(inputs, team_ids)

        assert result.teams_total == 250
        assert result.recommendations_kicked == 250
        assert result.batches_failed == 0
        assert len(batches) == 3
        assert sorted(len(b) for b in batches) == [50, 100, 100]
        assert sorted(team for batch in batches for team in batch) == team_ids

    @pytest.mark.asyncio
    async def test_no_eligible_teams_skips_batch_activity(self):
        result, batches = await _run_refresh_workflow(RecommendationsRefreshInputs(), [])

        assert result == RecommendationsRefreshResult(teams_total=0, recommendations_kicked=0, batches_failed=0)
        assert batches == []
