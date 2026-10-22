import datetime as dt
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import AlertBatchKey, SourceEvaluationInputs, SourceKind
from products.alerts_platform.backend.facade.lifecycle import AlertState
from products.alerts_platform.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
    source_evaluation_timeout,
)
from products.metrics.backend.alert_source_cycle import BATCH_QUERY_BUDGET_SECONDS, MAX_QUERY_SECONDS
from products.metrics.backend.facade.contracts import MetricPoint, MetricSeries
from products.metrics.backend.facade.temporal import SOURCE_EVALUATION_ACTIVITIES, SOURCE_EVALUATION_WORKFLOWS
from products.metrics.backend.temporal.alert_evaluate import (
    EVALUATE_SCHEDULE_TO_CLOSE,
    EVALUATE_START_TO_CLOSE,
    EVALUATION_BUDGET,
)


class TestEvaluationTimeoutLadder(SimpleTestCase):
    """Constants only, so this takes no database."""

    def test_the_evaluation_timeout_ladder_holds(self) -> None:
        assert EVALUATE_START_TO_CLOSE.total_seconds() > BATCH_QUERY_BUDGET_SECONDS > MAX_QUERY_SECONDS
        assert EVALUATE_SCHEDULE_TO_CLOSE > EVALUATE_START_TO_CLOSE
        assert (EVALUATE_SCHEDULE_TO_CLOSE - EVALUATE_START_TO_CLOSE).total_seconds() >= BATCH_QUERY_BUDGET_SECONDS / 2
        assert source_evaluation_timeout(SourceKind.METRICS) > EVALUATION_BUDGET


_CYCLE = "products.metrics.backend.alert_source_cycle"


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_metrics_alert_fires_end_to_end_through_the_platform(environment: WorkflowEnvironment) -> None:
    """The whole chain the tick would run: source evaluation and the platform's record activity.
    Only the metrics query itself is replaced. A metrics configuration owns no destinations yet,
    so the evaluation starts no delivery."""
    cutoff = dt.datetime(2026, 9, 29, 10, tzinfo=dt.UTC)
    due_at = cutoff - dt.timedelta(minutes=5)

    def _seed() -> tuple[int, UUID]:
        organization = Organization.objects.create(name="metrics alerts")
        team = Team.objects.create(organization=organization, name="metrics alerts")
        with team_scope(team.id):
            configuration = platform_testing.create_configuration(
                team=team,
                name="API p95 latency",
                source_kind=SourceKind.METRICS.value,
                source_config={
                    "type": "MetricsAlertSource",
                    "clauses": [{"name": "a", "metric_name": "m1", "aggregation": "sum"}],
                    "condition": {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5},
                },
                check_interval_minutes=5,
                next_check_at=due_at,
            )
        return team.id, configuration.id

    team_id, configuration_id = await sync_to_async(_seed)()
    breaching = [
        MetricSeries(
            labels={},
            points=(MetricPoint(time=(due_at - dt.timedelta(minutes=5)).isoformat(), value=500.0),),
            metric_name="m1",
            clause="a",
        )
    ]
    client = environment.client
    evaluation_id = f"alerts-eval-metrics-{team_id}-{due_at.isoformat()}"
    with (
        patch(f"{_CYCLE}.fetch_live_metrics_checkpoint", return_value=None),
        patch(f"{_CYCLE}.run_metric_query", return_value=breaching),
        ThreadPoolExecutor(max_workers=4) as activity_executor,
    ):
        async with (
            Worker(
                client,
                task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                workflows=EVALUATION_WORKFLOWS + SOURCE_EVALUATION_WORKFLOWS,
                activities=EVALUATION_ACTIVITIES + SOURCE_EVALUATION_ACTIVITIES,
                activity_executor=activity_executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ),
            Worker(
                client,
                task_queue=settings.ALERTS_PLATFORM_DELIVERY_TASK_QUEUE,
                workflows=DELIVERY_WORKFLOWS,
                activities=DELIVERY_ACTIVITIES,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ),
        ):
            handle = await client.start_workflow(
                "metrics-alert-evaluate",
                SourceEvaluationInputs(
                    source=SourceKind.METRICS,
                    cutoff=cutoff.isoformat(),
                    batch_key=AlertBatchKey(team_id=team_id, slot=due_at.isoformat()),
                ),
                id=evaluation_id,
                task_queue=settings.ALERTS_PLATFORM_EVALUATION_TASK_QUEUE,
                execution_timeout=dt.timedelta(seconds=75),
            )
            assert await handle.result() == 0

    def _read() -> tuple[str | None, dt.datetime | None]:
        with team_scope(team_id):
            alert = platform_testing.alert_for(configuration_id)
            configuration = platform_testing.configuration(configuration_id)
        return (alert.state if alert else None), configuration.next_check_at

    state, next_check_at = await sync_to_async(_read)()
    assert state == AlertState.FIRING.value
    assert next_check_at is not None and next_check_at > cutoff
