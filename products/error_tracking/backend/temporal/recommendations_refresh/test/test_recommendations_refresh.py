import uuid
import asyncio
from datetime import timedelta

import pytest
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    NonAtomicBaseTest,
    _create_event,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.utils import timezone

from temporalio import activity
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Team

from products.error_tracking.backend.models import ErrorTrackingRecommendation
from products.error_tracking.backend.recommendations import RECOMMENDATIONS
from products.error_tracking.backend.recommendations.refresh import ensure_recommendation_row
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

_ALERTS_COMPUTE = "products.error_tracking.backend.recommendations.alerts.AlertsRecommendation.compute"
_LONG_RUNNING_COMPUTE = (
    "products.error_tracking.backend.recommendations.long_running_issues.LongRunningIssuesRecommendation.compute"
)
_SOURCE_MAPS_COMPUTE = "products.error_tracking.backend.recommendations.source_maps.SourceMapsRecommendation.compute"
_RATE_LIMITS_COMPUTE = "products.error_tracking.backend.recommendations.rate_limits.RateLimitsRecommendation.compute"

_ALERTS_META = {"alerts": [{"key": "error-tracking-issue-created", "enabled": False}]}
_LONG_RUNNING_META: dict = {"issues": []}
_SOURCE_MAPS_META = {"total_frames": 0, "unresolved_frames": 0, "unresolved_pct": 0.0}
_RATE_LIMITS_META = {"rate_limits": [{"key": "project", "enabled": False}, {"key": "per_issue", "enabled": False}]}


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

    def test_excludes_teams_deleted_from_postgres(self):
        # ClickHouse keeps $exception events for teams that were deleted from Postgres; those
        # team_ids must be dropped so we never attempt a recommendation row for a missing team.
        deleted_team_id = self.team.id + 10_000_000
        assert not Team.objects.filter(id=deleted_team_id).exists()

        _create_event(distinct_id="u1", event="$exception", team=self.team, timestamp=timezone.now().isoformat())
        _create_event(
            distinct_id="u2", event="$exception", team_id=deleted_team_id, timestamp=timezone.now().isoformat()
        )
        flush_persons_and_events()

        team_ids = get_teams_with_recent_exceptions_activity(RecommendationsRefreshInputs(lookback_days=7))

        assert self.team.id in team_ids
        assert deleted_team_id not in team_ids


class TestRefreshRecommendationsBatchActivity(NonAtomicBaseTest):
    # Inline compute fans out over the shared thread pool, each thread with its own DB
    # connection, so the data must be committed (not wrapped in TestCase's atomic block).
    CLASS_DATA_LEVEL_SETUP = False

    @patch(_RATE_LIMITS_COMPUTE, return_value=_RATE_LIMITS_META)
    @patch(_SOURCE_MAPS_COMPUTE, return_value=_SOURCE_MAPS_META)
    @patch(_LONG_RUNNING_COMPUTE, return_value=_LONG_RUNNING_META)
    @patch(_ALERTS_COMPUTE, return_value=_ALERTS_META)
    def test_computes_recommendations_inline_for_all_teams(self, _alerts, _long, _source, _rate_limits):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        result = asyncio.run(
            ActivityEnvironment().run(
                refresh_recommendations_batch_activity, RefreshBatchInputs(team_ids=[self.team.id, team_b.id])
            )
        )

        assert result.teams_processed == 2
        assert result.recommendations_kicked == 8
        for team_id in (self.team.id, team_b.id):
            recs = ErrorTrackingRecommendation.objects.filter(team_id=team_id)
            assert recs.count() == 4
            for rec in recs:
                assert rec.status == ErrorTrackingRecommendation.Status.READY
                assert rec.computed_at is not None

    @patch(_RATE_LIMITS_COMPUTE, return_value=_RATE_LIMITS_META)
    @patch(_SOURCE_MAPS_COMPUTE, return_value=_SOURCE_MAPS_META)
    @patch(_LONG_RUNNING_COMPUTE, return_value=_LONG_RUNNING_META)
    @patch(_ALERTS_COMPUTE, return_value=_ALERTS_META)
    def test_rerun_only_recomputes_stale_recommendations(self, _alerts, _long, _source, _rate_limits):
        team_b = Team.objects.create(organization=self.organization, name="Team B")
        batch = RefreshBatchInputs(team_ids=[self.team.id, team_b.id])

        first = asyncio.run(ActivityEnvironment().run(refresh_recommendations_batch_activity, batch))
        assert first.recommendations_kicked == 8

        second = asyncio.run(ActivityEnvironment().run(refresh_recommendations_batch_activity, batch))
        # `alerts` and `rate_limits` have no refresh_interval, so they recompute for both teams;
        # long_running_issues and source_maps (both 6h) are still fresh and are skipped.
        assert second.recommendations_kicked == 4


class TestEnsureRecommendationRow(NonAtomicBaseTest):
    # Triggers a real foreign-key violation, which aborts the transaction, so data must be
    # committed rather than wrapped in TestCase's atomic block.
    CLASS_DATA_LEVEL_SETUP = False

    def test_creates_row_for_existing_team(self):
        rec = RECOMMENDATIONS[0]

        obj = ensure_recommendation_row(rec, self.team.id)

        assert obj is not None
        assert obj.team_id == self.team.id
        assert obj.type == rec.type

    def test_returns_existing_row(self):
        rec = RECOMMENDATIONS[0]
        first = ensure_recommendation_row(rec, self.team.id)
        second = ensure_recommendation_row(rec, self.team.id)

        assert first is not None and second is not None
        assert first.id == second.id

    def test_skips_team_deleted_from_postgres(self):
        # A team present in ClickHouse but absent from Postgres yields a foreign-key violation
        # on create() — we should skip it (return None) rather than re-raise DoesNotExist.
        rec = RECOMMENDATIONS[0]
        deleted_team_id = self.team.id + 10_000_000
        assert not Team.objects.filter(id=deleted_team_id).exists()

        obj = ensure_recommendation_row(rec, deleted_team_id)

        assert obj is None
        assert not ErrorTrackingRecommendation.objects.filter(team_id=deleted_team_id).exists()


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
